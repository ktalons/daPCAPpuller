# PCAPpuller 👊
## A fast PCAP window selector, merger, and trimmer ⏩

PCAPpuller helps you pull just the packets you need from large rolling PCAP collections.

---

## Install the GUI (recommended) 🖥️
The easiest way to use PCAPpuller is the desktop GUI. Download it from the latest release:
- https://github.com/ktalons/daPCAPpuller/releases/latest

Requirements for the GUI binary: Wireshark CLI tools (tshark, mergecap, editcap, capinfos) installed on your system PATH. See Install Wireshark CLI tools below if needed.

- macOS
  1) Download PCAPpullerGUI-macos from the latest release
  2) Optional: move it to /Applications
  3) First run: right-click → Open (or: xattr -d com.apple.quarantine /path/to/PCAPpullerGUI-macos)

- Windows
  1) Download PCAPpullerGUI-windows.exe from the latest release
  2) If SmartScreen warns, click “More info” → “Run anyway”

- Linux
  - Portable binary
    1) Download PCAPpullerGUI-linux
    2) chmod +x ./PCAPpullerGUI-linux && ./PCAPpullerGUI-linux
  - Packages
    - Debian/Ubuntu: sudo dpkg -i pcappuller-gui_*.deb && sudo apt -f install
    - Fedora/RHEL: sudo rpm -Uvh pcappuller-gui-*.rpm

### Run the GUI
- macOS/Linux: double-click or run from terminal: ./PCAPpullerGUI-macos or ./PCAPpullerGUI-linux
- Windows: double-click PCAPpullerGUI-windows.exe

### Quickstart (GUI)
1) Pick Root folder(s) containing your PCAP/PCAPNG files
2) Set Start time and Minutes (or use End time via Advanced if available)
3) Optional: Precise filter, Display filter (Wireshark syntax), Gzip
4) Choose an output file path
5) Click Run — progress will appear; cancel anytime

---

## What’s new ✨
- Refactored into a reusable core library (`pcappuller`) for stability and testability.
- Deterministic `capinfos` parsing and improved error handling.
- Flexible datetime parsing (`YYYY-MM-DD HH:MM:SS`, ISO-like, `Z`).
- `--end` as an alternative to `--minutes` (mutually exclusive).
- Multiple roots supported: `--root /dir1 /dir2 /dir3`.
- `--verbose` logging shows external tool commands/output.
- Dry-run `--summary` prints min/max packet times across survivors (UTC).
- Optional capinfos metadata cache (enabled by default) to speed up repeated runs.
- GUI with folder pickers, checkboxes, and progress.

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
- For the GUI binary: Wireshark CLI tools available on PATH (tshark, mergecap, editcap, capinfos). No Python required.
- For the CLI (pip install): Python 3.8+ and Wireshark CLI tools.
- **Note**: PySimpleGUI has moved to a private PyPI server. To install from source, use: `python3 -m pip install --extra-index-url https://PySimpleGUI.net/install PySimpleGUI`

### Install Wireshark CLI tools
> Debian/Ubuntu
> sudo apt-get update
> sudo apt-get install wireshark
#
> Manjaro/Arch
> sudo pacman -Syu wireshark
# 
> Fedora/CentOS/RHEL
> sudo dnf install wireshark
#
> macOS (Homebrew)
> brew install wireshark
#
> Windows (PowerShell, Admin)
> winget install WiresharkFoundation.Wireshark
> 
> If Wireshark CLI tools aren’t in PATH, the app will also look in common install dirs.
___
## Quick Usage ⭐
### Installed (via console scripts)
- `pcap-puller --root /mnt/dir --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --out out.pcapng`
- `pcap-puller --root /mnt/dir1 /mnt/dir2 --start "YYYY-MM-DD HH:MM:SS" --end "YYYY-MM-DD HH:MM:SS" --out out.pcapng`
- `pcap-puller --root /mnt/dir --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --precise-filter --workers auto --display-filter "dns" --gzip --verbose`
- Dry-run: `pcap-puller --root /mnt/dir --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --dry-run --list-out list.csv --summary --report survivors.csv`

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
## Tips 🗯️ 
- Use --tmpdir on a large volume (e.g., the NAS) if your /tmp is small.
- --precise-filter reduces I/O by skipping irrelevant files; tune --workers to match NAS throughput.
- Metadata caching speeds up repeated runs. Default cache location:
  - macOS/Linux: ~/.cache/pcappuller/capinfos.sqlite (respects XDG_CACHE_HOME)
  - Windows: %LOCALAPPDATA%\pcappuller\capinfos.sqlite
  - Control with `--cache <PATH>`, disable with `--no-cache`, clear with `--clear-cache`.
- Display filters use Wireshark display syntax (not capture filters).
- For auditing, run --dry-run --list-out list.csv first; add `--summary` to see min/max packet times.
___
## Development 🛠️
- Install tooling (in a virtualenv):
  - python3 -m pip install -e .[datetime]
  - python3 -m pip install --extra-index-url https://PySimpleGUI.net/install PySimpleGUI
  - python3 -m pip install pre-commit ruff mypy
- Enable pre-commit hooks:
  - pre-commit install
  - pre-commit run --all-files
- CI runs ruff (E,F) and mypy on pushes/PRs (see .github/workflows/ci.yml).

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
