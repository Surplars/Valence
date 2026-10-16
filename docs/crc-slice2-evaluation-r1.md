# Optional slice2 CRC evaluation

Slice2 fits the unchanged full-feature BootROM globals reservation with 320 B headroom. Default modes remain unchanged. Mode3 appends to the existing mode0/1/2 numbering.

## Full firmware layout

| Mode | Globals / 8192 B | RAM table | ROM binary |
|---|---:|---:|---:|
| byte | 6848 | 1024 | 67480 |
| slice2 | 7872 | 2048 | 68616 |
| slice4 | 9920 (FAIL +1728) | 4096 | no successful image |

All reserve the original8192 B stack. Static fit does not establish worst-case stack usage. Slice4 failed map/log remain in ../crc-full-bootrom-layout-r1. Full slice2 audit passes one shared 2048 B table at0xffff8000, LMA0x800103f8, initialized by unchanged startup copy. No memory region or runtime feature removed.

## Target-cycle results

Each row is1024 bytes; ticks therefore equal cycles/KiB. GCC14.2 -Os; same fixed DDR latency32/credits8/gap1 and unchanged38 DUT objects. Byte was not rerun: candidate mode1 build reproduces sealed byte binary SHA exactly. UART adaptation outside timing is identical to the prior approved fixture. This is not complete BootROM target execution, GCC13.2 qualification, or a real74.8MB download estimate.

| Align | Warm | Byte stream | Slice2 stream | Byte RAM | Slice2 RAM | Slice2 stream/RAM cache misses |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 0 | 14846 | 11299 | 14903 | 11363 | 48/48 |
| 1 | 0 | 14890 | 11231 | 14946 | 11293 | 49/49 |
| 2 | 0 | 14893 | 11272 | 14948 | 11335 | 49/49 |
| 3 | 0 | 14892 | 11271 | 14949 | 11334 | 49/49 |
| 4 | 0 | 14851 | 11230 | 14909 | 11293 | 49/49 |
| 5 | 0 | 14852 | 11231 | 14907 | 11293 | 49/49 |
| 6 | 0 | 14892 | 11231 | 14949 | 11292 | 49/49 |
| 7 | 0 | 14893 | 11268 | 14948 | 11332 | 49/49 |
| 0 | 1 | 13331 | 9254 | 13349 | 9260 | 0/0 |
| 1 | 1 | 13331 | 9254 | 13337 | 9259 | 0/0 |
| 2 | 1 | 13331 | 9254 | 13337 | 9259 | 0/0 |
| 3 | 1 | 13331 | 9254 | 13337 | 9260 | 0/0 |
| 4 | 1 | 13331 | 9254 | 13337 | 9260 | 0/0 |
| 5 | 1 | 13331 | 9254 | 13337 | 9260 | 0/0 |
| 6 | 1 | 13331 | 9254 | 13337 | 9260 | 0/0 |
| 7 | 1 | 13331 | 9254 | 13337 | 9260 | 0/0 |

Cold cycle reduction range: 23.75–24.58%.

Warm cycle reduction range: 30.57–30.63%.

CRC function: byte64 B versus slice2 180 B. Function+table1088→2228 B; tiny test ROM2424→3568 B. Larger table adds1024 B full globals and1136 B full ROM. Cold means64KiB read-sweep pressure; warm does not guarantee all cache hits.

## Correctness and bounds

- Independent bitwise and zlib:323 cases, all8 alignments, short lengths and two full synthetic payload lengths; arbitrary raw seed also checked against zlib seeded convention. Existing nibble/byte/slice4 tests pass.
- ASan/UBSan:32784 cases, every length0..4097 ×8 alignments, random seed, split concatenation, unchanged canaries, poisoned tail. Wrong T1 table rejected by independent assertion; odd-length overread rejected by ASan use-after-poison.
- Guest bitwise checks, host bitwise/zlib CRC and all16 row geometry checks pass; complete RAM table readback equals ROM initializer.
- See bounds-runner.log, equivalence.log, existing-modes.log, negative-receipt.json and full-build.log.
- Commands: python3 fpga/firmware/test_crc32.py --mode slice2; python3 fpga/firmware/test_crc32_bounds.py. Full firmware argv/source hashes/compiler recorded in receipt.json. Host compilation and runtime argv in link-receipt.json and run-receipt.json.
- No DUT build, board operation, default switch, bitstream or Linux package change.


## Reproduction and instruction audit

The standalone cloud experiment directory is crc-slice2-evaluation-r1 (sibling of the worktree); it retains build_guest.py, prepare_fixture.py, link_host.py, summarize.py, command receipts and all full maps/disassembly. Portable correctness entrypoints are committed with the firmware. The archived result logs are in docs/validation/crc-slice2-r1. Published source base mapping is local77cd6dc / remote80d37a5, same tree0cb1acc; this candidate has a separate branch.

Full-feature link command (with the installed GCC14.2 cross toolchain on PATH):

    python3 fpga/firmware/build.py --out /path/to/output --crc-mode slice2 --boot-menu --netboot --netboot-posted-rx --jtag-download --ddr --ddr-bytes 0x80000000 --cpu-hz 100000000 --uart-reference-hz 7372800 --uart-baud 460800
    python3 fpga/firmware/audit_crc32.py --rom /path/to/output

Pin the six official CoreMark source files as required by the existing diagnostic builder. No stub diagnostic or relaxed assertions are permitted.

Manual full-image disassembly review confirms _start copies2064 B from0x800103f8 to[0xffff8000,0xffff8810) before BSS clearing and boot_main. CRC hot loop reads only lbu at offsets0/1 of the input, then two aligned lw table entries from T1 and T0; the tail uses one lbu and one T0 lw. No unaligned word input read. Full CRC function180 B. ROI marker cost is retained separately in raw logs; use guest time CSR ticks for comparisons.

Additional narrow netboot protocol execution with the actual slice2 CRC passed34 base,99 window, and current76,564,168 B payload cases under ASan/UBSan. This is not the entire check_netboot regression. Default build.py/test_crc32 mode remains nibble; check_netboot default remains byte; build_crc_bench defaults remain modes0/1 and now accepts explicit --modes 3. Slice4 retains numeric mode2; slice2 is appended as3.
