# PCAPpuller 👊 [![CI](https://github.com/ktalons/daPCAPpuller/actions/workflows/ci.yml/badge.svg)](https://github.com/ktalons/daPCAPpuller/actions/workflows/ci.yml) [![Release](https://github.com/ktalons/daPCAPpuller/actions/workflows/release.yml/badge.svg)](https://github.com/ktalons/daPCAPpuller/actions/workflows/release.yml)
## A fast PCAP window selector, merger, and trimmer ⏩ 
> A small Python utility for high-volume packet collections. Point it at one or more directories, give it a start time and duration (or end time), and it will:
- Find candidate files quickly (by filesystem mtime),
- optionally refine them precisely (via capinfos first/last packet times, in parallel),
- merge in batches with `mergecap`,
- trim exactly to the time window with `editcap -A/-B`,
- optionally apply a Wireshark display filter with `tshark`,
- write the result as pcap or pcapng, and optionally gzip the final file,
- show progress bars throughout,
- and provide a dry-run mode to preview the selection with optional summary.
___
#### Built for speed and scale: low memory, batch merges, parallel metadata scans, and a `--tmpdir` so your `/tmp` doesn’t blow up.
___
## What’s new ✨
- Refactored into a reusable core library (`pcappuller`) for stability and testability.
- Deterministic `capinfos` parsing and improved error handling.
- Flexible datetime parsing (`YYYY-MM-DD HH:MM:SS`, ISO-like, `Z`).
- `--end` as an alternative to `--minutes` (mutually exclusive).
- Multiple roots supported: `--root /dir1 /dir2 /dir3`.
- `--verbose` logging shows external tool commands/output.
- Dry-run `--summary` prints min/max packet times across survivors (UTC).
- Optional capinfos metadata cache (enabled by default) to speed up repeated runs.
- Optional GUI (`gui_pcappuller.py`) with folder pickers, checkboxes, and progress.

## Features  🧰
- 2️⃣ Two-phase selection
  - Fast prefilter by file mtime.
  - Optional precise filter using `capinfos -a -e -S` to keep only files whose packets overlap the target window.
- :electron: Parallel capinfos `--workers auto | N` for thousands of files.
- 🧩 Batch merges with mergecap to avoid huge argv/memory usage.
- ✂️ Exact time trim using `editcap -A/-B`.
- 🦈 Display filter `tshark -Y "<filter>"` after trimming (e.g. dns, tcp.port==443).
- 🏁 Output control: `--out-format pcap | pcapng` and optional `--gzip`.
- 🧪 Dry run to preview survivors and optional `--list-out .csv | .txt` to save the list.
- ✨ Robust temp handling `--tmpdir` and tqdm progress bars.
___
## How it works ⚙️
1. Scan --root for *.pcap, *.pcapng, *.cap whose mtime falls within [start-slop, end+slop].
2. (Optional) Refine with capinfos -a -e -S in parallel to keep only files that truly overlap the window.
3. Merge candidates in batches with mergecap (limits memory and argv size).
4. Trim the merged file to [start, end] with editcap -A/-B.
5. (Optional) Filter with tshark -Y "<display filter>".
6. Write as pcap/pcapng, optionally gzip.
___
## Prerequisites ☑️
- **Python 3.8+ and Wireshark CLI tools.**
- Install via packaging (recommended)
  - `python3 -m pip install -e .`  (from repo root)
  - Optional extras: `python3 -m pip install -e .[gui,datetime]`
- Or install packages manually:
  - `tqdm` (CLI progress)
  - `PySimpleGUI` (GUI; optional)
  - `python-dateutil` (optional for more datetime parsing)
___
> **Debian/Ubuntu**
> `sudo apt-get update`
> `sudo apt-get install wireshark`
> `python3 -m pip install --upgrade tqdm`
#
> **Manjaro/Arch**
> `sudo pacman -Syu wireshark`
> `python3 -m pip install --upgrade tqdm`
# 
> **Fedora/CentOS/RHEL**
> `sudo dnf install wireshark`
> `python3 -m pip install --upgrade tqdm`
#
> **macOS (Homebrew)**
> `brew install wireshark`
> `python3 -m pip install --upgrade tqdm`
#
> **Windows (PowerShell, Admin)**
> `winget install WiresharkFoundation.Wireshark`
> `py -m pip install --upgrade tqdm`<br>
> *If Wireshark tools aren’t in PATH, the app will also look in common install dirs.*
____
## Quick Usage ⭐
### Installed (via console scripts)
- `pcap-puller --root /mnt/dir --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --out out.pcapng`
- `pcap-puller --root /mnt/dir1 /mnt/dir2 --start "YYYY-MM-DD HH:MM:SS" --end "YYYY-MM-DD HH:MM:SS" --out out.pcapng`
- `pcap-puller --root /mnt/dir --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --precise-filter --workers auto --display-filter "dns" --gzip --verbose`
- Dry-run: `pcap-puller --root /mnt/dir --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --dry-run --list-out list.csv --summary`

### CLI quickstart
- Walkthrough gif:
  ![CLI Quickstart](docs/media/cli-quickstart.gif)

### Direct (without install)
`python3 PCAPpuller.py --root /mnt/your-rootdir --start "YYYY-MM-DD HH:MM:SS" --minutes <1-60> --out /path/to/output.pcapng`
`python3 PCAPpuller.py --root /mnt/dir1 /mnt/dir2 --start "YYYY-MM-DD HH:MM:SS" --end "YYYY-MM-DD HH:MM:SS" --out /path/to/output.pcapng`
`python3 PCAPpuller.py --root /mnt/your-rootdir --start "YYYY-MM-DD HH:MM:SS" --minutes <1-60> --out /path/to/output_dns.pcap.gz --out-format pcap --tmpdir /big/volume/tmp --batch-size 500 --slop-min 120 --precise-filter --workers auto --display-filter "dns" --gzip --verbose`
`python3 PCAPpuller.py --root /mnt/your-rootdir --start "YYYY-MM-DD HH:MM:SS" --minutes <1-60> --precise-filter --workers auto --dry-run --list-out /path/to/list.csv --summary`
___
## Arguments 💥
### Required ❗
> `--root </root/directory ...>` — one or more directories to search.<br>
> `--start "YYYY-MM-DD HH:MM:SS"` — window start (local time).<br>
> `--minutes <1–60>` — duration; must stay within a single calendar day. Or use `--end` with same-day end time.<br>
> `--out </output/path>` — output file (not required if you use --dry-run).<br>
### Optional ❓
> `--end <YYYY-MM-DD HH:MM:SS>` — end time instead of `--minutes` (must be same day as `--start`).<br>
> `--tmpdir </temp/path>` — where to write temporary/intermediate files. **Highly recommended** on a large volume (e.g., the NAS).<br>
> `--batch-size <INT>` — files per merge batch (default: 500).<br>
> `--slop-min <INT>` — mtime prefilter slack minutes (default: 120).<br>
> `--precise-filter` — use capinfos first/last packet times to keep only overlapping files.<br>
> `--workers <auto|INT>` — concurrency for precise filter (default: auto ≈ 2×CPU, gently capped).<br>
> `--display-filter "<Wireshark filter>"` — post-trim filter via tshark (e.g., "dns", "tcp.port==443").<br>
> `--out-format {pcap|pcapng}` — final capture format (default: pcapng).<br>
> `--gzip` — gzip-compress the final output (writes .gz).<br>
> `--dry-run` — selection only; no merge/trim/write.<br>
> `--list-out <FILE.{txt|csv}>` — with `--dry-run`, write survivor list to file.<br>
> `--report <FILE.csv>` — write a CSV report for survivors with path,size,mtime,first,last (uses cache/capinfos).<br>
> `--summary` — with `--dry-run`, print min/max packet times across survivors (UTC).
> `--verbose` — print debug logs and show external tool output.
___
## GUI (optional) 🖥️
Install:
- `python3 -m pip install -e .[gui]`
Run:
- `pcap-puller-gui`
Features:
- Folder pickers for Root and Tmpdir
- Start time and Minutes selector
- Checkboxes: Precise filter, Gzip, Dry-run, Verbose
- Display filter input (Wireshark syntax)
- Progress bar with Cancel support

### Single-file GUI build (PyInstaller)
- Install: `python3 -m pip install pyinstaller`
- Build (macOS/Windows/Linux):
  - `pyinstaller --onefile --windowed --name PCAPpullerGUI gui_pcappuller.py`
- Output:
  - macOS/Linux: `dist/PCAPpullerGUI`
  - Windows: `dist/PCAPpullerGUI.exe`
Notes:
- This bundles the Python app; Wireshark CLI tools must still be installed on the system PATH.
- On macOS, you may need to allow the binary in System Settings > Privacy & Security (Gatekeeper).
___
## Tips 🗯️ 
- Use --tmpdir on a large volume (e.g., the NAS) if your /tmp is small.
- --precise-filter reduces I/O by skipping irrelevant files; tune --workers to match NAS throughput.
- Metadata caching speeds up repeated runs. Default cache location:
  - macOS/Linux: ~/.cache/pcappuller/capinfos.sqlite (respects XDG_CACHE_HOME)
  - Windows: %LOCALAPPDATA%\pcappuller\capinfos.sqlite
  - Control with `--cache <PATH>`, disable with `--no-cache`, clear with `--clear-cache`.
- Display filters use Wireshark display syntax (not capture filters).
- For auditing, run --dry-run --list-out list.csv first; add `--summary` to see min/max packet times.

### Verify prerequisites quickly
- Run: `scripts/verify_wireshark_tools.sh`
- Checks presence of mergecap, editcap, capinfos, tshark and prints OS-specific install hints.
___
## Development 🛠️
- Install tooling (in a virtualenv):
  - python3 -m pip install -e .[gui,datetime]
  - python3 -m pip install pre-commit ruff mypy
- Enable pre-commit hooks:
  - pre-commit install
  - pre-commit run --all-files
- CI runs ruff (E,F) and mypy on pushes/PRs (see .github/workflows/ci.yml).

## Releases 🚀
- Auto-build GitHub Release with binaries for macOS/Linux/Windows:
  - Bump version in pyproject.toml
  - Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`
  - The release workflow (.github/workflows/release.yml) builds PyInstaller GUI binaries and attaches them to the GitHub Release.
- Manual release with gh (optional):
  - `gh release create vX.Y.Z --generate-notes --title "vX.Y.Z"`
  - Attach artifacts if needed.

## Packaging 📦
### Homebrew (macOS)
- Create tap repo (e.g., ktalons/homebrew-tap) and copy packaging/homebrew/Formula/pcappuller.rb
- Update formula to latest with: `packaging/homebrew/update_formula.sh latest`
- Tap and install: `brew tap ktalons/tap && brew install pcappuller`

### Linux (.deb, .rpm, .tar.zst)
- Requires fpm (gem install fpm) and a Linux-built binary (see Release workflow)
- Build packages: `packaging/linux/build_fpm.sh`
- Outputs written to packaging/artifacts/

## Troubleshooting 🚨
- Temp disk fills up
> Set --tmpdir to a bigger filesystem. Batch size can be reduced via --batch-size.
- “No candidate PCAP files found”
> Try a larger --slop-min, confirm the time window, or test without --precise-filter. Use --dry-run for quick iteration.
- Tools not found
> Ensure Wireshark CLI tools are installed and in PATH. On Windows, common install dirs are auto-checked.
- Permissions with tshark/dumpcap
> On Linux, add your user to the wireshark group and re-login.
___
