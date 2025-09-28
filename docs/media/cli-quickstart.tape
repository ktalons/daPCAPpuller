Output docs/media/cli-quickstart.gif
Set Shell "bash"
Set Width 1000
Set Height 650
Set FontSize 16
Set Theme "Dracula"

Type "pcap-puller --help"
Enter
Sleep 2000

Type "pcap-puller --root /mnt/pcaps --start \"2025-08-20 13:50:00\" --minutes 15 --dry-run --summary"
Enter
Sleep 2500

Type "pcap-puller --root /mnt/pcaps --start \"2025-08-20 13:50:00\" --minutes 15 --precise-filter --workers auto --out /tmp/out.pcapng"
Enter
Sleep 2500