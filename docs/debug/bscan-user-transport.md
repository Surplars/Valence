# Optional FPGA USER-chain RAM-download transport

`ValenceBscanDebugPort.sv` adds an **opt-in transport implementation** for the
FPGA's existing dedicated JTAG pins. It does not instantiate another soft TAP,
change default board settings, reserve a USER chain by default, or add package
pins. RAM access, download limits, ROM coordination, and execution policy remain
responsibilities of the separately connected loader endpoint.

The repository's actual target is **xczu15eg-ffvb1156-2-i**, a Zynq UltraScale+
part (see `fpga/zu15eg/configure_project.tcl`). AMD documents the BSCANE2 interface
for UltraScale and identifies it as the same primitive used in 7-series. This
wrapper is suitable as a source-level integration candidate for those families;
it is not a board-qualified primitive simulation or timing result.
[AMD UG570 BSCANE2](https://docs.amd.com/r/en-US/ug570-ultrascale-configuration/BSCANE2).

## Physical path and explicit configuration

The path is:

`SMT2 -> existing FPGA TAP -> selected USER instruction -> BSCANE2 -> custom
64-bit DR engine -> capacity-one DMI CDC -> RAM-loader endpoint`.

The enabled wrapper instantiates a real `BSCANE2`, connecting `CAPTURE`, `SHIFT`,
`UPDATE`, `SEL`, `DRCK`, `TCK`, `RESET`, `TDI`, and `TDO`. `JTAG_CHAIN` selects
USER1 through USER4, and the board must allocate a chain not already owned by
an ILA/debug hub or another design component. `ENABLE=0` is the default and
eliminates the wrapper's primitive and state. `JTAG_CHAIN=0` deliberately has no
valid enabled meaning; an enabled caller must choose 1..4 explicitly.
[AMD primitive ports and attributes](https://docs.amd.com/r/2025.2-English/ug953-vivado-7series-libraries/BSCANE2).

The adapter is confirmed as **Digilent JTAG-SMT2**. OpenOCD's maintained adapter
file is `interface/ftdi/digilent_jtag_smt2.cfg`, using its FTDI driver with USB
VID/PID `0403:6014`. This is an adapter choice, not proof of the board's scan
chain. Its GPIO/SRST wiring must be checked against the board before use; this
implementation makes no USB-driver, reset-wiring, or host-access changes.
[OpenOCD adapter source](https://github.com/openocd-org/openocd/blob/master/tcl/interface/ftdi/digilent_jtag_smt2.cfg),
[Digilent SMT2 reference manual, rev. D](https://digilent.com/reference/_media/jtag_smt2:jtag-smt2_rm.pdf).

The board configuration must supply:

- Physical TAP names and order, including any exposed PS/DAP or other devices
- Physical FPGA TAP IR width and actual observed/expected FPGA IDCODE
- The **full physical instruction value** for the allocated USER chain
- The matching RTL `JTAG_CHAIN` and a verified, conservative TCK rate
- The exact optional image that contains this wrapper and matching loader/ROM

Do not substitute the standalone soft TAP's five-bit IR or transport IDCODE.
OpenOCD's ZynqMP configuration declares a 12-bit device TAP and lists the
ZU15EG IDCODE base `0x04750093`; revision bits and actual chain exposure still
need verification on the target. Its full A53 configuration also performs PS
chain configuration, so it is not an inert template to source blindly for this
loader. **No six-bit USER opcode is assumed or zero-extended here.** Obtain the
matching full-width USER opcode from the actual part's BSDL/device description
and verify that it selects this image's allocated chain.
[OpenOCD ZynqMP target source](https://github.com/openocd-org/openocd/blob/master/tcl/target/xilinx_zynqmp.cfg),
[OpenOCD TAP declaration requirements](https://openocd.org/doc/html/TAP-Declaration.html).

## Protocol version 1

This is **Valence's custom USER data register**, not the SiFive/OpenOCD
`riscv use_bscan_tunnel` framing, not DTMCS, and not a standard RISC-V Debug
Module. A raw `irscan` selects the physical USER instruction, then a `drscan`
transfers exactly **64 bits, least-significant bit first**. OpenOCD should split
the scan into fields of at most 32 bits:

`drscan $fpga_tap 2 $op 32 $data 7 $address 3 0 4 1 16 0x5642`

This uses OpenOCD's documented low-level commands. Its native BSCAN tunnel has
a different framing and is intentionally not enabled by the supplied backend.
[Low-level JTAG commands](https://openocd.org/doc/html/JTAG-Commands.html),
[OpenOCD BSCAN tunnel format](https://openocd.org/doc/html/Architecture-and-Core-Commands.html#riscv).

| Bits | Request written at UPDATE | Response sampled at CAPTURE |
|---|---|---|
| 63:48 | `0x5642` signature | `0x5642` signature |
| 47:44 | Version `1` | Version `1` |
| 43 | Zero | Sticky protocol error |
| 42 | Zero | Busy, including a pending UPDATE event |
| 41 | Zero | Result-valid / DONE |
| 40:34 | Seven-bit DMI/control address | Completed/accepted request address |
| 33:2 | 32-bit data | Completed data |
| 1:0 | Operation | Status: 0 success, 2 failed, 3 busy |

Operations:

- `0`: poll/NOP. It does not consume a result or create a busy error.
- `1`: DMI read, one outstanding transaction at most.
- `2`: DMI write, one outstanding transaction at most.
- `3`, address `0`, data `0`: local capability result `0x00000701`, identifying
  protocol version 1 and DMI address width 7; no endpoint memory access.
- `3`, address `1`, data `0`: clear retained result/protocol error, **only idle**.
  Does not cancel a request. An impossible UPDATE-event overrun instead requires
  a TAP reset or explicit hard transport reset.
- `3`, address `2`, data `0`: explicit hard transport reset/cancellation. The
  supplied loader never uses this as an automatic timeout retry.

Unsupported controls, nonzero request flag bits, wrong signature/version,
short or overlong scans, and non-NOP commands while busy fail closed and set
protocol error. The scan count saturates at 65, so a long scan cannot wrap into
acceptance. DMI commands are blocked until the error is cleared. An endpoint's
nonzero status becomes a completed status-2 failure without creating a protocol
error. Result data/DONE persist across polls until a new command, clear, or reset.

Every DR scan returns the snapshot taken **before** its incoming operation is
committed. Ignore the submit scan's old result. Give the adapter at least eight
Run-Test/Idle TCK cycles, then poll until busy is clear and DONE is set. Verify
signature, version, protocol error, status, and echoed address. Eight cycles are
a transport settling minimum, not a destination-response latency guarantee.
On timeout, stop with an uncertain outcome; never blindly resend a write.
The host backend is `simulator/jtag/ram-loader-bscan.tcl` and is selected through
`openocd-ram-loader-bscan.cfg` after verified board/adapter configuration.

## Clock and reset contract

- CAPTURE and SHIFT act on positive **DRCK** edges. Shift pause/resume retains
  the count and data; deselected USER activity cannot update a command.
- The primitive already registers its TDO input on falling TCK. The engine
  therefore connects the scan register LSB directly to `BSCANE2.TDO`; an extra
  falling-edge register would skew the outgoing bitstream.
- Positive **UPDATE** captures the completed scan into a separate held frame
  and toggles an event. It is not treated as an enable assumed to arrive before
  a particular negative TCK edge. A two-stage event synchronizer is consumed by
  the negative-TCK controller, which drives the existing `ValenceDmiCdc` source.
- The held frame cannot be overwritten before acknowledgement. Legal TAP
  sequencing provides more TCK cycles than this event needs, even for a later
  short scan. An invalid second UPDATE while pending is nevertheless rejected.
- Pending UPDATE participates in BUSY immediately. Completion data, status, and
  DONE change together on negative TCK; Capture sees either busy/old result or
  the complete new result, never success paired with stale data.

These phases follow AMD's primitive contract, including UPDATE's own event and
the primitive's falling-edge TDO register.
[AMD BSCANE2 pin descriptions](https://docs.amd.com/r/en-US/ug570-ultrascale-configuration/Pin-Descriptions).

`debug_por_n` and primitive `RESET` asynchronously cancel all scan/event/mailbox
state. The source and destination release locally after clocked synchronization.
The explicit hard-reset command asserts a full-TCK-period shared reset and clears
both event toggles, so a held frame cannot replay into a freshly reset mailbox.
Stopped TCK/DRCK does not prevent external reset assertion; it does prevent source
release/progress, so idle clock pulses are required before probing. Reset or
cable loss cannot roll back a RAM write already accepted downstream.

**Endpoint ownership requirement:** connect `dmi_reset_n` as a transport/session
cancellation indication according to the loader integration contract. A memory
bus request already accepted must retain its downstream transaction ownership
until its response is drained, even when the JTAG session disappears. Do not
use a transport reset to free/reuse an outstanding bus owner or reset the whole
SoC indiscriminately. This transport alone cannot guarantee downstream draining.

## Physical implementation still required

No board XDC or enable defaults are changed by this file. Before an enabled
image can be qualified:

1. Constrain the actual primitive TCK/DRCK/UPDATE clocks and their relationships
   using the target family's timing model and final hierarchy.
2. Analyze DRCK scan-register to UPDATE-held-frame paths, UPDATE-held-frame to
   negative-TCK consumer paths, and the event/acknowledgement crossings.
3. Preserve the synchronizer attributes and apply the existing mailbox's scoped
   request/response bundled-data max-delay constraints to its actual hierarchy.
4. Analyze reset assertion/release and primitive-internal TDI/TDO timing, including
   the UltraScale+ special internal pins where applicable. Do not copy standalone
   package-pin constraints onto this internal primitive or blanket-false-path all
   BSCAN clocks.
5. Check USER-chain/debug-hub conflicts, primitive simulation, synthesis and STA,
   then the real SMT2/board link. None has been performed by the source checks.

## Verification evidence and limits

- `python3 -B simulator/jtag/bscan_check.py`: source-structure checks and 120
  independent fixed-width wire-codec vectors. No HDL simulation or elaboration.
- `python3 -B simulator/jtag/bscan_run.py`: optional native test entry point.
  It records source hashes and exits **77 / blocked** when existing Icarus/vvp
  are absent; it never installs a tool or uses a retired simulator.
- `bscan_user_tb.sv` contains phase-aware primitive-interface tests for capability,
  read/write, zero-idle Update-to-Capture, pause/resume, deselection, stopped TCK,
  request backpressure, busy-command rejection, endpoint failure, zero/short/
  overlong scans (including count-wrap rejection), malformed signature/flags,
  explicit transport reset, and asynchronous reset with stopped clocks.
  It is a behavioral interface model, **not AMD UNISIM**.

In this environment Icarus/vvp are unavailable, so the native test is **unrun**.
The available `firtool` accepts FIR/MLIR input, not handwritten SystemVerilog;
Chisel export of a blackbox is not parsing or simulating this SV. Physical CDC,
primitive timing, synthesis, bitstream generation, and board operation remain
unverified. Host Tcl mock tests separately validate host protocol handling and
must not be presented as HDL or end-to-end hardware results.
