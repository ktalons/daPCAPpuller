class Pcappuller < Formula
  desc "PCAPpuller GUI: fast PCAP window selector, merger, trimmer"
  homepage "https://github.com/ktalons/daPCAPpuller"
  version "0.1.0" # <== update on release
  url "https://github.com/ktalons/daPCAPpuller/releases/download/v0.1.0/PCAPpullerGUI-macos"
  sha256 "REPLACE_WITH_SHA256"
  license "MIT"

  def install
    bin.install "PCAPpullerGUI-macos" => "pcappuller-gui"
  end

  def caveats
    <<~EOS
      This formula installs the PCAPpuller GUI binary.
      It requires Wireshark CLI tools (mergecap, editcap, tshark, capinfos) on PATH.

      On macOS, you may need to allow the app in System Settings > Privacy & Security (Gatekeeper).
    EOS
  end

  test do
    system "#{bin}/pcappuller-gui", "--help"
  end
end
