from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .errors import PCAPPullerError
from .logging_setup import setup_logging
from .time_parse import parse_dt_flexible
from .tools import (
    which_or_error,
    try_convert_to_pcap,
    run_reordercap,
    run_editcap_snaplen,
    run_editcap_trim,
    run_tshark_filter,
)


class ExitCodes:
    OK = 0
    ARGS = 2
    OSERR = 10
    TOOL = 11


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Clean a capture to make it easier to open in Wireshark: optionally convert to pcap, "
            "reorder timestamps, truncate payloads (snaplen), optionally time-window, "
            "optionally apply a display filter, and optionally split into chunks."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--input", required=True, help="Input capture file (.pcap or .pcapng)")
    ap.add_argument(
        "--out-dir",
        default=None,
        help="Output directory (default: <input>_clean alongside the input)",
    )
    ap.add_argument(
        "--keep-format", action="store_true", help="Keep original format (do not convert to pcap)"
    )
    ap.add_argument(
        "--no-reorder",
        action="store_true",
        help="Do not reorder packets by timestamp (reordercap)",
    )
    ap.add_argument(
        "--snaplen",
        type=int,
        default=256,
        help="Truncate packets to this many bytes (set to 0 to disable)",
    )
    ap.add_argument(
        "--start",
        default=None,
        help="Optional start time for trimming (YYYY-MM-DD HH:MM:SS[.ffffff][Z])",
    )
    ap.add_argument(
        "--end",
        default=None,
        help="Optional end time for trimming (YYYY-MM-DD HH:MM:SS[.ffffff][Z])",
    )
    ap.add_argument(
        "--filter",
        default=None,
        help="Optional Wireshark display filter to apply via tshark after trimming/snaplen",
    )
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument(
        "--split-seconds",
        type=int,
        default=None,
        help="Split output into N-second chunks (editcap -i N)",
    )
    grp.add_argument(
        "--split-packets",
        type=int,
        default=None,
        help="Split output every N packets (editcap -c N)",
    )
    ap.add_argument("--verbose", action="store_true", help="Verbose logging and show tool output")
    return ap.parse_args()


def ensure_tools_for_clean(use_reorder: bool, use_filter: bool) -> None:
    which_or_error("editcap")
    if use_reorder:
        which_or_error("reordercap")
    if use_filter:
        which_or_error("tshark")


def _suffix_for(path: Path) -> str:
    return ".pcap" if path.suffix.lower() == ".pcap" else ".pcapng"


def clean_pipeline(
    input_path: Path,
    out_dir: Path,
    keep_format: bool,
    do_reorder: bool,
    snaplen: int,
    start_dt: Optional[dt.datetime],
    end_dt: Optional[dt.datetime],
    display_filter: Optional[str],
    split_seconds: Optional[int],
    split_packets: Optional[int],
    verbose: bool,
) -> List[Path]:
    # Preflight
    if not input_path.exists():
        raise PCAPPullerError(f"Input file not found: {input_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    ensure_tools_for_clean(do_reorder, bool(display_filter))

    # Working state
    base = input_path.stem
    # Track format by suffix of current
    current = input_path

    # 1) Convert to pcap if allowed and beneficial
    outputs: List[Path] = []
    suffix = _suffix_for(current)
    if not keep_format and suffix == ".pcapng":
        conv = out_dir / f"{base}.pcap"
        logging.info("Converting to pcap (dropping pcapng metadata): %s", conv)
        ok = try_convert_to_pcap(current, conv, verbose=verbose)
        if ok:
            current = conv
            suffix = ".pcap"
        else:
            logging.info("Keeping original format (likely multiple link-layer types)")

    # 2) Reorder by timestamp
    if do_reorder:
        sorted_out = out_dir / f"{base}.sorted{suffix}"
        logging.info("Reordering packets by timestamp: %s", sorted_out)
        run_reordercap(current, sorted_out, verbose=verbose)
        current = sorted_out

    # 3) Optional time trim
    if start_dt and end_dt:
        trimmed = out_dir / f"{base}.trim{suffix}"
        logging.info("Trimming time window: %s .. %s -> %s", start_dt, end_dt, trimmed)
        run_editcap_trim(current, trimmed, start_dt, end_dt, out_format=suffix.lstrip("."), verbose=verbose)
        current = trimmed
    elif (start_dt and not end_dt) or (end_dt and not start_dt):
        raise PCAPPullerError("Provide both --start and --end for time trimming, or neither.")

    # 4) Snaplen
    if snaplen and snaplen > 0:
        s_out = out_dir / f"{base}.s{snaplen}{suffix}"
        logging.info("Applying snaplen=%d -> %s", snaplen, s_out)
        run_editcap_snaplen(current, s_out, snaplen, out_format=suffix.lstrip("."), verbose=verbose)
        current = s_out

    # 5) Optional display filter
    if display_filter:
        f_out = out_dir / f"{base}.filt{suffix}"
        logging.info("Applying display filter '%s' -> %s", display_filter, f_out)
        run_tshark_filter(current, f_out, display_filter, out_format=suffix.lstrip("."), verbose=verbose)
        current = f_out

    # 6) Optional split
    if split_seconds or split_packets:
        # editcap naming convention creates numbered files based on the output basename
        chunk_base = out_dir / f"{base}.chunk{suffix}"
        cmd = ["editcap"]
        if split_seconds:
            cmd += ["-i", str(int(split_seconds))]
        if split_packets:
            cmd += ["-c", str(int(split_packets))]
        cmd += [str(current), str(chunk_base)]
        if verbose:
            logging.debug("RUN %s", " ".join(cmd))
            import subprocess as _sp

            _sp.run(cmd, check=True)
        else:
            import subprocess as _sp

            _sp.run(cmd, check=True, stdout=_sp.DEVNULL, stderr=_sp.STDOUT)
        # Collect produced chunks (editcap appends numeric parts to the given name)
        produced = sorted(out_dir.glob(f"{base}.chunk_*{suffix}"))
        if not produced:
            # Some editcap versions produce name like base.chunk_00001_... without suffix repetition
            produced = sorted(out_dir.glob(f"{base}.chunk_*"))
        outputs.extend(produced)
    else:
        outputs.append(current)

    return outputs


def main():
    args = parse_args()
    setup_logging(args.verbose)

    try:
        input_path = Path(args.input)
        out_dir = Path(args.out_dir) if args.out_dir else input_path.with_name(input_path.name + "_clean")

        start_dt = parse_dt_flexible(args.start) if args.start else None
        end_dt = parse_dt_flexible(args.end) if args.end else None

        outs = clean_pipeline(
            input_path=input_path,
            out_dir=out_dir,
            keep_format=args.keep_format,
            do_reorder=not args.no_reorder,
            snaplen=int(args.snaplen),
            start_dt=start_dt,
            end_dt=end_dt,
            display_filter=args.filter,
            split_seconds=args.split_seconds,
            split_packets=args.split_packets,
            verbose=args.verbose,
        )
        if len(outs) == 1:
            print(f"Done. Wrote: {outs[0]}")
        else:
            print("Done. Wrote chunks:")
            for p in outs:
                print(f"  {p}")
        sys.exit(ExitCodes.OK)
    except PCAPPullerError as e:
        logging.error(str(e))
        sys.exit(ExitCodes.TOOL)
    except OSError as oe:
        logging.error("OS error: %s", oe)
        sys.exit(ExitCodes.OSERR)
    except Exception:
        logging.exception("Unexpected error")
        sys.exit(1)


if __name__ == "__main__":
    main()
