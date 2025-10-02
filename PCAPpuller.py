#!/usr/bin/env python3
"""
PCAPpuller CLI
Refactored to use pcappuller.core with improved parsing, logging, and optional GUI support (gui_pcappuller.py).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List
import csv

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm not installed. Please run: python3 -m pip install tqdm", file=sys.stderr)
    sys.exit(1)

from pcappuller.core import (
    Window,
    build_output,
    candidate_files,
    ensure_tools,
    parse_workers,
    precise_filter_parallel,
    summarize_first_last,
    collect_file_metadata,
)
from pcappuller.errors import PCAPPullerError
from pcappuller.logging_setup import setup_logging
from pcappuller.time_parse import parse_start_and_window
from pcappuller.cache import CapinfosCache, default_cache_path


class ExitCodes:
    OK = 0
    ARGS = 2
    TIME = 3
    RANGE = 5
    OSERR = 10
    TOOL = 11


def parse_args():
    ap = argparse.ArgumentParser(
        description="Select PCAPs by date/time and merge into a single file (up to 24 hours within a single calendar day).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--root",
        required=True,
        nargs="+",
        help="One or more root directories (searched recursively).",
    )
    ap.add_argument("--start", required=True, help="Start datetime: 'YYYY-MM-DD HH:MM:SS' (local time).")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--minutes", type=int, help="Duration in minutes (1-1440). Clamped to end-of-day if it would cross midnight.")
    group.add_argument("--end", help="End datetime (must be same calendar day as start).")

    ap.add_argument("--out", help="Output path (required unless --dry-run).")
    ap.add_argument("--batch-size", type=int, default=500, help="Files per merge batch.")
    ap.add_argument("--slop-min", type=int, default=120, help="Extra minutes around window for mtime prefilter.")
    ap.add_argument("--tmpdir", default=None, help="Directory for temporary files (defaults to system temp).")
    ap.add_argument("--precise-filter", action="store_true", help="Use capinfos to drop files without packets in window.")
    ap.add_argument("--workers", default="auto", help="Parallel workers for precise filter: 'auto' or an integer.")
    ap.add_argument("--display-filter", default=None, help="Wireshark display filter applied via tshark after trimming.")
    ap.add_argument("--out-format", choices=["pcap", "pcapng"], default="pcapng", help="Final capture format.")
    ap.add_argument("--gzip", action="store_true", help="Compress final output to .gz (recommended to use .gz extension).")
    ap.add_argument("--dry-run", action="store_true", help="Preview survivors and exit (no merge/trim).")
    ap.add_argument("--trim-per-batch", action="store_true", help="Trim each merge batch before final merge (reduces temp size for long windows).")
    ap.add_argument("--list-out", default=None, help="With --dry-run, write survivors to FILE (.txt or .csv).")
    ap.add_argument("--debug-capinfos", type=int, default=0, help="Print parsed capinfos times for first N files (verbose only).")
    ap.add_argument("--summary", action="store_true", help="With --dry-run, print min/max packet times across survivors.")
    ap.add_argument("--verbose", action="store_true", help="Enable verbose logging and show external tool output.")
    ap.add_argument("--report", default=None, help="Write CSV report for survivors (path,size,mtime,first,last).")
    ap.add_argument("--cache", default="auto", help="Path to capinfos cache database or 'auto'.")
    ap.add_argument("--no-cache", action="store_true", help="Disable capinfos metadata cache.")
    ap.add_argument("--clear-cache", action="store_true", help="Clear the capinfos cache before running.")

    args = ap.parse_args()

    if not args.dry_run and not args.out:
        ap.error("--out is required unless --dry-run is set.")

    if args.minutes is not None and not (1 <= args.minutes <= 1440):
        ap.error("--minutes must be between 1 and 1440.")
    return args


def write_list(paths: List[Path], list_out: Path):
    list_out.parent.mkdir(parents=True, exist_ok=True)
    if list_out.suffix.lower() == ".csv":
        with open(list_out, "w", encoding="utf-8") as f:
            f.write("path\n")
            for p in paths:
                f.write(f"{p}\n")
    else:
        with open(list_out, "w", encoding="utf-8") as f:
            for p in paths:
                f.write(str(p) + "\n")


def main():
    args = parse_args()
    setup_logging(args.verbose)

    try:
        start, end = parse_start_and_window(args.start, args.minutes, args.end)
        window = Window(start=start, end=end)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(ExitCodes.TIME)

    try:
        need_precise = args.precise_filter or bool(args.report)
        ensure_tools(args.display_filter, precise_filter=need_precise)

        # Cache setup
        cache = None
        if not args.no_cache:
            cache_path = default_cache_path() if args.cache == "auto" else Path(args.cache)
            cache = CapinfosCache(cache_path)
            if args.clear_cache:
                cache.clear()

        roots = [Path(r) for r in args.root]
        pre_candidates = candidate_files(roots, window, args.slop_min)

        workers = parse_workers(args.workers, total_files=len(pre_candidates))
        if args.precise_filter and pre_candidates:
            # tqdm progress bridge
            prog_total = len(pre_candidates)
            pbar = tqdm(total=prog_total, desc="Precise filtering", unit="file")

            def cb(_phase, cur, _tot):
                pbar.n = cur
                pbar.refresh()

            candidates = precise_filter_parallel(pre_candidates, window, workers, args.debug_capinfos, progress=cb, cache=cache)
            pbar.close()
        else:
            candidates = pre_candidates

        if args.dry_run:
            print("Dry run:")
            print(f"  Found by mtime prefilter: {len(pre_candidates)}")
            if args.precise_filter:
                print(f"  Survived precise filter: {len(candidates)}")
            else:
                print(f"  Survivors (mtime-only):  {len(candidates)}")
            if args.list_out:
                write_list(candidates, Path(args.list_out))
                print(f"  Wrote list to: {args.list_out}")
            if args.report and candidates:
                md = collect_file_metadata(candidates, workers=max(1, workers // 2), cache=cache)
                outp = Path(args.report)
                outp.parent.mkdir(parents=True, exist_ok=True)
                with open(outp, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["path","size_bytes","mtime_epoch","mtime_utc","first_epoch","last_epoch","first_utc","last_utc"])
                    import datetime as _dt
                    for r in md:
                        m_utc = _dt.datetime.fromtimestamp(r["mtime"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")
                        fu = _dt.datetime.fromtimestamp(r["first"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ") if r["first"] is not None else ""
                        lu = _dt.datetime.fromtimestamp(r["last"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ") if r["last"] is not None else ""
                        w.writerow([str(r["path"]), r["size"], r["mtime"], m_utc, r["first"], r["last"], fu, lu])
                print(f"  Wrote report to: {outp}")
            if args.summary and candidates:
                s = summarize_first_last(candidates, workers=max(1, workers // 2), cache=cache)
                if s:
                    import datetime as _dt
                    f_utc = _dt.datetime.fromtimestamp(s[0], _dt.timezone.utc)
                    l_utc = _dt.datetime.fromtimestamp(s[1], _dt.timezone.utc)
                    print(f"  Packet time range across survivors (UTC): {f_utc}Z .. {l_utc}Z")
            sys.exit(ExitCodes.OK)

        if not candidates:
            print("No target PCAP files found after filtering.", file=sys.stderr)
            sys.exit(ExitCodes.OK)

        # Merge/Trim/Filter/Write with progress bars
        out_path = Path(args.out)
        # merge batches
        def pb_phase(phase: str, cur: int, tot: int):
            pass  # placeholder for potential future CLI pb per phase

        # Optional reporting before writing
        if args.report and candidates:
            md = collect_file_metadata(candidates, workers=max(1, workers // 2), cache=cache)
            outp = Path(args.report)
            outp.parent.mkdir(parents=True, exist_ok=True)
            with open(outp, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["path","size_bytes","mtime_epoch","mtime_utc","first_epoch","last_epoch","first_utc","last_utc"])
                import datetime as _dt
                for r in md:
                    m_utc = _dt.datetime.fromtimestamp(r["mtime"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ")
                    fu = _dt.datetime.fromtimestamp(r["first"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ") if r["first"] is not None else ""
                    lu = _dt.datetime.fromtimestamp(r["last"], _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%fZ") if r["last"] is not None else ""
                    w.writerow([str(r["path"]), r["size"], r["mtime"], m_utc, r["first"], r["last"], fu, lu])
            print(f"Wrote report to: {outp}")

        duration_minutes = int((window.end - window.start).total_seconds() // 60)
        trim_per_batch = args.trim_per_batch or (duration_minutes > 60)

        result = build_output(
            candidates,
            window,
            out_path,
            Path(args.tmpdir) if args.tmpdir else None,
            args.batch_size,
            args.out_format,
            args.display_filter,
            args.gzip,
            progress=None,
            verbose=args.verbose,
            trim_per_batch=trim_per_batch,
        )
        print(f"Done. Wrote: {result}")
        if cache:
            cache.close()
        sys.exit(ExitCodes.OK)

    except PCAPPullerError as e:
        logging.error(str(e))
        sys.exit(ExitCodes.OSERR if "OS error" in str(e) else ExitCodes.TOOL)
    except Exception:
        logging.exception("Unexpected error")
        sys.exit(1)
    finally:
        try:
            if 'cache' in locals() and cache:
                cache.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
