#!/usr/bin/env python3
"""
GUI frontend for PCAPpuller using PySimpleGUI.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path
import datetime as dt

try:
    import PySimpleGUI as sg
except Exception:
    raise SystemExit("PySimpleGUI not installed. Install with: python3 -m pip install PySimpleGUI")

from pcappuller.core import (
    Window,
    build_output,
    candidate_files,
    ensure_tools,
    parse_workers,
    precise_filter_parallel,
)
from pcappuller.time_parse import parse_dt_flexible
from pcappuller.errors import PCAPPullerError
from pcappuller.filters import COMMON_FILTERS, FILTER_EXAMPLES


def compute_recommended(duration_minutes: int) -> dict:
    if duration_minutes <= 15:
        batch = 500
        slop = 120
    elif duration_minutes <= 60:
        batch = 400
        slop = 60
    elif duration_minutes <= 240:
        batch = 300
        slop = 30
    elif duration_minutes <= 720:
        batch = 200
        slop = 20
    else:
        batch = 150
        slop = 15
    return {"workers": "auto", "batch": batch, "slop": slop, "trim_per_batch": duration_minutes > 60}


def _open_advanced_settings(parent: "sg.Window", reco: dict, current: dict | None) -> dict | None:
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


def _open_filters_dialog(parent: "sg.Window") -> str | None:
    # Flatten categories into a searchable list
    entries = [f"Examples: {e}" for e in FILTER_EXAMPLES]
    for cat, items in COMMON_FILTERS.items():
        for it in items:
            entries.append(f"{cat}: {it}")
    layout = [
        [sg.Text("Search"), sg.Input(key="-FSEARCH-", enable_events=True, expand_x=True)],
        [sg.Listbox(values=entries, key="-FLIST-", size=(80, 20), enable_events=True)],
        [sg.Button("Insert"), sg.Button("Close")],
    ]
    win = sg.Window("Display Filters", layout, modal=True, keep_on_top=True)
    selected = None
    current = entries
    while True:
        ev, vals = win.read()
        if ev in (sg.WINDOW_CLOSED, "Close"):
            break
        if ev == "-FSEARCH-":
            q = (vals.get("-FSEARCH-") or "").lower()
            current = [e for e in entries if q in e.lower()] if q else entries
            win["-FLIST-"].update(current)
        elif ev == "-FLIST-" and vals.get("-FLIST-"):
            if isinstance(vals["-FLIST-"], list) and vals["-FLIST-"]:
                selected = vals["-FLIST-"][0]
        elif ev == "Insert":
            if isinstance(vals.get("-FLIST-"), list) and vals["-FLIST-"]:
                selected = vals["-FLIST-"][0]
                break
    win.close()
    if selected:
        if ":" in selected:
            selected = selected.split(":", 1)[1].strip()
        return selected
    return None


def run_puller(values, window: "sg.Window", stop_flag, adv_overrides: dict | None):
    try:
        start = parse_dt_flexible(values["-START-"])
        # Hours/Minutes sliders
        hours = int(values.get("-HOURS-", 0) or 0)
        mins = int(values.get("-MINS-", 0) or 0)
        total_minutes = min(hours * 60 + mins, 1440)
        if total_minutes <= 0:
            raise PCAPPullerError("Duration must be greater than 0 minutes")
        desired_end = start + dt.timedelta(minutes=total_minutes)
        if desired_end.date() != start.date():
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
    except Exception as e:
        tb = traceback.format_exc()
        window.write_event_value("-DONE-", f"Error: {e}\n{tb}")


def main():
    sg.theme("SystemDefault")
    layout = [
        [sg.Text("Root"), sg.Input(key="-ROOT-", expand_x=True), sg.FolderBrowse()],
        [sg.Text("Start (YYYY-MM-DD HH:MM:SS)"), sg.Input(key="-START-", expand_x=True)],
        [sg.Text("Duration"), sg.Text("Hours"), sg.Slider(range=(0, 24), orientation="h", key="-HOURS-", default_value=0, size=(20,15), enable_events=True),
         sg.Text("Minutes"), sg.Slider(range=(0, 59), orientation="h", key="-MINS-", default_value=15, size=(20,15), enable_events=True), sg.Button("All day", key="-ALLDAY-")],
        [sg.Text("Output"), sg.Input(key="-OUT-", expand_x=True), sg.FileSaveAs()],
        [sg.Text("Tmpdir"), sg.Input(key="-TMP-", expand_x=True), sg.FolderBrowse()],
        [sg.Checkbox("Precise filter", key="-PRECISE-", tooltip="More accurate: drops files with no packets in window (uses capinfos)")],
        [sg.Text("Display filter"), sg.Input(key="-DFILTER-", expand_x=True), sg.Button("Display Filters...", key="-DFILTERS-")],
        [sg.Text("Format"), sg.Combo(values=["pcap","pcapng"], default_value="pcapng", key="-FORMAT-"),
         sg.Checkbox("Gzip", key="-GZIP-"), sg.Checkbox("Dry run", key="-DRYRUN-"),
         sg.Checkbox("Verbose", key="-VERBOSE-")],
        [sg.Text("Using recommended settings based on duration.", key="-RECO-INFO-", size=(100,2), text_color="gray")],
        [sg.Text("Precise filter analyzes files and discards those without packets in the time window.", key="-PF-HELP-", visible=False, text_color="gray")],
        [sg.Text("", key="-STATUS-", size=(80,1))],
        [sg.ProgressBar(100, orientation="h", size=(40, 20), key="-PB-")],
        [sg.Text("", expand_x=True), sg.Button("Settings...", key="-SETTINGS-"), sg.Button("Run"), sg.Button("Cancel"), sg.Button("Exit")],
        [sg.Output(size=(100, 20))]
    ]
    window = sg.Window("PCAPpuller", layout)
    stop_flag = {"stop": False}
    worker = None
    adv_overrides: dict | None = None

    def _update_reco_label():
        try:
            h = int(values.get("-HOURS-", 0) or 0)
            m = int(values.get("-MINS-", 0) or 0)
            dur = min(h*60 + m, 1440)
            reco = compute_recommended(dur)
            parts = [f"workers={reco['workers']}", f"batch={reco['batch']}", f"slop={reco['slop']}", f"trim-per-batch={'on' if reco['trim_per_batch'] else 'off'}"]
            window["-RECO-INFO-"].update("Recommended: " + ", ".join(parts) + (" (Advanced overrides active)" if adv_overrides else ""))
        except Exception:
            pass

    while True:
        event, values = window.read(timeout=200)
        if event in (sg.WINDOW_CLOSED, "Exit"):
            stop_flag["stop"] = True
            break
        if event == "Run" and worker is None:
            # Warn on long window
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
            adv_overrides = _open_advanced_settings(window, compute_recommended(min(int(values.get("-HOURS-",0) or 0)*60 + int(values.get("-MINS-",0) or 0), 1440)), adv_overrides)
            _update_reco_label()
        elif event in ("-HOURS-", "-MINS-"):
            _update_reco_label()
        elif event == "-PRECISE-":
            window["-PF-HELP-"].update(visible=bool(values.get("-PRECISE-")))
        elif event == "-ALLDAY-":
            # Set start to midnight and 24h duration
            try:
                import datetime as _dt
                start_str = (values.get("-START-") or "").strip()
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
            if str(phase).startswith("scan"):
                window["-STATUS-"].update(f"Scanning... {cur} files visited")
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
    window.close()
    window.close()


if __name__ == "__main__":
    main()
