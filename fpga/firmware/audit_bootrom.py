#!/usr/bin/env python3
"""Reject stale BMG images: compare every generated MIF word to the expected binary."""
import argparse
import hashlib
import json
from pathlib import Path

ROM_BYTES = 128 * 1024


def audit(binary: Path, mif: Path, dcp: Path, profile="minimal"):
    data = binary.read_bytes()
    if not 0 < len(data) <= ROM_BYTES:
        raise ValueError("invalid BootROM binary size")
    if profile not in ("minimal", "menu"):
        raise ValueError("unknown BootROM profile")
    required = [b"Valence Bootrom V0.1\r\n\0"]
    if profile == "minimal":
        required.append(b"download mode (UART)\r\n\0")
    else:
        required += [b"monitor> \0", b"locked> \0",
                     b"EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n\0"]
    if any(token not in data for token in required):
        raise ValueError("expected " + profile + " Bootrom V0.1 identity/contract missing")
    if b"r:RAM" in data or b"CPU OK" in data:
        raise ValueError("retired ROM diagnostics detected")
    words = mif.read_text(encoding="ascii").splitlines()
    if len(words) != ROM_BYTES // 4 or any(len(w) != 32 or set(w) - set("01") for w in words):
        raise ValueError("expected 32768 binary MIF words")
    actual = b"".join(int(word, 2).to_bytes(4, "little") for word in words)
    if actual != data.ljust(ROM_BYTES, b"\0"):
        raise ValueError("BMG MIF differs from expected BootROM binary (including padding)")
    if not dcp.is_file() or dcp.stat().st_size == 0:
        raise ValueError("missing ROM IP checkpoint")
    if dcp.stat().st_mtime_ns < mif.stat().st_mtime_ns:
        raise ValueError("ROM DCP predates its MIF; regenerate output products")
    return {
        "profile": profile,
        "binary": str(binary.resolve()), "binaryBytes": len(data),
        "binarySha256": hashlib.sha256(data).hexdigest(),
        "mif": str(mif.resolve()), "mifWordsMatched": len(words),
        "romDcp": str(dcp.resolve()),
        "romDcpSha256": hashlib.sha256(dcp.read_bytes()).hexdigest(),
        "note": "MIF/binary identity and DCP provenance; release separately compares all ROM INIT/INITP properties.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--mif", type=Path, required=True)
    parser.add_argument("--dcp", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", choices=("minimal", "menu"), default="minimal")
    args = parser.parse_args()
    result = audit(args.bin, args.mif, args.dcp, args.profile)
    args.manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"BOOTROM_IMAGE: PASS {result['binaryBytes']} bytes, all 32768 MIF words matched; "
          f"SHA256={result['binarySha256']}")


if __name__ == "__main__":
    main()
