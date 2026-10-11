# BSCAN positive-TCK qualification candidate

Status: source-controlled structural candidate. Logical production-transport tests
pass; **AMD primitive execution, synthesized/routed timing and board qualification
for this changed candidate have not run**. This does not close the reported
pre-route −7.703 ns hold violation by assertion or waiver.

## Bounded change

`ValenceBscanUserTransport` retains native rising-UPDATE whole-frame capture.
Its UPDATE bank now sees two positive-TCK qualifiers:

- `update_selected` samples `SEL && source_release[2]`.
- `update_ack` samples the acknowledgement **bit**, `update_seen`.
- Capture tests the live UPDATE-local `update_toggle == update_ack`.

A latched Boolean “free” is unsafe: after one accepted event, a second UPDATE
without TCK would still see “free” and overwrite the first frame. The live-toggle
comparison prevents this. The overrun remains sticky and preserves the first
frame.

`update_release[2:0]` asynchronously asserts from the unchanged work reset and
releases on positive TCK. Its final bit resets both the qualifier registers and
the UPDATE bank. No raw negative-TCK release, raw ACK or raw SEL drives UPDATE
D/CE. The original source/consumer and mailbox reset and ownership laws remain.

Estimated structural cost: **five flip-flops** (three release, two qualifiers),
no additional scan bit, frame register, DMI transaction or legal scan latency.
This is source counting, not a synthesized resource or frequency result.

### Adjacent reset edges

After asynchronous reset, beginning with TCK low:

| Edge | Positive release | Negative source release | Selection qualifier |
|---|---|---|---|
| third positive TCK | becomes released | still reset | stays reset on this edge |
| third negative TCK | released | becomes released | remains false |
| fourth positive TCK | released | released | samples SEL and readiness |

The focused bench checks each of the first four rises/falls and rejects early
UPDATE events, then starts the first complete command without a long release
wait. Reset while TCK is stopped high or low clears pending frames immediately;
release without clocks cannot replay them. Hard-reset assertion also reaches
this positive island while stopped.

### Preserved protocol and timing paths

The 64-bit custom USER2 transport, length saturation/check, signature/version,
NOP polling, result ownership and immediate BUSY indication are unchanged.
This frame has no frame CRC. Download CRC remains host/ROM metadata verification;
`JtagRamLoader.scala`, host loader scripts, BootROM and `ValenceDmiCdc` are
unchanged. Link reset does not clear a held or accepted fabric transaction owner.

All related paths remain timed, including:

- SEL / negative source-ready / negative ACK into positive qualifiers
- positive qualifiers into UPDATE D/CE
- DRCK `shift_frame`, `shift_count`, `scan_captured` into UPDATE
- UPDATE toggle/data into the negative-TCK consumer and returned ACK
- response capture/TDO and functional reset recovery/removal

A positive-TCK qualifier removes the *specific same-falling-edge control
launch*, but is not proof that every hold path is fixed. The shortest legal
UPDATE-to-UPDATE sequence is four TCK cycles; the consumer ACK reaches the
positive qualifier before its fourth falling-edge UPDATE. Sixteen consecutive
empty-scan turnovers exercise this without idle padding.

## Tracked timing/export contract

`fpga/next/bscan_timing.tcl`, `bscan-timing-profile.json` and
`bscan_integration.py` are exported and hashed with the functional source.
`board/bscan-timing-contract.json` records exact exported bytes and invocation
requirements. Other USER chains do not silently inherit this USER2 board profile.

The candidate profile is explicitly `zu15eg-user2-tck50-positive-v1` for
full released industrial part xczu15eg-ffvb1156-2-i, USER2. The historical
report label without `-i` is not accepted as an unverified tool alias; any real
normalization must be reviewed with package/speed/temperature metadata. It retains INTERNAL_TCK 50 ns, waveform `{0 25}`, DRCK
`-divide_by 1`, and UPDATE `-edges {2 3 4}` as a conservative event envelope.
The primitive's clock delay is propagated by STA, never added again as a waveform
shift. Unlike the older untracked provisional recipe, setup/hold uncertainty
0.100 ns is explicit on **all nine related clock pairs**. The TDI/TMS
falling-TCK max 15 ns/min 0 ns adapter delays remain assumptions requiring
characterization, not measured board facts.

After synthesis, discover exact matching primitive/transport cells and call:

```tcl
source board/bscan_timing.tcl
valence_apply_bscan_timing $exact_primitive $exact_engine $fabric_clock zu15eg-user2-tck50-positive-v1
# After opt_design, validate regenerated shapes and reapply scoped CDC constraints:
valence_reapply_bscan_cdc $exact_primitive $exact_engine $fabric_clock
source board/audit_bscan_netlist.tcl
valence_collect_bscan_netlist $exact_primitive $exact_engine $fabric_clock $fresh_report_directory
```

Missing, ambiguous, reshaped or mismatched objects fail closed. The helper checks
FDCE clock polarity/domain, three-stage reset chains, constant-one first D,
direct intermediate Q→D connections, no intermediate functional fanout,
ASYNC_REG, positive qualifier and UPDATE clock domains, raw-control cone
exclusion, and the UPDATE/qualifier functional-reset origin. Only the **12 CLR
pins of four checked three-stage release banks** receive reset false paths.
Functional reset sinks remain timed.

The two true debug-clock mailbox toggle→first-stage paths receive 8 ns
`-datapath_only` max delay; only the request 41-bit and response 34-bit held
bundles receive 8 ns max delay and 8 ns bus skew. There is no related-clock
false path, multicycle or clock-group exception.

This is a reviewed source candidate replacing an untracked provisional recipe,
not a promotion of that recipe to physical signoff. Tcl mock passes prove script
selectors and fail-closed behavior, not real Vivado object topology or timing.

## Reproduce the small cloud checks

Use an existing Icarus 12 installation; no Verilator, Scala/SoC build or Vivado is
invoked by these commands. Every compile/run is serial, capped at 1 GiB and 60 s;
receipts record commands, input/log hashes, exits, duration and actual peak RSS.

```sh
python3 simulator/jtag/bscan_check.py
python3 simulator/jtag/test_bscan_qualification.py
python3 -m unittest discover -s simulator/jtag -p test_xsim_runner.py
tclsh simulator/jtag/test_bscan_netlist_audit.tcl
tclsh simulator/jtag/test_bscan_timing.tcl
python3 simulator/jtag/bscan_qualification_run.py --output FRESH_LOGICAL_OUTPUT
python3 simulator/jtag/bscan_qualification_mutations.py --output FRESH_MUTATION_OUTPUT
```

The inherited transport/CDC benches needed portability-only repairs: an unspaced
hex-literal ternary was ambiguous to Icarus, and declaration-only time-zero reset
levels did not produce reliable reset events. A baseline RTL comparison
reproduced the initial transport failure. Explicit reset establishment fixes
these benches; the new qualification bench separately checks the shortest
release sequence rather than hiding it behind warm-up clocks. Transport lengths
0/1/63/64/65/192, pause, immediate capture, stopped TCK, deselection,
backpressure, overlap, endpoint failure and hard/POR reset are covered.

Behavioral negative controls include sampled-free overwrite, raw SEL,
raw reset release, negative-edge qualifier, wrong length and missing
asynchronous assertion. Source/Tcl gates additionally reject direct negative
ACK/source-ready paths, malformed reset chains, wrong domains and widened scope.

### Reused production loader drain fixture

If the source-bound saved board export is available, reuse its actual
JtagRamLoader, with **unchanged 1,000,000-cycle timeout**, for offered-reset,
accepted-timeout, late-drain, bus-error and MMIO rejection:

```sh
VALENCE_BOARD_LOADER_FIXTURE=BOARD_EXPORT/rtl/JtagRamLoader.sv python3 simulator/jtag/test_loader_lifetime_adapter.py
python3 simulator/jtag/bscan_qualification_run.py --case board_drain --case board_drain_bad_owner \
  --board-loader-export BOARD_EXPORT --adapt-board-loader-lifetimes --output FRESH_DRAIN_OUTPUT
```

Icarus cannot compile firtool's `automatic logic` block locals directly. The
optional adapter accepts **only** original SHA256
`c0e45a9e864311cb67bac3ed97e24e14aa0169a363634b71474df58148142e4f` and creates a
separate test copy, SHA256
`4d861109b6aaf75a6c600e3ba9b2bfd90d889c828ccc9b4dd9a3457e9ce2429b`.
It checks one non-reentrant, delay-free sequential process, six exact declaration
groups and unconditional assignment before first read for all 78 temporaries.
Five automatic declaration initializers become explicit per-entry assignments,
in original order, after their declarations. Unknown source, added delays or
missing/reordered initializers fail closed. This is not a general SV lowering;
original/generated production RTL is never modified. The original compiler
failure is retained as evidence and is not counted as a test pass.

## Vendor and physical qualification still required

Prepare a source-bound, separate installed-model run (no runtime claim):

```sh
python3 simulator/jtag/run_xsim.py --suite unisim --model-profile vivado-2025.1-xczu15eg --output FRESH_VENDOR_PLAN
```

The vendor bench now observes TAP state and SEL/UPDATE events during IR as well
as DR, checks sampled qualification before every selected UPDATE, direct
USER1→USER2 IR-to-DR scans without idle, eight shortest empty turnovers,
1/63/64/65-bit scans and reset of a pending UPDATE. The runner retains three
prior independent-clock ratios and adds exact 50 ns / 50% TCK (the helper's
23 ns low argument plus its 2 ns trailing delay, 25 ns high). All six independent
readback/identity negatives remain. These added checks are **prepared, unrun**
in cloud; historical local passes concern earlier bytes and cannot qualify them.
Simulation USER2=0x0e4 / ID=0x04a52093 stays distinct from physical BSDL
USER2=0x903 / ID=0x04750093.

For the later authorized combined physical batch:

1. Bind the integrated source/export, exact USER2/part/hierarchy, installed model
   hashes, complete applied Tcl, and each pre-/post-opt checkpoint/report.
2. Pass real bank/qualifier/reset audits after synthesis and after opt_design;
   inspect expanded exception coverage for unrelated outside-script cuts.
3. Collect related clock waveforms/uncertainty, UPDATE D/CE setup and hold,
   DRCK data/count/capture→UPDATE, UPDATE→TCK data/toggle, ACK→qualifier,
   response capture/TDO, pulse width and functional reset recovery/removal.
4. Review slow/fast min/max corners and the actual routed design. Retain the
   stopped pre-route violation as historical evidence; do not relabel it routed.
5. Characterize adapter duty/input assumptions and validate board behavior only
   when separately authorized. No local build, rerun or bitstream is implied.
