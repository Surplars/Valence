# R38 fixed TX reset placement diagnostic

This candidate moves only the existing three `tx_release/tx_reset_pipe_reg[0:2]`
FDPEs together from SLICE_X116Y132 to SLICE_X106Y229 EFF2/FFF2/GFF2.
The target EFGH half was empty in the native site census; the other half has
three RAW125 FFs, no RAM or CARRY. Empty BELs are rechecked, then Vivado's
`place_cell` legality is authoritative. No force, alternate-site retry, logic
rewiring, reset-cycle change, ASYNC_REG removal, clock-root change, or exception.

Input (do not substitute RX450 before the CPU-reset ECO):
- E:/VM/Share/Valence-rtl/r38reseteco1/eco/routed-reset-unqualified.dcp
- 79990654 bytes
- SHA256 a4c0da88d92de9762051d0a0abf69965a5ae4163cfb0645080c0587e6b0ae55a
- CPU300/fabric250 performance constraints retained, not the 50/50 analysis clone.

First verify the input and all package hashes externally. Vivado 2025.2 command:

    vivado -mode batch -source route_tx_reset_placement.tcl -tclargs INPUT_DCP FRESH_OUTPUT_DIR tx_reset_placement.tcl

Use absolute paths. The output directory must not exist. A failed mutation is
one-shot: discard that process, never re-source and retry within its netlist.
Do not overwrite any input/checkpoint/evidence.

The script checks exact three-stage topology and all 19 original final loads,
keeps all input connections/consumer locations and RAW125/PAD250 clock geometry
and roots, moves the three cells once, then `route_design -preserve`.
Both timing corners, max/min are checked on two chain paths and all 13 final
FF reset paths before and after. Six mapped OSERDESE3 RST pins did not produce normal slack reports in the
original probe. Native get_timing_paths nevertheless can return an object.
The runtime records its actual properties, finite/nonfinite status and any
finite violation, without asserting an empty collection or claiming coverage.
Their reset connectivity, input drivers and mapped attributes stay unchanged. The three asynchronous entry
PREs remain timed, with no exception in this candidate.

Outputs are explicitly UNQUALIFIED. Even if all 13 final FF paths pass, the
entry recovery failures and any global failures remain unresolved. Review
route status, DRC, complete setup/hold/recovery/removal and preserved RX450
minimums. Then use the existing bounded actual50/50 mode analysis on this new
routed physical candidate; preserve the original300/250 reports. No bitstream,
board acceptance, or frequency qualification is authorized by this script.

Cloud finite guard test: `tclsh test_tx_reset_placement.tcl`.
Result: 1 positive and17 negatives pass (including wrong clock, early stage,
extra load, constant type, occupied BEL, partial place error then re-source,
and altered root/sink). Mock proves guards only, not placement legality/STA.
Independent read-only review of both runtime Tcl files completed without blocker.

Native first placement attempt stopped before mutation because the old runtime
incorrectly equated a no-slack report with zero path objects. The r2 runtime
removes only that diagnostic-count assertion; the13 functional FF and2 chain
paths retain all strict clock/endpoint/finite/exception checks. OSERDES records
remain unqualified and require native interpretation, not a blanket waiver.

The r3 guard uses the native cell collection associated with each exact BEL
(`get_cells -quiet -of_objects [get_bels ...]`), not IS_OCCUPIED: that property
was unsupported on the actual2025.2 BEL object and caused a second pre-mutation
stop. Tests now make every IS_OCCUPIED access throw. All other preflight
properties were already reached successfully in that native attempt. The
only mutable operation remains the one vendor place_cell call.

The r4 sequence first calls `unplace_cell` on exactly the three reviewed FFs,
logs their actual LOC/BEL, requires both empty, then performs the same single
`place_cell` mapping. No property reset, force, alternate site, or broad unroute
is used. This addresses the native r3 LOC/BEL-disagreement failure with a
materially different documented sequence, not a repeated identical command.
The r3 process exited without routing or a new checkpoint; partial in-memory
placement was unknown, so r4 must reopen the immutable input. The one-shot
guard covers unplace as well as place. A failure is never automatically retried.

Official command references: [UG835 2025.2 unplace_cell](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/unplace_cell?contentId=aLJcWhQiVJu4Yn0pYiuHHg),
[UG835 2025.2 place_cell](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/place_cell?contentId=fJ9GyepDaZaBVVdOXauxZw).
They document the operations, not this candidate's physical legality or timing.
Finite tests additionally reject partial unplace and residual BEL, and enforce
unplace-before-place. Native outcome remains required.
