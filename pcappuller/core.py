from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple, Dict

import datetime as dt

from .errors import PCAPPullerError
from .tools import (
    capinfos_epoch_bounds,
    gzip_file,
    merge_batch,
    run_editcap_trim,
    run_tshark_filter,
    which_or_error,
)
from .cache import CapinfosCache

ProgressFn = Callable[[str, int, int], None]  # phase, current, total

PCAP_EXTS = {".pcap", ".pcapng", ".cap"}


def parse_workers(value: str | int, total_files: int) -> int:
    """
    'auto'  -> ~2x CPU cores (min 4, max 32), gently capped for very large sets.
    integer -> parsed as provided, min 1, max 64.
    """
    if isinstance(value, int):
        w = value
    else:
        v = str(value).strip().lower()
        if v == "auto":
            cpu = os.cpu_count() or 4
            w = max(4, cpu * 2)
            if total_files >= 2000:
                w = min(w, 16)
            else:
                w = min(w, 32)
        else:
            try:
                w = int(v)
            except ValueError:
                raise PCAPPullerError(f"Invalid --workers value: {value}. Use 'auto' or an integer.")
    return max(1, min(w, 64))


@dataclass(frozen=True)
class Window:
    start: dt.datetime
    end: dt.datetime


def candidate_files(roots: Sequence[Path], window: Window, slop_min: int) -> List[Path]:
    lower = window.start - dt.timedelta(minutes=slop_min)
    upper = window.end + dt.timedelta(minutes=slop_min)
    lower_ts = lower.timestamp()
    upper_ts = upper.timestamp()

    files: List[Path] = []
    for root in roots:
        if not root.is_dir():
            raise PCAPPullerError(f"--root '{root}' is not a directory")
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


def precise_filter_parallel(
    files: Sequence[Path],
    window: Window,
    workers: int,
    debug_n: int = 0,
    progress: Optional[ProgressFn] = None,
    cache: Optional[CapinfosCache] = None,
) -> List[Path]:
    if not files:
        return []
    start_ts = window.start.timestamp()
    end_ts = window.end.timestamp()

    kept: List[Path] = []
    shown = 0
    total = len(files)
    def _get_bounds(p: Path):
        if cache:
            cached = cache.get(p)
            if cached is not None:
                return cached
        vals = capinfos_epoch_bounds(p)
        if cache:
            cache.set(p, vals[0], vals[1])
        return vals

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futmap = {ex.submit(_get_bounds, f): f for f in files}
        done_count = 0
        for fut in as_completed(futmap):
            f = futmap[fut]
            try:
                f_epoch, l_epoch = fut.result()
            except Exception as e:
                logging.debug("capinfos failed for %s: %s", f, e)
                f_epoch = l_epoch = None
            if f_epoch is None or l_epoch is None:
                if debug_n and shown < debug_n:
                    logging.debug("[DEBUG] %s: could not parse capinfos times", f.name)
                    shown += 1
            else:
                if debug_n and shown < debug_n:
                    first_utc = dt.datetime.fromtimestamp(f_epoch, dt.timezone.utc)
                    last_utc = dt.datetime.fromtimestamp(l_epoch, dt.timezone.utc)
                    logging.debug(
                        "[DEBUG] %s: first=%sZ last=%sZ",
                        f.name,
                        first_utc.strftime("%Y-%m-%d %H:%M:%S.%f"),
                        last_utc.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    )
                    shown += 1
                if not (l_epoch < start_ts or f_epoch > end_ts):
                    kept.append(f)
            done_count += 1
            if progress:
                progress("precise", done_count, total)
    return kept


def ensure_tools(display_filter: Optional[str], precise_filter: bool) -> None:
    which_or_error("mergecap")
    which_or_error("editcap")
    if precise_filter:
        which_or_error("capinfos")
    if display_filter:
        which_or_error("tshark")


def build_output(
    candidates: Sequence[Path],
    window: Window,
    out_path: Path,
    tmpdir_parent: Optional[Path],
    batch_size: int,
    out_format: str,
    display_filter: Optional[str],
    gzip_out: bool,
    progress: Optional[ProgressFn] = None,
    verbose: bool = False,
) -> Path:
    if not candidates:
        raise PCAPPullerError("No target PCAP files found after filtering.")

    candidates = sorted(candidates)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(dir=str(tmpdir_parent) if tmpdir_parent else None) as tmpdir:
            tmpdir_path = Path(tmpdir)
            intermediate_files: List[Path] = []

            # Merge in batches
            bs = max(1, batch_size)
            batches = [list(candidates)[i : i + bs] for i in range(0, len(candidates), bs)]
            if progress:
                progress("merge-batches", 0, len(batches))
            for i, batch in enumerate(batches, 1):
                interm = tmpdir_path / f"batch_{i:05d}.pcapng"
                merge_batch(batch, interm, verbose=verbose)
                intermediate_files.append(interm)
                if progress:
                    progress("merge-batches", i, len(batches))

            # Combine to one file
            if len(intermediate_files) == 1:
                merged_all = intermediate_files[0]
            else:
                merged_all = tmpdir_path / "merged_all.pcapng"
                merge_batch(intermediate_files, merged_all, verbose=verbose)

            # Trim to time window in desired format
            trimmed = tmpdir_path / f"trimmed.{out_format}"
            run_editcap_trim(merged_all, trimmed, window.start, window.end, out_format, verbose=verbose)
            if progress:
                progress("trim", 1, 1)

            # Optional display filter via tshark
            final_uncompressed = tmpdir_path / f"final.{out_format}"
            if display_filter:
                run_tshark_filter(trimmed, final_uncompressed, display_filter, out_format, verbose=verbose)
                if progress:
                    progress("display-filter", 1, 1)
            else:
                shutil.copy2(trimmed, final_uncompressed)

            # Optional gzip compression
            if gzip_out:
                final_gz = out_path if str(out_path).endswith(".gz") else out_path.with_suffix(out_path.suffix + ".gz")
                gzip_file(final_uncompressed, final_gz)
                if progress:
                    progress("gzip", 1, 1)
                return final_gz
            else:
                shutil.copy2(final_uncompressed, out_path)
                return out_path
    except OSError as oe:
        hint = " Provide a larger temp location with --tmpdir /path/on/big/volume" if tmpdir_parent is None else ""
        raise PCAPPullerError(f"OS error while handling temporary files: {oe}.{hint}")
    except subprocess.CalledProcessError as cpe:
        raise PCAPPullerError(f"External tool error: {cpe}")


def summarize_first_last(files: Sequence[Path], workers: int, cache: Optional[CapinfosCache] = None) -> Optional[Tuple[float, float]]:
    """Return (min_first_epoch, max_last_epoch) across files using capinfos in parallel.
    Returns None if no readable times.
    """
    if not files:
        return None
    which_or_error("capinfos")
    firsts: List[float] = []
    lasts: List[float] = []
    def _get_bounds(p: Path):
        if cache:
            hit = cache.get(p)
            if hit is not None:
                return hit
        vals = capinfos_epoch_bounds(p)
        if cache:
            cache.set(p, vals[0], vals[1])
        return vals

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_get_bounds, f) for f in files]
        for fut in as_completed(futs):
            f_epoch, l_epoch = fut.result()
            if f_epoch is not None and l_epoch is not None:
                firsts.append(f_epoch)
                lasts.append(l_epoch)
    if not firsts or not lasts:
        return None
    return (min(firsts), max(lasts))


def collect_file_metadata(files: Sequence[Path], workers: int, cache: Optional[CapinfosCache] = None) -> List[Dict[str, object]]:
    """Collect per-file metadata including size, mtime, and first/last epochs.
    Returns a list of dicts with keys: path, size, mtime, first, last.
    """
    results: List[Dict[str, object]] = []
    if not files:
        return results

    def _get_one(p: Path):
        try:
            st = p.stat()
            size = st.st_size
            mtime = st.st_mtime
        except OSError:
            return None
        # Get or compute times
        if cache:
            hit = cache.get(p)
            if hit is not None:
                first, last = hit
            else:
                first, last = capinfos_epoch_bounds(p)
                cache.set(p, first, last)
        else:
            first, last = capinfos_epoch_bounds(p)
        return {
            "path": p,
            "size": size,
            "mtime": mtime,
            "first": first,
            "last": last,
        }

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_get_one, f) for f in files]
        for fut in as_completed(futs):
            rec = fut.result()
            if rec is not None:
                results.append(rec)
    # stable order by path
    results.sort(key=lambda r: str(r["path"]))
    return results
