import gzip
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from .errors import PCAPPullerError


def which_or_error(name: str) -> str:
    """Return full path to tool or raise PCAPPullerError.
    On Windows, also try common Wireshark install dirs if not in PATH.
    """
    p = shutil.which(name)
    if p:
        return p
    # Windows heuristics
    if os.name == "nt":
        common_dirs = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\\Program Files"), "Wireshark"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)"), "Wireshark"),
        ]
        for d in common_dirs:
            candidate = str(Path(d) / f"{name}.exe")
            if Path(candidate).exists():
                return candidate
    raise PCAPPullerError(f"'{name}' not found in PATH. Please install Wireshark CLI tools.")


def merge_batch(inputs: Sequence[Path], out_path: Path, verbose: bool = False) -> None:
    cmd = ["mergecap", "-w", str(out_path), *[str(p) for p in inputs]]
    _run(cmd, verbose)


def run_editcap_trim(src: Path, dst: Path, start_dt, end_dt, out_format: str, verbose: bool = False) -> None:
    fmt_flag = ["-F", out_format] if out_format else []
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    cmd = ["editcap", "-A", start_str, "-B", end_str, *fmt_flag, str(src), str(dst)]
    _run(cmd, verbose)


def run_tshark_filter(src: Path, dst: Path, display_filter: str, out_format: str, verbose: bool = False) -> None:
    fmt_flag = ["-F", out_format] if out_format else []
    cmd = ["tshark", "-r", str(src), "-Y", display_filter, "-w", str(dst), *fmt_flag]
    _run(cmd, verbose)


def gzip_file(src: Path, dst: Path) -> None:
    with open(src, "rb") as fin, gzip.open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def capinfos_epoch_bounds(path: Path):
    """Return (first_epoch, last_epoch) using capinfos -a -e -S.
    Parse deterministically by lines. Handles both "Earliest/Latest" and "First/Last" labels.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    res = subprocess.run(["capinfos", "-a", "-e", "-S", str(path)], capture_output=True, text=True, env=env)
    if res.returncode != 0:
        return (None, None)
    first = last = None
    for line in res.stdout.splitlines():
        low = line.strip().lower()
        if low.startswith("first packet time:") or low.startswith("earliest packet time:"):
            try:
                first = float(line.split(":", 1)[1].strip())
            except Exception:
                first = None
        elif low.startswith("last packet time:") or low.startswith("latest packet time:"):
            try:
                last = float(line.split(":", 1)[1].strip())
            except Exception:
                last = None
    return (first, last)


def _run(cmd, verbose: bool = False) -> None:
    if verbose:
        logging.debug("RUN %s", " ".join(str(c) for c in cmd))
        subprocess.run(cmd, check=True)
    else:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
