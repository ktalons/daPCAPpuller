# PCAPd 👊
## ⏩ A fast PCAP window selector, merger, and trimmer ⏩
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
## Features
