#!/usr/bin/env python3
"""
Name: pcapd.py
Date: 08/12/2025
By: Kyle Versluis (talons)

Core functionality:
- Select PCAP files by date/time and merge them into a single file.
- Supports both PCAP and PCAPNG formats.
- Handles files within a 1-day window, with a maximum duration of 60 minutes.
- Uses filesystem mtime for fast prefiltering, then trims precisely with editcap.
- batches merges via 'mergecap' to keep memory and argv size small.
- Requires Wireshark CLI tools: mergecap and editcap.
- Uses tqdm for progress bars.
- Python 3.8+ required.
- Compatible with Linux, macOS, and Windows (with Wireshark CLI tools installed).

Added highlights:
- Precise filter uses capinfos -u (UTC) and converts your window to UTC before comparison.
- Robust timestamp parsing (microseconds, Z/UTC, +/-HH:MM or +/-HHMM, trailing zone text).
- --dry-run to preview survivors; optionally --list-out FILE.{txt,csv}
- --workers auto (smart default) or explicit integer
- --display-filter "<Wireshark display filter>" via tshark after time trim
- --out-format pcap|pcapng and optional 
- --gzip to compress final output

Prereqs:
  - Wireshark CLI tools: mergecap, editcap
    * Ubuntu/Debian: sudo apt-get install -y wireshark-cli
    * RHEL/Fedora:   sudo dnf install -y wireshark-cli
    * Manjaro/Arch:  sudo pacman -Syu wireshark-cli
    * macOS:         brew install wireshark
    * Windows:       winget install WiresharkFoundation.Wireshark
  - Python package: tqdm  (pip install tqdm)
  
Required Basic Usage:
python3 pcapd.py \
  --root /path/to/root/pcap_directory \
  --start "YYYY-MM_DD HH:MM:SS" --minutes (1-60) \
  --out /path/to/output.pcapng \
  --tmpdir /path/to/temp_directory <optional> HOWEVER required if you have large sets of files

Optional Full Usage:
python3 pcapd.py \
  --root /path/to/root/pcap_directory \
  --start "YYYY-MM_DD HH:MM:SS" --minutes (1-60) \
  --out /path/to/output.pcapng \
  --tmpdir /path/to/temp_directory <optional> HOWEVER required if you have large sets of files \
  --batch-size 500 <optional> (default: 500) \
  --slop-min 120 <optional> (default: 120) \
  --precise-filter <optional> (default: False) \
  --workers auto <optional> (default: auto) \
  --display-filter "<Wireshark display filter>" <optional> \
  --out-format pcapng <optional> (default: pcapng) \
  --gzip <optional> (default: False) \
  --dry-run <optional> (default: False)

Dry-Run Usage (no merge/trim):
python3 pcapd.py \
  --root /path/to/root/pcap_directory \
  --start "YYYY-MM_DD HH:MM:SS" --minutes (1-60) \
  --dry-run \
  --list-out /path/to/survivors.csv <optional> (csv or txt) \
  --tmpdir /path/to/temp_directory <optional> HOWEVER required if you have large sets of files
  --precise-filter <optional> (default: False)
  
"""

import argparse
import datetime as dt
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from tqdm import tqdm
except ImportError:
    print("tqdm not installed. Please run: python3 -m pip install tqdm", file=sys.stderr)
    sys.exit(1)

PCAP_EXTS = {".pcap", ".pcapng", ".cap"}

# ----------------- CLI -----------------

def which_or_die(name: str):
    p = shutil.which(name)
    if not p:
        print(f"ERROR: '{name}' not found in PATH. Please install Wireshark CLI tools.", file=sys.stderr)
        sys.exit(2)
    return p

def parse_workers(value: str, total_files: int) -> int:
    """
    'auto'  -> ~2x CPU cores (min 4, max 32), gently capped for very large sets.
    integer -> parsed as provided, min 1, max 64.
    """
    if isinstance(value, int):
        w = value
    else:
        v = value.strip().lower()
        if v == "auto":
            cpu = os.cpu_count() or 4
            w = max(4, cpu * 2)
            # gentle cap: avoid overwhelming NAS on giant sets
            if total_files >= 2000:
                w = min(w, 16)
            else:
                w = min(w, 32)
        else:
            try:
                w = int(v)
            except ValueError:
                print(f"Invalid --workers value: {value}. Use 'auto' or an integer.", file=sys.stderr)
                sys.exit(2)
    return max(1, min(w, 64))

def parse_args():
    ap = argparse.ArgumentParser(
        description="Select PCAPs by date/time and merge into a single file (<=60 minutes, single calendar day)."
    )
    ap.add_argument("--root", required=True, help="Root directory (searched recursively).")
    ap.add_argument("--start", required=True, help="Start datetime: 'YYYY-MM-DD HH:MM:SS' (local time).")
    ap.add_argument("--minutes", required=True, type=int, help="Duration in minutes (1-60).")
    ap.add_argument("--out", help="Output path (required unless --dry-run).")
    ap.add_argument("--batch-size", type=int, default=500, help="Files per merge batch (default: 500).")
    ap.add_argument("--slop-min", type=int, default=120, help="Extra minutes around window for mtime prefilter (default: 120).")
    ap.add_argument("--tmpdir", default=None, help="Directory for temporary files (defaults to system temp).")
    ap.add_argument("--precise-filter", action="store_true", help="Use capinfos to drop files without packets in window.")
    ap.add_argument("--workers", default="auto", help="Parallel workers for precise filter: 'auto' or an integer.")
    ap.add_argument("--display-filter", default=None, help="Wireshark display filter applied via tshark after trimming.")
    ap.add_argument("--out-format", choices=["pcap", "pcapng"], default="pcapng", help="Final capture format (default: pcapng).")
    ap.add_argument("--gzip", action="store_true", help="Compress final output to .gz (recommended to use .gz extension).")
    ap.add_argument("--dry-run", action="store_true", help="Preview survivors and exit (no merge/trim).")
    ap.add_argument("--list-out", default=None, help="If set with --dry-run, write survivors to FILE (.txt or .csv).")
    ap.add_argument("--debug-capinfos", type=int, default=0, help="Print parsed capinfos times for first N files.")
    args = ap.parse_args()
    if not args.dry_run and not args.out:
        ap.error("--out is required unless --dry-run is set.")
    return args

def parse_local(dt_str: str) -> dt.datetime:
    s = dt_str.strip().replace("T", " ")
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        print(f"Invalid datetime format: {dt_str}. Use 'YYYY-MM-DD HH:MM:SS'.", file=sys.stderr)
        sys.exit(3)

def validate_window(start: dt.datetime, minutes: int):
    if minutes < 1 or minutes > 60:
        print("ERROR: --minutes must be between 1 and 60.", file=sys.stderr); sys.exit(4)
    end = start + dt.timedelta(minutes=minutes)
    if start.date() != end.date():
        print("ERROR: Window crosses midnight. Choose a window fully within a single day.", file=sys.stderr); sys.exit(5)
    return end

# ----------------- scanning -----------------

def candidate_files(root: Path, start: dt.datetime, end: dt.datetime, slop_min: int):
    lower = start - dt.timedelta(minutes=slop_min)
    upper = end + dt.timedelta(minutes=slop_min)
    lower_ts = lower.timestamp()
    upper_ts = upper.timestamp()

    files = []
    for dirpath, _, filenames in os.walk(root, followlinks=False):
        for fn in filenames:
            if Path(fn).suffix.lower() in PCAP_EXTS:
                full = Path(dirpath) / fn
                try:
                    st = full.stat()
                except OSError:
                    continue
                if lower_ts <= st.st_mtime <= upper_ts:
                    files.append(full)
    return files

# ----------------- capinfos epoch (precise filter) -----------------

def _capinfos_epoch_bounds(path: Path):
    """
    Return (first_epoch, last_epoch) as floats using:
      capinfos -a -e -S <file>
    -a => earliest packet time
    -e => latest  packet time
    -S => print times as seconds since Unix epoch (UTC)
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"; env["LANG"] = "C"
    try:
        res = subprocess.run(
            ["capinfos", "-a", "-e", "-S", str(path)],
            capture_output=True, text=True, check=True, env=env
        )
    except subprocess.CalledProcessError:
        return (None, None)

    nums = []
    for s in re.findall(r"[-+]?\d+(?:\.\d+)?", res.stdout):
        try:
            x = float(s)
            # plausible epoch seconds: 1990-01-01 .. 2100-01-01
            if 631152000.0 <= x <= 4102444800.0:
                nums.append(x)
        except ValueError:
            pass

    if len(nums) < 2:
        return (None, None)

    return (min(nums), max(nums))

def precise_filter_parallel(files, start_local, end_local, workers: int, debug_n: int = 0):
    """
    Keep files whose packet time range overlaps the [start_local, end_local] window.
    Compare in epoch seconds (no timezone ambiguity).
    """
    if not files:
        return []

    start_ts = start_local.timestamp()
    end_ts   = end_local.timestamp()

    kept = []
    shown = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futmap = {ex.submit(_capinfos_epoch_bounds, f): f for f in files}
        for fut in tqdm(as_completed(futmap), total=len(futmap), desc="Precise filtering", unit="file"):
            f = futmap[fut]
            try:
                f_epoch, l_epoch = fut.result()
            except Exception:
                continue
            if f_epoch is None or l_epoch is None:
                if debug_n and shown < debug_n:
                    print(f"[DEBUG] {f.name}: could not parse capinfos times", file=sys.stderr)
                    shown += 1
                continue

            if debug_n and shown < debug_n:
                first_utc = dt.datetime.fromtimestamp(f_epoch, dt.timezone.utc)
                last_utc  = dt.datetime.fromtimestamp(l_epoch, dt.timezone.utc)
                print(f"[DEBUG] {f.name}: first={first_utc.strftime('%Y-%m-%d %H:%M:%S.%f')}Z "
                      f"last={last_utc.strftime('%Y-%m-%d %H:%M:%S.%f')}Z", file=sys.stderr)
                shown += 1

            if not (l_epoch < start_ts or f_epoch > end_ts):
                kept.append(f)

    return kept

# ----------------- merging & post-processing -----------------

def merge_batch(inputs, out_path):
    cmd = ["mergecap", "-w", str(out_path)]
    cmd.extend([str(p) for p in inputs])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

def run_editcap_trim(src, dst, start_dt, end_dt, out_format: str):
    # out_format: 'pcap' or 'pcapng'
    fmt_flag = ["-F", out_format] if out_format else []
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str   = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    subprocess.run(
        ["editcap", "-A", start_str, "-B", end_str, *fmt_flag, str(src), str(dst)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )

def run_tshark_filter(src, dst, display_filter: str, out_format: str):
    fmt_flag = ["-F", out_format] if out_format else []
    subprocess.run(
        ["tshark", "-r", str(src), "-Y", display_filter, "-w", str(dst), *fmt_flag],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )

def gzip_file(src: Path, dst: Path):
    # Stream-compress to avoid spiking memory
    with open(src, "rb") as fin, gzip.open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout)

def write_list(paths, list_out: Path):
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

# ----------------- main -----------------

def main():
    
    args = parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: --root '{root}' is not a directory.", file=sys.stderr); sys.exit(6)

    which_or_die("mergecap")
    which_or_die("editcap")
    if args.precise_filter:
        which_or_die("capinfos")
    if args.display_filter:
        which_or_die("tshark")

    start = parse_local(args.start)
    end   = validate_window(start, args.minutes)

    # 1) Fast mtime prefilter
    pre_candidates = candidate_files(root, start, end, args.slop_min)

    # 2) Optional precise filter (parallel)
    workers = parse_workers(args.workers, total_files=len(pre_candidates))
    candidates = (precise_filter_parallel(pre_candidates, start, end, workers, args.debug_capinfos)
                  if args.precise_filter and pre_candidates else pre_candidates)

    if args.dry_run:
        print(f"Dry run:")
        print(f"  Found by mtime prefilter: {len(pre_candidates)}")
        if args.precise_filter:
            print(f"  Survived precise filter: {len(candidates)}")
        else:
            print(f"  Survivors (mtime-only):  {len(candidates)}")
        if args.list_out:
            write_list(candidates, Path(args.list_out))
            print(f"  Wrote list to: {args.list_out}")
        sys.exit(0)

    if not candidates:
        print("No target PCAP files found after filtering.", file=sys.stderr)
        sys.exit(0)

    candidates.sort()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmpdir_parent = args.tmpdir if args.tmpdir else None

    try:
        with tempfile.TemporaryDirectory(dir=tmpdir_parent) as tmpdir:
            tmpdir = Path(tmpdir)
            intermediate_files = []

            # Merge in batches
            bs = max(1, args.batch_size)
            batches = [candidates[i:i + bs] for i in range(0, len(candidates), bs)]
            for i, batch in enumerate(tqdm(batches, desc="Merging batches", unit="batch")):
                interm = tmpdir / f"batch_{i:05d}.pcapng"
                merge_batch(batch, interm)
                intermediate_files.append(interm)

            # Combine to one file
            if len(intermediate_files) == 1:
                merged_all = intermediate_files[0]
            else:
                merged_all = tmpdir / "merged_all.pcapng"
                merge_batch(intermediate_files, merged_all)

            # Trim to time window in desired format
            trimmed = tmpdir / f"trimmed.{args.out_format}"
            for _ in tqdm(range(1), desc="Trimming to window", unit="step"):
                run_editcap_trim(merged_all, trimmed, start, end, args.out_format)

            # Optional display filter via tshark
            final_uncompressed = tmpdir / f"final.{args.out_format}"
            if args.display_filter:
                for _ in tqdm(range(1), desc="Applying display filter", unit="step"):
                    run_tshark_filter(trimmed, final_uncompressed, args.display_filter, args.out_format)
            else:
                # no additional filtering; just move trimmed to final_uncompressed
                shutil.copy2(trimmed, final_uncompressed)

            # Optional gzip compression
            if args.gzip:
                final_gz = out_path if out_path.suffix.endswith(".gz") else out_path.with_suffix(out_path.suffix + ".gz")
                for _ in tqdm(range(1), desc="Compressing (gzip)", unit="step"):
                    gzip_file(final_uncompressed, final_gz)
                print(f"Done. Wrote: {final_gz}")
            else:
                shutil.copy2(final_uncompressed, out_path)
                print(f"Done. Wrote: {out_path}")

    except OSError as oe:
        print(f"OS error while handling temporary files: {oe}", file=sys.stderr)
        if args.tmpdir is None:
            print("Tip: Provide a larger temp location with --tmpdir /path/on/big/volume", file=sys.stderr)
        sys.exit(10)
    except subprocess.CalledProcessError as cpe:
        print(f"External tool error: {cpe}", file=sys.stderr)
        sys.exit(11)

if __name__ == "__main__":
    main()
