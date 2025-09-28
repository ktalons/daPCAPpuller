from __future__ import annotations

import threading
import traceback
from pathlib import Path
import datetime as dt

try:
    import PySimpleGUI as sg
except Exception:
    raise SystemExit("PySimpleGUI not installed. Install with: python3 -m pip install PySimpleGUI")

from .core import (
    Window,
    build_output,
    candidate_files,
    ensure_tools,
    parse_workers,
    precise_filter_parallel,
)
from .time_parse import parse_dt_flexible
from .errors import PCAPPullerError


def run_puller(values, window: "sg.Window", stop_flag):
    try:
        start = parse_dt_flexible(values["-START-"])
        minutes = int(values["-MINUTES-"])
        w = Window(start=start, end=start + dt.timedelta(minutes=minutes))
        roots = [Path(values["-ROOT-"])] if values["-ROOT-"] else []
        if not roots:
            raise PCAPPullerError("Root directory is required")
        tmpdir = Path(values["-TMP-"]) if values["-TMP-"] else None
        workers = parse_workers(values["-WORKERS-"] or "auto", total_files=1000)
        display_filter = values["-DFILTER-"] or None
        verbose = bool(values.get("-VERBOSE-"))

        ensure_tools(display_filter, precise_filter=values["-PRECISE-"])

        def progress(phase, current, total):
            if stop_flag["stop"]:
                raise PCAPPullerError("Cancelled")
            window.write_event_value("-PROGRESS-", (phase, current, total))

        cands = candidate_files(roots, w, int(values["-SLOP-"]))
        if values["-PRECISE-"]:
            cands = precise_filter_parallel(cands, w, workers=workers, progress=progress)

        if values["-DRYRUN-"]:
            window.write_event_value("-DONE-", f"Dry-run: {len(cands)} survivors")
            return

        outp = Path(values["-OUT-"])
        result = build_output(
            cands,
            w,
            outp,
            tmpdir,
            int(values["-BATCH-"]),
            values["-FORMAT-"],
            display_filter,
            bool(values["-GZIP-"]),
            progress=progress,
            verbose=verbose,
        )
        window.write_event_value("-DONE-", f"Done: wrote {result}")
    except Exception as e:
        tb = traceback.format_exc()
        window.write_event_value("-DONE-", f"Error: {e}\n{tb}")


def main():
    sg.theme("SystemDefault")
    layout = [
        [sg.Text("Root"), sg.Input(key="-ROOT-"), sg.FolderBrowse()],
        [sg.Text("Start (YYYY-MM-DD HH:MM:SS)"), sg.Input(key="-START-")],
        [sg.Text("Minutes"), sg.Slider(range=(1, 60), orientation="h", key="-MINUTES-", default_value=15)],
        [sg.Text("Output"), sg.Input(key="-OUT-"), sg.FileSaveAs()],
        [sg.Text("Tmpdir"), sg.Input(key="-TMP-"), sg.FolderBrowse()],
        [sg.Checkbox("Precise filter (capinfos)", key="-PRECISE-"),
         sg.Text("Workers"), sg.Input(key="-WORKERS-", size=(6,1))],
        [sg.Text("Display filter"), sg.Input(key="-DFILTER-")],
        [sg.Text("Batch size"), sg.Input("500", key="-BATCH-", size=(6,1)),
         sg.Text("Slop min"), sg.Input("120", key="-SLOP-", size=(6,1)),
         sg.Combo(values=["pcap","pcapng"], default_value="pcapng", key="-FORMAT-"),
         sg.Checkbox("Gzip", key="-GZIP-"), sg.Checkbox("Dry run", key="-DRYRUN-"),
         sg.Checkbox("Verbose", key="-VERBOSE-")],
        [sg.ProgressBar(100, orientation="h", size=(40, 20), key="-PB-")],
        [sg.Button("Run"), sg.Button("Cancel"), sg.Button("Exit")],
        [sg.Output(size=(100, 20))]
    ]
    window = sg.Window("PCAPpuller", layout)
    stop_flag = {"stop": False}
    worker = None
    while True:
        event, values = window.read(timeout=200)
        if event in (sg.WINDOW_CLOSED, "Exit"):
            stop_flag["stop"] = True
            break
        if event == "Run" and worker is None:
            stop_flag["stop"] = False
            worker = threading.Thread(target=run_puller, args=(values, window, stop_flag), daemon=True)
            worker.start()
        elif event == "Cancel":
            stop_flag["stop"] = True
        elif event == "-PROGRESS-":
            phase, cur, tot = values[event]
            pct = int((cur / max(tot, 1)) * 100)
            window["-PB-"].update(pct)
            print(f"{phase}: {cur}/{tot}")
        elif event == "-DONE-":
            print(values[event])
            worker = None
            window["-PB-"].update(0)
    window.close()
