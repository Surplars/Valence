#!/usr/bin/env python3
"""Independent CRC equivalence tests. Host correctness only, not CPU timing."""
import argparse
import ctypes
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib

SOURCE = Path(__file__).resolve().parent
ORACLE = r'''
#include <stdint.h>
uint32_t legacy(uint32_t c,const uint8_t *p,unsigned n) {
    while(n--) { c^=*p++; for(unsigned i=0;i<8;++i) c=(c>>1)^(0xedb88320U&(0U-(c&1))); }
    return c;
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--mode",choices=("nibble","byte","slice4"),default="nibble");args=ap.parse_args()
    rng = random.Random(0x43524332)
    cases = 0
    with tempfile.TemporaryDirectory(prefix="valence-crc-") as temp:
        root = Path(temp)
        (root / "oracle.c").write_text(ORACLE)
        subprocess.run([os.environ.get("CC", "cc"), "-O2", "-shared", "-fPIC", f"-DFIRMWARE_CRC_MODE={dict(nibble=0,byte=1,slice4=2)[args.mode]}",
                        str(SOURCE / "crc32.c"), str(root / "oracle.c"),
                        "-o", str(root / "crc.so")], check=True)
        lib = ctypes.CDLL(str(root / "crc.so"))
        for fn in (lib.firmware_crc_update, lib.legacy):
            fn.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint]
            fn.restype = ctypes.c_uint32
        def check(data, alignment):
            nonlocal cases
            buf = ctypes.create_string_buffer(b'!' * alignment + data)
            addr = ctypes.addressof(buf) + alignment
            raw = lib.firmware_crc_update(0xffffffff, addr, len(data))
            assert raw == lib.legacy(0xffffffff, addr, len(data))
            assert raw ^ 0xffffffff == zlib.crc32(data)
            c, offset = 0xffffffff, 0
            while offset < len(data):
                n = min(rng.randrange(1, 65537), len(data) - offset)
                c = lib.firmware_crc_update(c, addr + offset, n)
                offset += n
            assert c == raw
            # Arbitrary raw accumulator preserves chunk and unfinalized convention.
            seed = rng.getrandbits(32)
            assert lib.firmware_crc_update(seed, addr, len(data)) == lib.legacy(seed, addr, len(data))
            cases += 1
        check(b'123456789', 0)
        assert zlib.crc32(b'123456789') == 0xcbf43926
        lengths = sorted({0, 1, *(x + d for x in (4, 8, 64, 256, 512, 4096) for d in (-1, 0, 1))})
        for epoch in range(2):
            for alignment in range(8):
                for n in lengths:
                    check(rng.randbytes(n), alignment)
        # Actual payload LENGTH; deterministic synthetic bytes, not claimed image content.
        pattern = rng.randbytes(65536)
        for n in (66_348_740, 76_564_168):
            check((pattern * (n // len(pattern) + 1))[:n], 7)
    print(f'CRC32_EQUIVALENCE_PASS mode={args.mode} cases={cases} full_payload_length={n} wire_length={n+36} alignments=8 epochs=2 oracle=legacy_bitwise+python_zlib host_timing_claim=0')

if __name__ == '__main__':
    main()
