from __future__ import annotations

import datetime as dt
import threading
import traceback
from pathlib import Path

try:
    import PySimpleGUI as sg
except Exception:
    raise SystemExit("PySimpleGUI not installed. Install with: python3 -m pip install --extra-index-url https://PySimpleGUI.net/install PySimpleGUI")

from .core import (
    Window,
    build_output,
    candidate_files,
    ensure_tools,
    parse_workers,
    precise_filter_parallel,
)
from .errors import PCAPPullerError
from .filters import COMMON_FILTERS, FILTER_EXAMPLES
from .time_parse import parse_dt_flexible
from .clean_cli import clean_pipeline
from .tools import which_or_error


def _open_advanced_settings(parent: "sg.Window", reco: dict, current: dict | None) -> dict | None:
    """Modal advanced settings editor. Returns overrides dict or existing current if cancelled."""
    cur = {
        "workers": (current.get("workers") if current else reco["workers"]),
        "batch": (current.get("batch") if current else reco["batch"]),
        "slop": (current.get("slop") if current else reco["slop"]),
        "trim_per_batch": (current.get("trim_per_batch") if current else reco["trim_per_batch"]),
    }
    layout = [
        [sg.Text("Advanced Settings (override recommendations)")],
        [sg.Text("Workers"), sg.Input(str(cur["workers"]), key="-A-WORKERS-", size=(8,1)), sg.Text("(use 'auto' or integer 1-64)")],
        [sg.Text("Batch size"), sg.Input(str(cur["batch"]), key="-A-BATCH-", size=(8,1))],
        [sg.Text("Slop min"), sg.Input(str(cur["slop"]), key="-A-SLOP-", size=(8,1))],
        [sg.Checkbox("Trim per batch", key="-A-TRIMPB-", default=bool(cur["trim_per_batch"]))],
        [sg.Button("Save"), sg.Button("Cancel")],
    ]
    win = sg.Window("Advanced Settings", layout, modal=True, keep_on_top=True)
    overrides = current or {}
    while True:
        ev, vals = win.read()
        if ev in (sg.WINDOW_CLOSED, "Cancel"):
            win.close()
            return current
        if ev == "Save":
            wv = (vals.get("-A-WORKERS-") or "auto").strip()
            if wv.lower() != "auto":
                try:
                    w_int = int(wv)
                    if not (1 <= w_int <= 64):
                        raise ValueError
                    overrides["workers"] = w_int
                except Exception:
                    sg.popup_error("Workers must be 'auto' or an integer 1-64")
                    continue
            else:
                overrides["workers"] = "auto"
            try:
                b_int = int(vals.get("-A-BATCH-") or reco["batch"])
                s_int = int(vals.get("-A-SLOP-") or reco["slop"])
                if b_int < 1 or s_int < 0:
                    raise ValueError
                overrides["batch"] = b_int
                overrides["slop"] = s_int
            except Exception:
                sg.popup_error("Batch size must be >=1 and Slop >=0")
                continue
            overrides["trim_per_batch"] = bool(vals.get("-A-TRIMPB-"))
            win.close()
            return overrides


def compute_recommended(duration_minutes: int) -> dict:
    """Compute recommended settings for stability/efficiency based on duration."""
    if duration_minutes <= 15:
        batch = 500
        slop = 120
    elif duration_minutes <= 60:
        batch = 400
        slop = 60
    elif duration_minutes <= 240:  # up to 4h
        batch = 300
        slop = 30
    elif duration_minutes <= 720:  # up to 12h
        batch = 200
        slop = 20
    else:  # >12h (all-day)
        batch = 150
        slop = 15
    return {
        "workers": "auto",
        "batch": batch,
        "slop": slop,
        "trim_per_batch": duration_minutes > 60,
    }


def _open_filters_dialog(parent: "sg.Window") -> str | None:
    """A simple searchable dialog of common display filters. Returns the selected string or None."""
    # Flatten categories into list of entries with category prefix
    entries = []
    for cat, items in COMMON_FILTERS.items():
        for it in items:
            entries.append(f"{cat}: {it}")
    # Add examples at the top
    entries = [f"Examples: {e}" for e in FILTER_EXAMPLES] + entries

    layout = [
        [sg.Text("Search"), sg.Input(key="-FSEARCH-", enable_events=True, expand_x=True)],
        [sg.Listbox(values=entries, key="-FLIST-", size=(80, 20), enable_events=True)],
        [sg.Button("Insert"), sg.Button("Close")],
    ]
    win = sg.Window("Display Filters", layout, modal=True, keep_on_top=True)
    selected: str | None = None
    current = entries
    while True:
        ev, vals = win.read()
        if ev in (sg.WINDOW_CLOSED, "Close"):
            break
        if ev == "-FSEARCH-":
            q = (vals.get("-FSEARCH-") or "").lower()
            if not q:
                current = entries
            else:
                current = [e for e in entries if q in e.lower()]
            win["-FLIST-"].update(current)
        elif ev == "-FLIST-" and vals.get("-FLIST-"):
            # Double-click support
            if isinstance(vals["-FLIST-"], list) and vals["-FLIST-"]:
                selected = vals["-FLIST-"][0]
        elif ev == "Insert":
            if isinstance(vals.get("-FLIST-"), list) and vals["-FLIST-"]:
                selected = vals["-FLIST-"][0]
                break
    win.close()
    if selected:
        # Strip category prefix
        if ":" in selected:
            selected = selected.split(":", 1)[1].strip()
        return selected
    return None


def compute_clean_defaults(out_path: Path, main_filter: str | None) -> dict:
    try:
        st = out_path.stat()
        size = st.st_size
    except Exception:
        size = 0
    suffix = out_path.suffix.lower()
    # Heuristics
    keep_format = (suffix == ".pcap")  # already pcap => keep; pcapng => try convert
    reorder = True
    snaplen = 256
    split_seconds = 60 if size >= (2 * 1024 * 1024 * 1024) else None  # 2 GiB threshold
    return {
        "keep_format": keep_format,
        "reorder": reorder,
        "snaplen": snaplen,
        "filter": (main_filter or ""),
        "split_seconds": split_seconds,
        "split_packets": None,
        "out_dir": str(out_path.with_name(out_path.name + "_clean")),
    }


def run_puller(values, window: "sg.Window", stop_flag, adv_overrides: dict | None):
    try:
        start = parse_dt_flexible(values["-START-"])
        # Duration from Hours/Minutes sliders (clamped to same calendar day)
        hours = int(values.get("-HOURS-", 0) or 0)
        mins = int(values.get("-MINS-", 0) or 0)
        total_minutes = (hours * 60) + mins
        if hours >= 24:
            total_minutes = 1440
        if total_minutes <= 0:
            raise PCAPPullerError("Duration must be greater than 0 minutes")
        desired_end = start + dt.timedelta(minutes=total_minutes)
        if desired_end.date() != start.date():
            # Clamp to end of day
            desired_end = dt.datetime.combine(start.date(), dt.time(23, 59, 59, 999999))
        w = Window(start=start, end=desired_end)
        roots = [Path(values["-ROOT-"])] if values["-ROOT-"] else []
        if not roots:
            raise PCAPPullerError("Root directory is required")
        tmpdir = Path(values["-TMP-"]) if values["-TMP-"] else None
        display_filter = values["-DFILTER-"] or None
        verbose = bool(values.get("-VERBOSE-"))

        ensure_tools(display_filter, precise_filter=values["-PRECISE-"])

        # Recommended settings based on duration
        reco = compute_recommended(total_minutes)
        # Apply overrides if provided
        eff_slop = int(adv_overrides.get("slop", reco["slop"])) if adv_overrides else reco["slop"]

        def progress(phase, current, total):
            if stop_flag["stop"]:
                raise PCAPPullerError("Cancelled")
            window.write_event_value("-PROGRESS-", (phase, current, total))

        # Prefilter by mtime using effective slop
        pre_candidates = candidate_files(roots, w, eff_slop, progress=progress)

        # Determine workers now that we know candidate count
        if adv_overrides and str(adv_overrides.get("workers", "auto")).strip().lower() != "auto":
            try:
                workers = parse_workers(int(adv_overrides["workers"]), total_files=len(pre_candidates))
            except Exception:
                workers = parse_workers("auto", total_files=len(pre_candidates))
        else:
            workers = parse_workers("auto", total_files=len(pre_candidates))

        # Optional precise filter
        cands = pre_candidates
        if values["-PRECISE-"] and pre_candidates:
            cands = precise_filter_parallel(cands, w, workers=workers, progress=progress)

        if values["-DRYRUN-"]:
            window.write_event_value("-DONE-", f"Dry-run: {len(cands)} survivors")
            return

        outp = Path(values["-OUT-"])

        eff_batch = int(adv_overrides.get("batch", reco["batch"])) if adv_overrides else reco["batch"]
        eff_trim_pb = bool(adv_overrides.get("trim_per_batch", reco["trim_per_batch"])) if adv_overrides else reco["trim_per_batch"]

        result = build_output(
            cands,
            w,
            outp,
            tmpdir,
            eff_batch,
            values["-FORMAT-"],
            display_filter,
            bool(values["-GZIP-"]),
            progress=progress,
            verbose=verbose,
            trim_per_batch=eff_trim_pb,
        )
        window.write_event_value("-DONE-", f"Done: wrote {result}")
        # Provide a hint to the event loop about the output path
        window.write_event_value("-MERGE-RESULT-", str(result))
    except Exception as e:
        tb = traceback.format_exc()
        window.write_event_value("-DONE-", f"Error: {e}\n{tb}")


def main():
    sg.theme("SystemDefault")
    layout = [
        [sg.Text("Root"), sg.Input(key="-ROOT-", expand_x=True), sg.FolderBrowse()],
        [sg.Text("Start (YYYY-MM-DD HH:MM:SS)"), sg.Input(key="-START-", expand_x=True)],
        [sg.Text("Duration"),
         sg.Text("Hours"), sg.Slider(range=(0, 24), orientation="h", key="-HOURS-", default_value=0, size=(20,15), enable_events=True),
         sg.Text("Minutes"), sg.Slider(range=(0, 59), orientation="h", key="-MINS-", default_value=15, size=(20,15), enable_events=True),
         sg.Button("All day", key="-ALLDAY-")],
        [sg.Text("Output"), sg.Input(key="-OUT-", expand_x=True), sg.FileSaveAs()],
        [sg.Text("Tmpdir"), sg.Input(key="-TMP-", expand_x=True), sg.FolderBrowse()],
        [sg.Checkbox("Precise filter", key="-PRECISE-", tooltip="More accurate: drops files with no packets in window (uses capinfos)")],
        [sg.Text("Display filter"), sg.Input(key="-DFILTER-", expand_x=True), sg.Button("Display Filters...", key="-DFILTERS-")],
        [sg.Text("Format"), sg.Combo(values=["pcap","pcapng"], default_value="pcapng", key="-FORMAT-"),
         sg.Checkbox("Gzip", key="-GZIP-"), sg.Checkbox("Dry run", key="-DRYRUN-"),
         sg.Checkbox("Verbose", key="-VERBOSE-")],
        [sg.Text("Using recommended settings based on duration. Customize in Settings.", key="-RECO-INFO-", size=(100,2), text_color="gray")],
        [sg.Text("Precise filter analyzes files and discards those without packets in the time window.", key="-PF-HELP-", visible=False, text_color="gray")],
        [sg.Frame("Clean merged output (optional)", [
            [sg.Checkbox("Enable clean step", key="-CLEAN-ENABLE-", default=False), sg.Button("Run Clean Now", key="-RUN-CLEAN-"), sg.Button("Set defaults from merged file", key="-CLEAN-SET-DEFAULTS-")],
            [sg.Checkbox("Keep original format (do not convert to pcap)", key="-CLEAN-KEEPFMT-", default=False), sg.Checkbox("Reorder timestamps", key="-CLEAN-REORDER-", default=True)],
            [sg.Text("Snaplen"), sg.Input("256", key="-CLEAN-SNAPLEN-", size=(8,1)), sg.Text("Filter"), sg.Input(key="-CLEAN-FILTER-", expand_x=True), sg.Button("Use main filter", key="-CLEAN-COPY-FILTER-")],
            [sg.Text("Start"), sg.Input(key="-CLEAN-START-", size=(22,1)), sg.Text("End"), sg.Input(key="-CLEAN-END-", size=(22,1))],
            [sg.Text("Split seconds"), sg.Input(key="-CLEAN-SPLITSEC-", size=(8,1)), sg.Text("Split packets"), sg.Input(key="-CLEAN-SPLITPKT-", size=(10,1))],
            [sg.Text("Out dir"), sg.Input(key="-CLEAN-OUTDIR-", expand_x=True), sg.FolderBrowse("Browse...")],
        ], expand_x=True, relief=sg.RELIEF_SUNKEN)],
        [sg.Text("", key="-STATUS-", size=(80,1))],
        [sg.ProgressBar(100, orientation="h", size=(40, 20), key="-PB-")],
        [sg.Text("", expand_x=True), sg.Button("Settings...", key="-SETTINGS-"), sg.Button("Run"), sg.Button("Cancel"), sg.Button("Exit")],
        [sg.Output(size=(100, 20))]
    ]
    window = sg.Window("PCAPpuller", layout)
    stop_flag = {"stop": False}
    worker = None
    clean_worker = None
    adv_overrides: dict | None = None
    last_merged_path: Path | None = None

    def _update_reco_label():
        try:
            h = int(values.get("-HOURS-", 0) or 0)
            m = int(values.get("-MINS-", 0) or 0)
            dur = min(h*60 + m, 1440)
            reco = compute_recommended(dur)
            parts = [
                f"workers={reco['workers']}",
                f"batch={reco['batch']}",
                f"slop={reco['slop']}",
                f"trim-per-batch={'on' if reco['trim_per_batch'] else 'off'}",
            ]
            suffix = " (Advanced overrides active)" if adv_overrides else ""
            window["-RECO-INFO-"].update("Recommended: " + ", ".join(parts) + suffix)
        except Exception:
            pass

    def _populate_clean_defaults_from_path(p: Path):
        try:
            d = compute_clean_defaults(p, values.get("-DFILTER-") or None)
            window["-CLEAN-KEEPFMT-"].update(d["keep_format"])
            window["-CLEAN-REORDER-"].update(d["reorder"])
            window["-CLEAN-SNAPLEN-"].update(str(d["snaplen"]))
            window["-CLEAN-FILTER-"].update(d["filter"])
            window["-CLEAN-SPLITSEC-"].update("" if d["split_seconds"] is None else str(d["split_seconds"]))
            window["-CLEAN-SPLITPKT-"].update("")
            window["-CLEAN-OUTDIR-"].update(d["out_dir"]) 
            window["-CLEAN-ENABLE-"].update(True)
        except Exception:
            pass

    def _run_clean_thread(vals):
        try:
            in_path = Path(vals["-OUT-"])
            if not in_path.exists():
                window.write_event_value("-CLEAN-DONE-", f"Error: merged file not found: {in_path}")
                return
            if str(in_path).endswith(".gz"):
                window.write_event_value("-CLEAN-DONE-", "Error: cleaning currently does not support .gz outputs. Disable Gzip and retry.")
                return
            out_dir = Path(vals.get("-CLEAN-OUTDIR-") or (in_path.with_name(in_path.name + "_clean")))
            # Validate tools
            try:
                which_or_error("editcap")
                if vals.get("-CLEAN-REORDER-"):
                    which_or_error("reordercap")
                if (vals.get("-CLEAN-FILTER-") or "").strip():
                    which_or_error("tshark")
            except Exception as te:
                window.write_event_value("-CLEAN-DONE-", f"Error: {te}")
                return
            # Parse optional times
            start_dt = parse_dt_flexible(vals.get("-CLEAN-START-") or "") if (vals.get("-CLEAN-START-") or "").strip() else None
            end_dt = parse_dt_flexible(vals.get("-CLEAN-END-") or "") if (vals.get("-CLEAN-END-") or "").strip() else None
            snaplen_str = (vals.get("-CLEAN-SNAPLEN-") or "").strip()
            snaplen = int(snaplen_str) if snaplen_str else 256
            splitsec_str = (vals.get("-CLEAN-SPLITSEC-") or "").strip()
            splitpkt_str = (vals.get("-CLEAN-SPLITPKT-") or "").strip()
            split_seconds = int(splitsec_str) if splitsec_str else None
            split_packets = int(splitpkt_str) if splitpkt_str else None

            outs = clean_pipeline(
                input_path=in_path,
                out_dir=out_dir,
                keep_format=bool(vals.get("-CLEAN-KEEPFMT-")),
                do_reorder=bool(vals.get("-CLEAN-REORDER-")),
                snaplen=snaplen,
                start_dt=start_dt,
                end_dt=end_dt,
                display_filter=(vals.get("-CLEAN-FILTER-") or None),
                split_seconds=split_seconds,
                split_packets=split_packets,
                verbose=bool(vals.get("-VERBOSE-")),
            )
            if len(outs) == 1:
                window.write_event_value("-CLEAN-DONE-", f"Clean done: {outs[0]}")
            else:
                msg = "Clean done (chunks):\n" + "\n".join(f"  {p}" for p in outs)
                window.write_event_value("-CLEAN-DONE-", msg)
        except Exception as e:
            tb = traceback.format_exc()
            window.write_event_value("-CLEAN-DONE-", f"Error: {e}\n{tb}")

    while True:
        event, values = window.read(timeout=200)
        if event in (sg.WINDOW_CLOSED, "Exit"):
            stop_flag["stop"] = True
            break
        if event == "Run" and worker is None:
            # Compute total minutes
            hours_val = int(values.get("-HOURS-", 0) or 0)
            mins_val = int(values.get("-MINS-", 0) or 0)
            total_minutes = min(hours_val * 60 + mins_val, 1440)
            if total_minutes > 60:
                resp = sg.popup_ok_cancel(
                    "Warning: Long window (>60 min) can take a long time and use large temp space.\n" \
                    "Consider setting Tmpdir to a large filesystem and using Dry run first.",
                    title="Long window warning",
                )
                if resp != "OK":
                    continue
            stop_flag["stop"] = False
            window["-STATUS-"].update("Scanning root... (this may take time on NAS)")
            worker = threading.Thread(target=run_puller, args=(values, window, stop_flag, adv_overrides), daemon=True)
            worker.start()
        elif event == "Cancel":
            stop_flag["stop"] = True
            window["-STATUS-"].update("Cancelling...")
        elif event == "-SETTINGS-":
            # Open advanced settings dialog
            adv_overrides = _open_advanced_settings(window, compute_recommended(min(int(values.get("-HOURS-",0) or 0)*60 + int(values.get("-MINS-",0) or 0), 1440)), adv_overrides)
            _update_reco_label()
        elif event in ("-HOURS-", "-MINS-"):
            _update_reco_label()
        elif event == "-PRECISE-":
            window["-PF-HELP-"].update(visible=bool(values.get("-PRECISE-")))
        elif event == "-ALLDAY-":
            # Set start to midnight of provided date (or today) and duration to 24h
            try:
                start_str = (values.get("-START-") or "").strip()
                import datetime as _dt
                if start_str:
                    base = parse_dt_flexible(start_str)
                    midnight = _dt.datetime.combine(base.date(), _dt.time.min)
                else:
                    now = _dt.datetime.now()
                    midnight = _dt.datetime.combine(now.date(), _dt.time.min)
                window["-START-"].update(midnight.strftime("%Y-%m-%d %H:%M:%S"))
                window["-HOURS-"].update(24)
                window["-MINS-"].update(0)
            except Exception:
                # If parse fails, just set time to today's midnight
                import datetime as _dt
                now = _dt.datetime.now()
                midnight = _dt.datetime.combine(now.date(), _dt.time.min)
                window["-START-"].update(midnight.strftime("%Y-%m-%d %H:%M:%S"))
                window["-HOURS-"].update(24)
                window["-MINS-"].update(0)
        elif event == "-DFILTERS-":
            picked = _open_filters_dialog(window)
            if picked:
                prev = values.get("-DFILTER-") or ""
                if prev and not prev.endswith(" "):
                    prev += " "
                window["-DFILTER-"].update(prev + picked)
        elif event == "-PROGRESS-":
            phase, cur, tot = values[event]
            # Status text
            if str(phase).startswith("scan"):
                window["-STATUS-"].update(f"Scanning... {cur} files visited")
                # Pulse the bar in indeterminate mode
                window["-PB-"].update(cur % 100)
            else:
                window["-STATUS-"].update(f"{phase} {cur}/{tot}")
                pct = 0 if tot <= 0 else int((cur / tot) * 100)
                window["-PB-"].update(pct)
            print(f"{phase}: {cur}/{tot}")
        elif event == "-DONE-":
            print(values[event])
            worker = None
            window["-PB-"].update(0)
            window["-STATUS-"].update("")
        elif event == "-MERGE-RESULT-":
            try:
                last_merged_path = Path(values[event])
                _populate_clean_defaults_from_path(last_merged_path)
            except Exception:
                pass
        elif event == "-CLEAN-COPY-FILTER-":
            window["-CLEAN-FILTER-"].update(values.get("-DFILTER-") or "")
        elif event == "-CLEAN-SET-DEFAULTS-":
            try:
                p = Path(values.get("-OUT-") or "")
                if p and p.exists():
                    _populate_clean_defaults_from_path(p)
                else:
                    sg.popup_error("Output file does not exist yet. Run the merge first, then set defaults.")
            except Exception:
                pass
        elif event == "-RUN-CLEAN-":
            if not values.get("-CLEAN-ENABLE-"):
                resp = sg.popup_ok_cancel("Enable 'Clean' to proceed?", title="Clean not enabled")
                if resp != "OK":
                    continue
                window["-CLEAN-ENABLE-"].update(True)
            if clean_worker is None:
                window["-STATUS-"].update("Cleaning...")
                clean_worker = threading.Thread(target=_run_clean_thread, args=(values,), daemon=True)
                clean_worker.start()
        elif event == "-CLEAN-DONE-":
            print(values[event])
            clean_worker = None
            window["-STATUS-"].update("")
    window.close()
