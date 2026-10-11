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
| `unisim` | Real `JTAG_SIME2` and `BSCANE2`, three independent-clock phase ratios, independent readback negative and five identity negatives | Full dbg_hub simulation, memory bus owner, metastability/STA |
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

## Vendor model identity is separate from the physical board identity

The offline exact-part BSDL says physical IR12, USER1=0x902, USER2=0x903 and
IDCODE 0x04750093 with mask 0x0fffffff. Keep the existing BSDL/OpenOCD settings
unchanged. The physical TAP order and nSRST wiring remain unknown.

Read-only inspection of the installed Vivado 2025.1 sources on 2026-10-11 found
the simulation identity below for `PART_NAME="XCZU15EG"`. This is distinct from
both the physical BSDL and older archived model revisions. The supported
simulation profile is explicitly named `vivado-2025.1-xczu15eg`; it is never a
default, and an unreviewed profile or conflicting numeric override is rejected.

| Field | Simulation profile | Physical BSDL/OpenOCD |
|---|---|---|
| IR length | 12 | 12 |
| USER1 | 0x0a4 | 0x902 |
| USER2 | 0x0e4 | 0x903 |
| IDCODE | exact 0x04a52093, all 32 bits | 0x04750093, mask 0x0fffffff |

The runner pins these installed file SHA-256 values and rejects drift before
invoking even a tool version probe:

- `JTAG_SIME2.v`: `73db6473f4d162bacc0c42ca1d28986ad2074e986b7ebe122cba615e5f8a536d`
- `BSCANE2.v`: `77795f9c236f62c74c07ce61a2deaecc5c8816e94fe8cd4b2de1646f56bbaf8b`

`glbl.v` and test inputs retain the runner's source/drift hashing. Vendor files
are read from the explicitly selected existing installation and are never
modified. `unisims_ver` is still the vendor library; no replacement primitive
is introduced. The bench independently checks the named profile tag, the exact
IR/USER/full-ID values and the instantiated model attributes before traffic.
The named `unisim-profile` run also validates its printed values against the
profile. An unnamed `unisim-profile` run remains inspection-only, with no claim
that its identity matches the supported profile.

At base commit `adf7059513be64c61303dd17de344ac446ab0cca`, the bench incorrectly
required `(tap.IDCODEval_sig & 32'h0fffffff) === 32'h04750093`. The installed
simulation ID would fail this assertion before a USER transaction. This is a
source/host arithmetic finding, not an observed xsim failure: xsim had not been
run when this fix was prepared. The [retained finding](evidence/xsim-vendor-profile-20261011.json)
binds the original bench hash, original condition and inspected source hashes.
`vendor_bad_legacy_physical_id` now deliberately supplies the physical ID as a
simulation expectation and must reach `UNISIM_IDCODE_MISMATCH`. Four additional
identity negatives independently corrupt the profile tag, IR length, USER1 and
USER2. None may pass from an unrelated fatal or a compile failure.

From this patched snapshot, on the authorized local executor, use fresh result
directories and the verified existing installation root:

```text
python simulator/jtag/run_xsim.py --suite unisim-profile --model-profile vivado-2025.1-xczu15eg --output <fresh-profile-results> --run --vivado-root <existing-Vivado-installation>
python simulator/jtag/run_xsim.py --suite unisim --model-profile vivado-2025.1-xczu15eg --output <fresh-unisim-results> --run --vivado-root <existing-Vivado-installation>
```

Prerequisites: Python 3, the installation's `bin/xvlog`, `bin/xelab`, `bin/xsim`
(the `.bat` variants on Windows), `data/verilog/src/glbl.v`, the two pinned
`data/verilog/src/unisims/` sources, and its usable `unisims_ver` library.
No installation or download is performed. First require
`PROFILE_PRINTED_NOT_PROTOCOL_QUALIFIED` with both model verification fields
true; then require all nine unisim cases and `PASS_SIMULATION_ONLY`. Preparation
without `--run` still does not claim execution or installed hash verification
unless the actual installation path was supplied. If hashes, attributes or
runtime behavior differ, retain the failure and review the actual installed
model; do not widen the physical accepted ID, edit vendor sources, waive the
checks or switch the part. These commands have not been executed as part of the
host-side fix.

JTAG_SIME2 models only part of the JTAG interface, so this test does not discover
the board's TAP order. [AMD JTAG simulation scope](https://docs.amd.com/r/2020.2-English/ug900-vivado-logic-simulation/JTAG-Simulation).

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
