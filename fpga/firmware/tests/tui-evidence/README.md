# BootROM auto-start / ANSI TUI qualification

Scope: host-native production C, independent modeled MMIO/terminal, actual Python
uploader ↔ C BootROM over local process pipes, and RV64 builds/link/layout audits.
This is **not** a board screenshot or a production-C-on-SoC execution claim.
`menu.png` in the external companion archive is the actual host-compiled C
renderer decoded by an independent 80x24 terminal interpreter; archived
`menu.ansi` is its raw output and `menu.txt` its cells. Generated screenshots and
raw logs are intentionally outside source Git; their paths/hashes remain in
`receipt.json`. The companion is `Valence-bootrom-tui-validation-formal-20261009.tar.gz`.

## Implemented

- UART/TFTP success goes through one final metadata/range/physical-RAM verification
  helper, including initial legacy network boot. Launch consumes validity.
- A new attempt invalidates the old image before peripheral preflight. Busy,
  timeout, abort, record/range failure and CRC mismatch cannot reuse it.
- JTAG retains OPEN → host COMMIT → independent RAM CRC → epoch-bound CLAIM →
  existing assembly `run_image`. No UI output was inserted after the final
  session check and before CLAIM.
- Removed standalone Run Image and g/r/4 dispatch. Trusted embedded diagnostics
  return to the menu; an external return retains the existing reset-only lock.
- ASCII borders, color or monochrome selection, arrows/Enter/Esc, original
  shortcuts, plain fallback, status/result panel and actual RAM-check progress.
  Full action output is preserved in ordinary scrollback before repaint.
- Fragmented CSI/SS3, overlong/malformed CSI and OSC/DCS are handled without
  exposing their payload as shortcuts. Ctrl-C recovers unterminated control
  strings. CRLF selection cannot prefix the VLD1 header with LF.
- No TUI bytes are emitted during binary UART; no new network packet-loop output.
  RAM progress emits at most once per second plus its final completion line.
- New uploader sees AUTOBOOT and never sends g. Its legacy --run behavior remains
  available only after recognized old readiness. Selecting UART before opening
  the host tool is supported: its redundant d gets a fresh VLOAD banner.

## Passed

- 182 JTAG cases across four menu/network profiles, ASan/UBSan
- 43 menu, auto-start, stale-image, escape, CRLF and binary-isolation cases
- 27 recovery cases, including RAM corruption at six offsets and initial TFTP
- 2 pending-command cases; queued g cannot launch
- 25 Python uploader cases plus 2 bidirectional real-C/production-host pipe cases
- 80x24 independent terminal model, ASCII border and selection, zero offscreen writes
- Existing CoreMark CRC, 11 fake-MMIO diagnostics and memory-profile/cache models
- TFTP: 34 protocol, 99 window, 32 MMIO, 22 posted-RX, 4162 store-alignment cases;
  10 capacity profiles; 8 real Python/C sender/receiver interop cases, no sockets
- RV64 compile/link and machine-code UART contract (DLL=1, FCR=7)

Full menu + JTAG + posted TFTP + byte CRC ROM: 60,424 / 131,072 bytes.
Monitor globals: 6,848 bytes; the 8 KiB reserved stack remains intact.
Plain-start/nibble variant: 59,488 bytes. Legacy/JTAG/network variant: 25,780 bytes.
The user-requested short CoreMark action is removed; c/C/5 select only formal
CoreMark. Six timing/CRC gate tests reject <=10 seconds, bad/missing CRC or an
upstream error. The strict gate uses measured benchmark ticks, with no artificial
delay; provisional rates are suppressed. The unrelated short bandwidth selftest
and independent short native CoreMark kernel oracle remain. Linker RWX warnings concern the existing
bare-metal RAM diagnostic/sample LOAD segments, not a new OS permission change.

## Why old assertions changed

The former `n` test required download to stop without execution. It now requires
exactly one execution, consumed validity and AUTOBOOT. Busy-at-launch formerly
retained validity for a later g; it now requires invalidity, a rejected g and a
fresh successful download before launch. The old post-download/manual-run RAM
mutation test now mutates RAM after DOWNLOAD OK but before automatic final
verification, retaining the negative reread oracle. NO IMAGE responses tied to
retired g were replaced by explicit no-launch/invalid-state assertions. The
182 JTAG success/failure oracles were retained; only snapshot support was added.

## Reproduce

Use an existing C11 Clang with ASan/UBSan and the existing RV64 bare-metal GCC
14.2 toolchain. Pinned official CoreMark files must already be present; this
qualification did not install anything or fetch new software.

    python3 fpga/firmware/check_jtag_download.py --cc clang-19 --out OUT/jtag
    python3 fpga/firmware/check_boot_tui.py --binary OUT/jtag/menu-network --jtag --out OUT/preview
    python3 fpga/firmware/test_uart_tui_interop.py --cc clang-19
    python3 fpga/firmware/check_monitor.py --out OUT/monitor
    python3 fpga/firmware/check_netboot.py --out OUT/netboot
    python3 fpga/firmware/build.py --ddr --ddr-bytes 0x80000000 --boot-menu --jtag-download --netboot --netboot-posted-rx --crc-mode byte --cpu-hz 100000000 --uart-divisor 1 --uart-reference-hz 7372800 --uart-baud 460800 --out OUT/target
    python3 fpga/firmware/audit_uart_contract.py --rom OUT/target --reference-hz 7372800 --baud 460800 --out OUT/uart.json
    python3 fpga/firmware/audit_crc32.py --rom OUT/target

`receipt.json` binds the final source and copied evidence. Individual reports
retain their exact tested source hashes and explicit scope. Earlier JTAG default
firmware/export-equivalence records remain archived to their old checkpoint;
this automatic-start/TUI change intentionally changes every affected ROM binary.
The included 1a81f17 CPU smoke uses synthetic assembly and remains separate.

## Unverified boundary

Production C TUI/CRC on the selected real CPU/cache/DDR geometry, physical UART
and terminal behavior, real JTAG/OpenOCD/SMT2 and network PHY/CDC, Vivado resource
and routed timing, bitstream and board execution remain unverified. No bitstream
was generated, no board was accessed, and nothing was pushed. The frozen Vivado
candidate was not modified. Terminals smaller than 80x24 should use plain mode.
