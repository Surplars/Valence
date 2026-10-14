# Ready73 physical evaluation driver

`fpga/next/run_timing_ready73.py` launches the fresh synth/opt/place flow in
`run_timing_ready73.tcl`. This entry prevents gates from running before board
clocks exist, checks actual `TOP` independently of checkpoint `NAME`, and returns
nonzero on any Tcl failure. A zero Vivado exit without the completion marker is
also failure. Completion is not timing, routing, CDC or hardware signoff.

The launcher reuses the existing exact ready73 native-output validator for all
177/94 fields, ordered73 options and constructor audits; binding/export paths
must agree. First export the exact named ready73 entry using its existing strict source and
full parameter checks. Supply a reviewed local Tcl binding with these variables:

- `READY73_EXPORT`: that unchanged staged export directory.
- `READY73_READ_DESIGN`: the existing board/project/IP input setup command list.
- `READY73_CONFIGURE_PYTHON`: the existing explicit native/WSL Python setup command.
- `READY73_SYNTH_ARGS`: board synth options, excluding `-top`/`-generic`, which the
  existing bound native wrapper owns.
- `READY73_ORIGINAL_CLOCKS`: the original board/IP primary clocks and package-only
  XDC setup. Do not apply BSCAN clocks here; the driver applies them once.
- `READY73_CONTROL_CDC`: the existing reviewed board-control CDC procedure.
  It runs after synth and opt; it must not recreate clocks.
- `READY73_BSCAN_ENGINE`: exact sibling transport engine for the USER2 owner.
- `READY73_FABRIC_CLOCK`: exact existing fabric clock for its CDC endpoints.
- `VALENCE_TRISPEED_MBPS`: one rate (10, 100 or 1000).
- `VALENCE_JTAG_OWN_CELL`: the exact observed USER2 loader BSCANE2 owner.

The named entry retains its fixed board top and part. No personal paths, IP
copies, DCP hashes or local credentials belong in the repository.

    python fpga/next/run_timing_ready73.py --vivado /path/to/vivado \
      --binding /path/to/reviewed-local-binding.tcl --export /path/to/named-export \
      --output /fresh/evaluation

The pre-opt gate permits only the exact nonprimitive `dbg_hub` instance with
`REF_NAME=ORIG_REF_NAME=dbg_hub_CV`, which Vivado generates during optimization.
Every other black box fails. After optimization and placement, no black box is
permitted. USER2 allocation is checked at every stage, including the debug core.

The RAW clock witness is the live encoder control FF C pin, with all encoder and
present falling-sample C pins checked against the same real RAW net. The unused
adapter input `u_rgmii/tx_clock` may legitimately be trimmed to GND. The actual
RAW/PAD dividers, common source/reset, polarity, 8/4/2ns periods and waveforms
remain checked. No clock is invented to satisfy an unused input. RAW sampling is
explicitly required by this ready73 driver. The clock witness check is not a
complete RAW payload functional proof.

Constraints are initialized once before mapped gates. Do not reapply the whole
tri-speed recipe after optimization: it deliberately rejects duplicate media
clocks. The driver explicitly applies the original USER2/50ns BSCAN recipe once after
synthesis, and reapplies its scoped CDC constraints after optimization, alongside the
existing MAC packet, board-control and registered-level CDC procedures. Placed
BSCAN checks are read-only. Subsequent stages repeat the mapped/clock and USER2 gates.
Synth/postopt checkpoint sidecars use the existing live-session mechanism;
placement invalidates that seal and produces a separately identified observation.
Never create a new seal for a reopened checkpoint or substitute a recovered DCP
for a fresh-session result.

The already-started diagnostic checkpoint recovery is a separate explicitly
reviewed local process. This driver does not generalize recovery or admit old
checkpoints. Resume such a process only with its independently bound input and
stage evidence, retaining the original failed-session record.

Run host regression with `python fpga/next/test_timing_ready73_driver.py`.
It includes actual-property-shaped mocks for differing NAME/TOP, debug generation
stages, clock-anchor mutations and process failure propagation. Mock success is
not actual Vivado success. Actual synth/opt/place results remain pending until
the corresponding run and reports have been checked.

## Live control witness CE

In this complete source-bound export, `gmiiError` is constant zero. The
encoder's `heldEnable` and rise/fall control bits reset to zero and remain equal: on byte start they receive the same gated GMII enable; otherwise the
control bits retain the held enable. Vivado may merge these registers and
use a dynamic shared FF CE. No particular mapped CE equation is inferred here. Requiring constant-one CE on that live
control clock witness incorrectly rejects this legal mapping. The witness
therefore retains the original gate's direct-Q, FDCE, INIT, reset and clock
checks without adding a CE implementation constraint. This does not remove
the separate constant-one CE requirement on the falling sample FFs or any
serializer next-state equation checks. Source: `TriSpeedRgmiiTx` generated from
the existing MAC encoder; no encoder RTL change is part of this driver fix.

## Typed queries and recovered RX buffer

Tcl list/dictionary assembly can lose Vivado object typing. FIFO timing queries,
constraint scopes and MAC collector helpers now re-resolve the exact escaped
pin/cell names and check the complete returned set before querying properties or
applying constraints. Indexed names remain literal. Endpoint selection and the
existing 8ns datapath-only/skew budgets are unchanged.

Vivado can map the recovered-clock BUFG into BUFGCE. The gate accepts that form
only with a unique constant-POWER CE net and explicit non-inverted I/CE pins.
Missing inversion properties fail. Vivado 2025.1 on the current synthesized
candidate exposed both pin properties as zero and CE as POWER; this observation
supports the property API, not overall timing or physical qualification.

For mapped FF polarity, the collector queries each unique C and CLR/PRE pin's
`IS_INVERTED` property. Vivado may expose empty cell-level inversion properties
while the actual pins report explicit zero. Empty or missing pin properties
still fail, as does true inversion. Boolean literals `1'b0` and `1'b1` are
accepted only as their corresponding explicit values.

BSCAN bank and reset-pin lists are likewise resolved back into checked Vivado
collections before property queries or constraint calls. The phase-handoff
bank, direct drivers, clock edges, USER2 allocation and original 50ns/8ns timing
contracts are unchanged. The current independent checkpoint evaluation has
passed its full input and BSCAN apply gates and entered optimization. Completion
of optimization and placement, and full physical signoff, are separate results;
the fresh public driver also has host orchestration tests rather than a claim
that its entire fresh run has already executed.
