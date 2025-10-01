Place your application icon PNG here, named exactly:

  pcappuller.png

Recommendations:
- Size: 512x512 (square), RGBA
- Will be downscaled to 256x256 (Linux icon theme), .ico (Windows), and .icns (macOS) by CI/build scripts.

This icon will be embedded/installed in:
- Linux: hicolor theme at /usr/share/icons/hicolor/*/apps/pcappuller.png and referenced by the desktop entry (Icon=pcappuller)
- Windows: PyInstaller --icon artifacts/icons/pcappuller.ico
- macOS: PyInstaller --icon artifacts/icons/pcappuller.icns