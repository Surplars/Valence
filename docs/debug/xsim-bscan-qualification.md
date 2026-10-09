# Native JTAG/BSCAN qualification with an existing Vivado installation

This package is **prepared source, not an executed HDL result**. Cloud Python
and Tcl tests validate preparation, fail-closed result classification and report
selection only. No xsim, vendor primitive, local Vivado project, hardware cable,
driver, synthesis or bitstream is touched while preparing it. Existing defaults
and the current board implementation inputs are unchanged.

`simulator/jtag/run_xsim.py` defaults to `PREPARED_NOT_RUN`. Execution requires
both `--run` and an explicit existing `--vivado-root`. It uses that installation's
`xvlog`, `xelab`, `xsim`, glbl and `unisims_ver`; it never installs/fetches tools
or tries a fallback simulator. Use a fresh output directory for each suite.
Actual execution belongs in a separately authorized desktop task after the
currently running Vivado work is finished.

## Four distinct suites

| Suite | Inputs and intended evidence | Does not establish |
|---|---|---|
| `protocol` | Seven native cases: soft-TAP arcs/IR/IDCODE/BYPASS/fail stub, mailbox CDC, completion-phase regression, ABITS 1/7/32, BSCAN pin-event protocol model | Real FPGA BSCANE2, board TAP, physical timing |
| `unisim-profile` | Installed `JTAG_SIME2` attributes printed with model source hashes | Any USER transaction or board scan |
| `unisim` | Real `JTAG_SIME2` and `BSCANE2`, three independent-clock phase ratios, independent readback negative | Full dbg_hub simulation, memory bus owner, metastability/STA |
| `loader-drain` | Actual generated `JtagRamLoader` plus `ValenceDmiCdc`, three clock ratios and wrong-owner-reset negative | CPU/cache/DDR execution, TAP or vendor primitive |

The last two suites are complementary. The vendor suite uses a clearly named
endpoint model that cancels its temporary response on link reset. It must not be
used as proof that an accepted real memory transaction can be cancelled.

The runner requires an explicit clean PASS marker for positive cases, and the
specific expected oracle rejection with no PASS for negatives. A compile error,
missing marker or unrelated fatal is never a successful negative. Some xsim
versions return zero after HDL `$fatal`, so the diagnostic itself is also checked.
Source and log hashes are recorded; reports always keep board/physical signoff
false. A failed or partial execution must not be relabeled as a completed suite.

### Cloud preparation and static checks

```sh
python3 simulator/jtag/test_xsim_runner.py
tclsh simulator/jtag/test_bscan_netlist_audit.tcl
python3 simulator/jtag/run_xsim.py --suite protocol --output <fresh-prepared-dir>
python3 simulator/jtag/run_xsim.py --suite unisim-profile --output <another-fresh-dir>
```

No tool binary is invoked by preparation. The stored command arrays show exactly
what the eventual run will do. `xelab -mt off` keeps these small tests bounded;
each compiler/run process has a wall-time timeout, and benches have simulation
watchdogs. The launcher uses argument arrays, not a generated shell command.

### Separately authorized execution on the installed toolchain

From the matching source snapshot, with Python already available:

```text
python simulator/jtag/run_xsim.py --suite protocol --output <fresh-results> --run --vivado-root <existing-Vivado-installation>
python simulator/jtag/run_xsim.py --suite unisim-profile --output <fresh-profile-results> --run --vivado-root <existing-Vivado-installation>
```

Vivado 2025.1 was previously found locally; its installation must still be
checked by the desktop task. Do not launch a hardware manager, change the active
project, acquire SMT2, or alter Windows USB bindings for these simulation tests.
Compile/elaboration uses the documented command-line simulator workflow.
[AMD UG900 command options](https://docs.amd.com/r/2025.1-English/ug900-vivado-logic-simulation/xelab-xvhdl-and-xvlog-xsim-Command-Options).

## Vendor model IR is not the physical board IR

The offline exact-part BSDL says physical IR12, USER2=0x903 and fixed ID
0x04750093. Keep the existing host profile unchanged.

There is a material simulation-model distinction: the officially published
archived `JTAG_SIME2.v` selects IR length 16 for `XCZU15EG`, with USER opcodes
selected from its model constants. This observation does not explain or prove
any physical PS/DAP chain layout. The installed 2025.1 model, not that archived
file, is the execution input. First record its file hashes and profile output;
inspect the matching installed model/template. Do not patch a vendor model or
fall back to a different part to make a test pass.
[Official archived model source](https://github.com/Xilinx/XilinxUnisimLibrary/blob/master/verilog/src/unisims/JTAG_SIME2.v).

After the profile is understood, pass its exact values explicitly:

```text
python simulator/jtag/run_xsim.py --suite unisim --model-ir-length <MODEL_IR_LENGTH> --model-user1 <MODEL_USER1_OPCODE> --model-user2 <MODEL_USER2_OPCODE> --output <fresh-results> --run --vivado-root <existing-Vivado-installation>
```

The bench independently checks the supplied parameters against the instantiated
vendor attributes and the part ID. No numeric simulation profile is a default.
If the installed model changes its internal attribute names, stop and update
the profile adapter after review; do not waive that check. JTAG_SIME2 models only
part of the JTAG interface, so this test does not discover the board's TAP order.
[AMD JTAG simulation scope](https://docs.amd.com/r/2020.2-English/ug900-vivado-logic-simulation/JTAG-Simulation).

## Clock phases and vendor test coverage

The real primitive is instantiated by the unchanged production wrapper on
USER2. A second BSCANE2 on USER1 is a simple independent consumer, not a pretend
dbg_hub. The bench verifies USER isolation; the actual debug-hub collision guard
must still run against the new enabled netlist.

- TDI/TMS are driven during low TCK and TDO is sampled before the next rising
  edge. No extra falling-edge TDO register is inserted into the test connection.
- DRCK capture/shift edges are counted. On UPDATE's rising event, the bench
  checks the production engine's shifted length and held 64-bit frame. UPDATE
  is not fabricated from DRCK. The source controller still consumes on negative
  TCK using the existing synchronized event.
- Directed cases exercise zero-idle UPDATE-to-next-capture, pause/resume, last
  shifted bits, USER1 deselection, stopped TCK immediately after UPDATE, held
  downstream request, malformed scan lengths, endpoint error, external reset
  with TCK stopped, TAP reset, and no stale replay. The protocol-model suite
  additionally exercises bad signatures/version/reserved bits, overlap and hard
  transport reset. The directed completion regression checks both data/status
  forwarding and a failure hidden behind sticky DMI BUSY.
- Three clock/rate/phase parameter sets intentionally vary the event ordering.
  This is digital multi-clock simulation, not metastability proof.

These phase obligations follow the primitive interface: DRCK is gated to
capture/shift, TDO is sampled at falling TCK, and UPDATE has its own rising
event. [AMD BSCANE2 pin contract](https://docs.amd.com/r/en-US/ug570-ultrascale-configuration/Pin-Descriptions?contentId=6_C1wrsUFG~1m0jvlyc4xg).

## Native bus-owner drain fixture

Export once on the approved cloud compile slot or existing build environment:

```sh
mill -i IonSoC.test.runMain debug.JtagRamNativeMain <fresh-loader-rtl>
```

The emitter binds the build definition/version, loader, DMI type, bus type and emitter sources; it exports
the actual production endpoint with test aperture 0x80200000..0x80201000 and a
64-cycle timeout. The native runner rejects a missing/mismatched fixture receipt.
This is not a hand-written model of the endpoint. The emitter was prepared here;
its compilation/export and the HDL execution remain separate pending gates.

```text
python simulator/jtag/run_xsim.py --suite loader-drain --loader-rtl <source-bound-fixture> --output <fresh-results> --run --vivado-root <existing-Vivado-installation>
```

The bench checks offered-but-stalled request/payload retention across link reset,
accepted timeout with BUSY retained, blocked OPEN while draining, late reply
consumption, clean re-arm only after drain, bus errors, MMIO rejection and no CDC
request replay. The negative deliberately connects transport reset to the fabric
owner reset and must fail the independent owner-retention oracle. This does not
test a CPU, DDR or production BootROM CRC/CLAIM execution.

## New-image constraint and CDC/RDC review checklist

Do not apply the standalone package-TCK `jtag-reservation.xdc.example` to BSCAN.
Do not add a blanket asynchronous clock-group cut. No numeric BSCAN timing
budget is invented by this package.

1. Open a separately generated matching enabled synthesis/checkpoint. Run its
   mandatory `board/require_jtag_chain.tcl`, with exact loader primitive path.
   It must prove exactly one USER2 owner and no dbg_hub/other BSCANE2 conflict.
2. Inspect BSCANE2's special internal timing pins on UltraScale+. Define the
   supported maximum external TCK rate, waveform and relationships of actual
   TCK, gated DRCK and UPDATE using the installed family model. UPDATE is an
   event clock, not a periodic DRCK substitute; phase/edge exceptions need a
   specific proof. Check all generated clocks and phase relationships.
3. Review these separately, with exact endpoint counts and scoped constraints:
   DRCK shift/counter to UPDATE frame/length; UPDATE frame/toggle to negative-TCK
   consumer; negative-TCK acknowledgement back to UPDATE; capture status/data
   from negative TCK to DRCK; 41-bit held DMI request to fabric capture; 34-bit
   held response to negative-TCK capture. Retained payload paths need derived
   max-delay/bus-skew budgets, not per-bit synchronizers or unconstrained cuts.
4. Check source-release, update-event and bridge request/response/reset-release
   synchronizers retain ASYNC_REG and appropriate placement. Check reset removal,
   recovery, assertion with stopped clocks, independently synchronized release,
   hard transport reset duration, and no coupling to the fabric owner's reset.
5. After supplying the reviewed clock model, the optional read-only collector is:

```tcl
source fpga/next/audit_bscan_netlist.tcl
valence_collect_bscan_netlist <exact-user-scan-cell> <exact-sibling-transport-cell> <fabric-clock-name> <fresh-report-directory>
```

It rejects absent clocks, ambiguous hierarchy, changed synchronizer shapes or
missing ASYNC_REG, reuses the real USER2 collision guard, and collects CDC, clock
interaction, exception coverage and unconstrained timing reports. Its success
means scoped structure/reports exist, **not** that CDC/RDC/timing passed. Optimized
or renamed hierarchy must be reviewed explicitly instead of weakening matches.

6. Inspect every warning and exception; prove the timed bundled-data paths were
   not superseded by wider cuts. Review physical reset and I/O/internal primitive
   arcs, both setup and hold, actual supported TCK limits and routed results.
   Keep this separate from the MAC's 10/100/1000 clock scenarios.
7. Only then undertake a separately authorized SMT2/OpenOCD test, with actual
   board chain order/IR widths, safe reset wiring, new image, paired BootROM,
   readback/CRC/CLAIM and observable downloaded-code execution.

This package adds no production debug functionality and does not implement a
Debug Module, hardware breakpoint, halt, resume, step or native OpenOCD target.
