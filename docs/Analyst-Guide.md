# PCAPpuller Analyst Guide

This short guide helps SOC analysts use PCAPpuller safely and efficiently.

1. Install prerequisites
- Wireshark CLI tools: mergecap, editcap, capinfos, tshark
- Python 3.8+, recommended 3.10+
- Optional GUI dependency: PySimpleGUI

Quick check:
- Run scripts/verify_wireshark_tools.sh

2. Quick starts
- CLI (basic):
  pcap-puller --root /data --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --out /tmp/out.pcapng
- CLI (precise + filter + gzip):
  pcap-puller --root /data --start "YYYY-MM-DD HH:MM:SS" --minutes 15 --precise-filter --workers auto --display-filter "dns" --gzip --out /tmp/out_dns.pcapng.gz
- GUI:
  pcap-puller-gui

3. Time windows and formats
- Use start+minutes or start+end (same calendar day)
- Accepts YYYY-MM-DD HH:MM:SS, ISO-like, with optional .%f and Z

4. Performance tips
- Use --tmpdir on a large volume (e.g., the NAS)
- Tune --workers with --precise-filter to match storage throughput
- Use --display-filter only after trimming to minimize I/O

5. Auditing & reporting
- Dry-run:
  pcap-puller ... --dry-run --list-out survivors.csv --summary
- CSV per-file report:
  pcap-puller ... --report report.csv

6. Common troubleshooting
- "No candidate files":
  - Increase --slop-min, confirm time window, try without --precise-filter
- Temp disk fills:
  - Reduce --batch-size, set --tmpdir to a larger filesystem
- Missing Wireshark tools:
  - Run scripts/verify_wireshark_tools.sh and follow OS hints

7. Security notes
- The tool copies and trims PCAPs; it does not modify originals
- Use --dry-run first to validate selection

8. Support & logs
- Add --verbose to print external tool commands
- Capture logs to a file for incident tickets

