# PCAPpuller 👊
## A fast PCAP window selector, merger, and trimmer ⏩ (tshark wrapper)
> A small Python utility for high-volume packet collections. Point it at a given directory, give it a start time and duration (same day, up to 60 minutes), and it will:
- Find candidate files quickly (by filesystem mtime),
- optionally refine them precisely (via capinfos first/last packet times, in parallel),
- merge in batches with `mergecap`,
- trim exactly to the time window with `editcap -A/-B`,
- optionally apply a Wireshark display filter with `tshark`,
- write the result as pcap or pcapng, and optionally gzip the final file,
- show progress bars throughout,
- and provide a dry-run mode to preview the selection.
___
#### Built for speed and scale: low memory, batch merges, parallel metadata scans, and a `--tmpdir` so your `/tmp` doesn’t blow up.
___
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
___
> **Debian/Ubuntu**
> `sudo apt-get update`
> `sudo apt-get install -y wireshark-cli`
> `python3 -m pip install --upgrade tqdm`
#
> **Manjaro/Arch**
> `sudo pacman -Syu --needed wireshark-cli`
> `python3 -m pip install --upgrade tqdm`
# 
> **Fedora/CentOS/RHEL**
> `sudo dnf install -y wireshark-cli`
> `python3 -m pip install --upgrade tqdm`
#
> **macOS (Homebrew)**
> `brew install wireshark`
> `python3 -m pip install --upgrade tqdm`
#
> **Windows (PowerShell, Admin)**
> `winget install WiresharkFoundation.Wireshark`
> `py -m pip install --upgrade tqdm`<br>
> *add wireshark install dir (e.g. C:\Program Files\Wireshark) to PATH if needed
____
## Quick Usage ⭐
### Basic (required args only)
`python3 PCAPpuller.py --root /mnt/your-rootdir --start "YYYY-MM-DD HH:MM:SS" --minutes <1-60> --out /path/to/output.pcapng`
### Advanced (precise filter, auto worker, wireshark (dns) filter, gzip, etc)
`python3 PCAPpuller.py --root /mnt/your-rootdir --start "YYYY-MM-DD HH:MM:SS" --minutes <1-60> --out /path/to/output_dns.pcap.gz --out-format pcap --tmpdir /big/volume/tmp --batch-size 500 --slop-min 120 --precise-filter --workers auto --display-filter "dns" --gzip`
### Dry-run (no merge/trim) + write list
`python3 PCAPpuller.py --root /mnt/your-rootdir --start "YYYY-MM-DD HH:MM:SS" --minutes <1-60> --precise-filter --workers auto --dry-run --list-out /path/to/list.csv`
___
## Arguments 💥
### Required ❗
> `--root </root/directory>` — top-level directory to search.<br>
> `--start "YYYY-MM-DD HH:MM:SS"` — window start (local time).<br>
> `--minutes <1–60>` — duration; must stay within a single calendar day.<br>
> `--out </output/path>` — output file (not required if you use --dry-run).<br>
### Optional ❓
> `--tmpdir </temp/path>` — where to write temporary/intermediate files. **highly recommended** on a large volume (e.g., the NAS).<br>
> `--batch-size <INT>` — files per merge batch (default: 500).<br>
> `--slop-min <INT>` — mtime prefilter slack minutes (default: 120).<br>
> `--precise-filter` — use capinfos first/last packet times to keep only overlapping files.<br>
> `--workers <auto|INT>` — concurrency for precise filter (default: auto ≈ 2×CPU, gently capped).<br>
> `--display-filter "<Wireshark filter>"` — post-trim filter via tshark (e.g., "dns", "tcp.port==443").<br>
> `--out-format {pcap|pcapng}` — final capture format (default: pcapng).<br>
> `--gzip` — gzip-compress the final output (writes .gz).<br>
> `--dry-run` — selection only; no merge/trim/write.<br>
> `--list-out <FILE.{txt|csv}>` — with `--dry-run`, write survivor list to file.<br>
> `--debug-capinfos <N>` — Print parsed first/last times for the first N files during precise filter.<br>
___
## Tips 🗯️ 
- Use --tmpdir on a large volume (e.g., the NAS) if your /tmp is small.
- --precise-filter reduces I/O by skipping irrelevant files; tune --workers to match NAS throughput.
- Display filters use Wireshark display syntax (not capture filters).
- For auditing, run --dry-run --list-out list.csv first.
___
## Troubleshooting 🚨
- Temp disk fills up
> Set --tmpdir to a bigger filesystem. Batch size can be reduced via --batch-size.
- “No candidate PCAP files found”
> Try a larger --slop-min, confirm the time window, or test without --precise-filter. Use --dry-run for quick iteration.
- Permissions with tshark/dumpcap
> On Linux, add your user to the wireshark group and re-login.
___
