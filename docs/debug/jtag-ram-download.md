# Boot-owned JTAG RAM download (experimental)

## Scope and compatibility

This candidate implements a boot-only RAM downloader, not an architectural RISC-V Debug Module. The existing CPU is never reported halted, and no halt/resume, abstract GPR/CSR access, triggers, single stepping or GDB support is implied. `dmstatus.version=0` and nonzero `dmcontrol` writes fail. A raw OpenOCD Tcl loader uses either the standard standalone JTAG DTM/DMI wire format or an optional custom FPGA BSCANE2 USER data register. Do not create a native OpenOCD `riscv` target or call `load_image` against this endpoint.

The [Debug specification](https://docs.riscv.org/reference/debug/v1.0/debug_module.html) requires genuine hart control/register support even for minimal conformance. The [OpenOCD RISC-V source](https://openocd.org/doc/doxygen/html/riscv-013_8c_source.html) `examine()` halts a running hart and examines registers before normal target use; selecting `sysbus` does not remove this dependency. The [raw scan commands](https://openocd.org/doc/html/JTAG-Commands.html) are the supported first-stage integration route.

Default hardware and firmware stay disabled. No board pin, USB driver, Vivado project, published branch or bitstream is changed by this candidate.

## Data path and ownership

`JtagRamLoader` is in the CPU/fabric clock domain, behind the existing bundled-data TCK mailbox. Its memory requests join the existing DMA register arbiter, then `DmaRegisterDataAdapter`, `AtomicDataMemory` and the coherent home. The source retains DMA identity, so owned CPU cache lines are probed. It is not an unqualified DDR-side bypass. Only naturally aligned 32-bit physical transfers are supported, one outstanding operation, no burst. Right-justified bytes are converted by the existing adapter, including addresses at the high word of a 64-bit beat.

The compile-time whitelist begins at `0x80200000`. Its end is `min(RAM_BASE + ramBytes - 0x4000, 0xffff8000) - 0x80000`, excluding the monitor stack/globals and the larger menu diagnostic reservation even for a non-menu ROM. It stays below 4 GiB and uses widened range arithmetic. The ROM independently checks that the advertised end does not exceed its own `RAM_BASE + IMAGE_LIMIT` before OPEN. ROM, arbitrary MMIO and the reserved monitor/diagnostic areas cannot be written through SBA.

Only the CPU's explicit MMIO OPEN arms downloads. The firmware enters this mode only after the user types `j`, while its existing memory/network DMA owners are quiet and cache preparation succeeds. Normal startup does not touch the optional endpoint. A returned or trapped external image cannot re-arm: the existing `external_state_untrusted` policy is preserved, and successful final CLAIM also locks the hardware until a coordinated fabric reset.

### Reset, errors and aborted requests

- DTM/BSCAN interface reset closes the session and cancels launch permission. It clears the pending DMI response, not the bus-owner state.
- A presented memory request remains stable until accepted. A request already accepted retains ownership until its actual response, including after abort, TAP reset and timeout.
- Timeout (default 1,000,000 fabric cycles) sets a sticky error/fault and closes the session. BUSY stays set while the old offer/response drains. Timeout does not undo a write, free the arbiter token or authorize replay.
- An indefinitely unresponsive bus remains blocked; only a coordinated system/fabric reset can recover it. Resetting only the downloader while an old downstream transaction survives is unsupported.
- A late response is consumed exactly once, does not resurrect the cancelled session, and cannot authorize launch. Bus error closes the session.
- CPU OPEN is rejected while BUSY, link-down or CLAIMED. After a drained failure a new explicit OPEN clears session state and advances generation. No automatic reopen or write retry occurs.
- Initialize OpenOCD first, then type `j`. TAP reset/TRST during an armed session cancels it. After a system reset reinitialize the host transport before entering a new session.

## Register contract

All DMI registers are 32 bits; unsupported addresses/opcodes fail. Custom identity is `0x564c0101` at `0x40`. The interface uses an SBA-compatible layout but does not claim a complete DM.

| DMI | Meaning |
|---|---|
| 0x10 / 0x11 | Absent DM control/status, both read zero; only zero dmcontrol write succeeds |
| 0x38 | SBCS: version1, address-size32, 32-bit access only |
| 0x39 / 0x3c | SBADDRESS0 / SBDATA0 |
| 0x40 | Custom capability/version |
| 0x41 | Session status |
| 0x42 | Host ABORT=1; COMMIT=2 |
| 0x43 / 0x44 / 0x45 | Entry, logical byte length, CRC-32/ISO-HDLC |
| 0x46 | Generation |
| 0x47 / 0x48 | Whitelist base / end-exclusive |
| 0x49 | Expected generation token, required for atomic COMMIT |

SBCS supports read-on-address, read-on-data and increment-on-success; reset access size is 32 bits. Both sticky error fields inhibit new transfers. `sberror` clears bitwise W1C. A busy address/data access sets `sbbusyerror` and never changes the pending transfer. SBCS writes during BUSY are deterministically ignored. Errors: timeout1, address2, alignment3, size4, other7. A DMI write acknowledgment means the register operation was accepted, not that its memory write completed; poll SBCS.

CPU MMIO at `0x10003000` accepts aligned 64-bit full-strobe accesses only:

| Offset | Meaning |
|---|---|
| +0 | Status: bit0 ARMED, bit1 COMMITTED, bit2 CANCELLED, bit3 BUSY, bit4 FAULT, bit5 LINK_UP, bit6 CLAIMED |
| +8 | CPU command: OPEN1, CLOSE2, CLAIM3; CLAIM requires generation in bits63:32 |
| +16 / +24 / +32 | Frozen entry / length / CRC |
| +40 / +48 / +56 | Generation / RAM base / end-exclusive |

COMMIT atomically checks the expected-generation token, nonzero logical length, rounded-up length in bounds, four-byte aligned entry inside the logical image, no pending bus operation and no SBA/session error. It seals data/metadata writes before the ROM checks the descriptor. Last-word zero padding is written/read back by the host; CRC covers only original file bytes.

The ROM independently verifies descriptor bounds, uses the existing cache preparation protocol and computes CRC, then performs an epoch-bound CPU CLAIM. A reset/abort before CLAIM invalidates it. Successful CLAIM is the explicit irreversible launch boundary; later ABORT cannot prevent the jump. The existing `run_image` issues memory and instruction fences. This SoC's `fence.i` includes private dirty writeback and home drain; the existing verification sweep covers clean-cache eviction. These are SoC-specific mechanisms, not a general claim that `fence.i` alone provides D-cache coherence.

Launch ABI is the existing bare-metal M-mode ABI: interrupts disabled, SATP zero, PMP configuration cleared, application stack selected, `a0=0`, `a1=0`. A flat binary must be linked for the advertised base and entry. This is not a Linux/OpenSBI DTB boot protocol, a relocatable ELF loader or a secure/authenticated boot mechanism.

## Build and use

See [firmware instructions](../../fpga/firmware/JTAG-DOWNLOAD.md), [BSCAN integration](bscan-user-transport.md), and the self-contained configuration files under `simulator/jtag/`.

- Standalone soft TAP candidate: `ooo.FpgaNextMain OUTPUT --experimental-jtag-ram`.
- Existing FPGA hard TAP candidate: `fpga/next/export.py --output OUTPUT --experimental-jtag-bscan N --emit`, with an explicitly reviewed USER chain. No default chain is allocated.
- This export derives a matching `board/soc_top_gmac_ddr.sv` from the unchanged current GMII wrapper, replacing only its SoC instance prefix and connecting debug POR to the existing whole-board reset. It adds no JTAG package pins and leaves media/PHY/clock wiring unchanged. Tri-speed remains a separate explicit export option with its own wrapper.
- The exporter compares the complete named-port set against the actual emitted top and fails on missing, unknown or duplicate connections. The required `board/require_jtag_chain.tcl` must run after synthesis (with the exact `VALENCE_JTAG_OWN_CELL`) before accepting implementation or a bitstream. It rejects BSCANE2/debug-hub collisions and unknown chain properties. Cloud Tcl mocks are not a substitute for that real Vivado gate.
- Firmware: `fpga/firmware/build.py --jtag-download` plus the matching existing memory/menu/network profile.
- Native simulator install, native transport tests, real OpenOCD/SMT2 connection, BSDL verification, CDC/RDC signoff and board programming are separate gates, not performed implicitly.

## Verification and performance boundaries

Run the focused checks with the already approved tool cache:

```
source /path/to/Valence/scripts/cloud/env.sh
export VALENCE_GSIM_SOURCE=/path/to/Valence/simulator/build/gsim-src
mill -i IonSoC.test.testOnly debug.JtagRamLoaderSpec debug.JtagDebugReservationSpec
python3 simulator/gsim/jtag_ram_loader.py
python3 fpga/firmware/check_jtag_download.py
tclsh simulator/jtag/ram-loader-test.tcl
tclsh simulator/jtag/ram-loader-bscan-test.tcl
python3 simulator/jtag/run.py
python3 simulator/jtag/bscan_run.py
```

The endpoint GSIM test uses one clock and an independent byte-array memory oracle. It does not validate the physical TCK crossing or booting the full CPU. Firmware host tests execute real C against adversarial MMIO models. Tcl tests emulate independent wire/register endpoints; they are not actual OpenOCD interoperability evidence. Native edge tests report BLOCKED if Icarus/vvp are absent, and install nothing.

Download throughput is bounded by TCK scan overhead, DMI round trips, per-word SBA polling, bus/DDR latency, host USB batching and full readback verification. The conservative implementation deliberately prioritizes recovery correctness; do not claim it is faster than Ethernet or quote model execution speed as hardware throughput. No measured SMT2/board download rate, FPGA area, Fmax or routed timing is available for this candidate.

### Recorded source-candidate evidence (2026-10-09)

- Focused Scala checks: 5 debug tests plus 10 preserved FPGA-next geometry/configuration tests.
- GSIM endpoint: 165 requests / 84 writes, independent readback-corruption negative detected; separate 64 low/high lane adapter cases with request/response stalls and error propagation. A subsequent focused CPU/cache smoke is recorded below; external DDR and the production C ROM are not covered by that smoke.
- Firmware: 182 downloader host-model cases and 46 existing menu/recovery cases, ASan/UBSan clean; matching RV64 link builds. Default minimal and full menu/network binaries unchanged.
- Host: 44 standalone DTM model tests, 15 USER model tests, 4 configuration checks; actual OpenOCD/Jim/SMT2 not run.
- BSCAN: 120 source/codec checks; native edge/UNISIM/CDC tests remain blocked and unrun.
- Default-off complete selected RTL: all 262 SystemVerilog files are byte-identical to a fresh export of frozen commit `9a149e1330c05c6909b774efa45ede8db7627d08`.
- Enabled BSCAN complete SoC source export and matching 64-port legacy board binding passed. Handwritten SV is carried as a blackbox resource; this is not SV behavioral or physical timing validation.
- Chain-guard Tcl: 11 mock allocation/error cases; real post-synthesis chain gate not run.

See `docs/debug/evidence/ram-download/`, `simulator/jtag/evidence/`, and firmware evidence for exact source hashes and limitations. The deliberately injected corrupt-readback run failed as expected; early stale compiler-snapshot runs were discarded and the final tested source is hash-bound.

### Subsequent real-CPU/coherent-cache handoff smoke

`python3 simulator/gsim/jtag_boot.py` now exercises a real two-issue CPU executing a small assembly ROM through OPEN, frozen descriptor validation, epoch-bound CLAIM, `fence.i`, and actual execution of newly downloaded RAM instructions. It uses the production staged coherent DMA route, but synchronous DMI injection bypasses TCK. To keep this test short it uses 1 MiB RAM at `0x80020000`, 8 data-cache lines and 4 instruction-cache lines. This is not the selected board's geometry, external DDR, NEMU comparison, complete production BootROM C or its CRC computation; the assembly checks a fixed CRC metadata token.

All test code/data is explicitly initialized, then all 192 bytes of the replacement image are written and read back through SBA. The old RAM program first retires and primes the I-cache; CPU reads a clean owned line and writes a dirty owned line. The independent retired-instruction/register oracle records:

- 1,336 cycles, 477 total retired instructions, 31 downloaded-RAM retirements
- One clean owned ProbeAck and eight dirty ProbeAckData beats, including the CPU's old dirty word `0x55667788`
- One retired `fence.i`, explicit fetch invalidation and one RAM instruction refill before/after download
- Correct frozen generation/entry and irreversibly CLAIMED endpoint, with host edits rejected

Both same-model negative runs fail the independent instruction oracle: deleting `fence.i` retires the cached old instruction `0x11100d13`; corrupting the downloaded instruction retires `0x5a400d13`; both differ from expected `0x5a500d13`. ASan/UBSan stay enabled. The GSIM model uses static storage so invalid queue-array entries cannot contain out-of-width host garbage before their valid bit is set; architectural test data never relies on that host initialization. The final pre/post source hashes match and evidence is in `docs/debug/evidence/ram-download/cpu-smoke/`.

## Subsequent BootROM auto-start/TUI revision

The current firmware replaces separate manual launch with checked automatic startup
for UART/TFTP/JTAG and adds the ANSI/VT100 menu. See
[the new firmware evidence](../../fpga/firmware/tests/tui-evidence/receipt.json).
The earlier source hashes and default-off export/firmware identity comparison are
historical evidence for the JTAG checkpoint, not a byte-identity claim for this
new BootROM binary. The synthetic assembly CPU smoke remains separate from the
unverified production C firmware + selected CPU/cache/DDR/physical board gate.
