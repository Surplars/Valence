# recovery-r1

This branch starts from persisted common-platform commit `a49a28b1296d216770573f4b08585a24e1d2dfbe`.
It is a new recovery candidate, not the unavailable overnight r6.

The retained r2 ZIP and its 232 generated production modules have verified hashes.
Its baseline-source manifest differs from the available source in seven production
files and fifteen test/harness files. The six complete source files and patches in
that ZIP do not supply all missing predecessor changes. This branch therefore keeps
the exact persisted source as its initial reproducible baseline. It does not claim
to reproduce the r2 SV or inherit its test results.

The first repair targets the source-domain idle announcement feeding the existing
two-stage synchronizers. Existing local transport-empty outputs and protocol
handshakes remain unchanged. First-cycle outbound offers must cancel the registered
announcement on the same source edge. Both directions require focused verification.

Formal board constraints remain mandatory: media/RGMII, BSCAN, management, and CPU/
fabric CDC. The earlier 77 common-boundary scopes alone are not a board signoff.
No bitstream or board programming is authorized before the complete gates pass.

## First repair validation

Both cross-domain idle announcements now come directly from reset-low source
registers. Their next state includes every raw outbound offer, including stalled
offers. The existing local empty outputs, channel handshakes, FIFO capacity,
owner/drain/barrier logic, and destination synchronizers are unchanged. A rising
idle announcement gains one source clock of latency; no bus-data stage is added.

`TransportEmptyAnnouncementSpec` elaborates the actual boundary and evaluates its
emitted Boolean next-state cones over 8192 offer combinations and both local-empty
values in each direction (32768 valuations total). It also checks the reset-low
source registers and direct synchronizer connections, with plain delayed-empty
as a failing first-offer negative control. Existing common-port and TileLink
boundary structural suites pass. The Tcl gate rejects combinational or multiple
idle drivers and will require direct reset-low source FFs on the new mapped design.
This is source-equation/structure verification, not a GSIM traffic run or physical
CDC/RDC/timing qualification. See `validation-source-idle.json`.

Native Windows reproduction uses the pinned Mill 1.1.7 launcher and an installed
JVM via `mill-jvm-version: system`. Run `recovery/run-targeted.ps1` with explicit
`-MillPath`, `-JavaHome`, `-ToolCacheRoot`, and a fresh `-OutputTag`.

The old routed DCP remains a constraint-preparation reference only. Formal media
and BSCAN gates pass in memory, but commonCDC stops at a GND-driven first-stage
Gray bit in the I1 instruction lane because the formal inactive proof has not
passed. That gate is retained. Management/post_opt and full fresh-netlist mapping
remain prerequisites to implementation. No old r2/r6 result qualifies this repair.

## Synthesis preparation checkpoint

`prepare-synthesis.py` validates the native emission profile, every emitted artifact,
the board port ABI and the CPU300/fabric250/UART50 configuration. It copies exactly
three existing IP DCPs into a fresh directory, verifies their hashes and records
source, constraint, interface-stub and IP hashes in `synthesis-inputs.json`.
Existing IP stubs remain read-only inputs. No IP is regenerated or upgraded.
`fpga/common/recovery_synthesize.tcl` synthesizes the new core, saves an explicitly
partial checkpoint, inserts the three existing IP DCPs and rejects any remaining
blackboxes. It then saves an unqualified checkpoint and checks actual clocks.
Implementation and bitstream commands are blocked in this synthesis-only entry.

The first new synthesis is running in Vivado 2025.2; its normal Synthesis/xczu15eg
license checkout succeeded. Completion, linked IP, mapped constraints and timing
have not yet passed. The committed helper is a reproducibility checkpoint, not a
successful synthesis or physical acceptance receipt.

The idle-source collector now distinguishes a completely pruned, unused export
(no port and no synchronizer state) from a missing synchronizer on a retained
export, which still fails. Pure Tcl positive/negative controls pass. The standalone
boundary emitter is preparation for a native FPGA cycle fixture; no cycle-test
pass is claimed at this checkpoint.

## Native FPGA cycle validation

The standalone, unmodified `CommonCpuClockBoundary` export passes the native
Vivado 2025.2 xsim fixture. Independent CPU/fabric clocks (3334ps/4000ps, 719ps
phase) carry 26 complete scalar-request/MSI payloads in each direction. The
fixture requires sustained backpressure, stable stalled payloads, complete drain,
and a second first-offer transition after idle. Direct source registers cancel
idle on both first offers. Results: CPU/fabric stalls 13/8, first-offer checks 2/2.
The intentional bad scoreboard fails with `ORACLE_NEGATIVE_REJECT`; it never
prints PASS. See `validation-native-idle.json`. This is targeted FPGA boundary
behavior, not whole-CPU GSIM acceptance or physical CDC/RDC signoff.

Reproduce by emitting `platform.TransportEmptyAnnouncementMain` into a fresh
folder, generating the bench with `make-idle-cycle-fixture.py`, and invoking
`run-idle-xsim.ps1` with explicit installed Vivado bin and fixture directories.
The generator reads all actual ports and compares every field of both exercised
payloads. It does not modify generated DUT RTL.

Core synthesis completed successfully (0 errors, 3 critical warnings), but the
initial link gate stopped on the additional existing `dbg_hub` blackbox. The
saved core checkpoint permits `recovery_link_ip.tcl` to resume linking without
resynthesis. Linked output remains unqualified until all IP dependencies and
complete board constraints pass. The OOC-import warnings also require checking
that every original IP implementation constraint is represented.

`recovery_map_constraints.tcl` caches exact object names while executing the
formal board entries. Its post_opt entry rehearsal on a synthesized netlist is
explicitly diagnostic; it must run again after real optimization. Common gate
failures remain failures while independent management diagnostics continue.
`inactive_zero_state.tcl` is a new fail-closed induction proof under review: only
INIT-zero FDCE functional state, arbitrary external/release inputs, supported
LUT truth tables, no payload RAM, constant/disconnected data and invariant-zero
valid qualify. Its LUT controls pass; fresh-netlist acceptance is still pending.
No added blanket exception or old signoff is used.

The second link run saved `linked-unqualified.dcp` with zero remaining blackboxes,
including the exact inserted `dbg_hub` / `dbg_hub_CV` instance. Its clock-contract
gate then correctly failed: no clocks were defined after raw OOC DCP insertion.
This is an unqualified netlist, not a successful full synthesis flow. A read-only
inspection of the original project recovered its actual 13-file implementation
constraint order (9 EARLY, 2 board NORMAL, 2 LATE). The inventory builder records
scope and SHA256, excludes OOC-only files, and verifies board text against current
source, allowing newline differences. Fresh mapping must restore these exact
constraints before official board entries; it rejects missing scopes. No guessed
clock or timing budget substitutes for the original IP constraints.

The zero-state proof controls now include accepting disabled INIT-zero state and
rejecting arbitrary enabled D, INIT-one state, payload RAM, arbitrary output valid,
unknown INIT and falsely correlated LUT unknowns. These controls pass; real-netlist
proof remains pending until the mapping log explicitly certifies each lane.


Fresh mapping restored actual clocks (CPU3.333ns, fabric/UI4ns, UART/AON20ns) and
executed media/BSCAN entries. The first instruction FIFO passed zero-state induction
for all 36 functional FFs with arbitrary external and reset-release values. This
does not qualify the other lanes. The next disconnected valid output and an exact
management reset array-pin lookup blocked that run; fixes retain the full state
proof and use the already cached exact owner cell, with positive/negative controls.
Five renamed vendor references have unique ORIG_REF_NAME matches to real DDR
calibration MicroBlaze/LMB instances. Original XDCs are adapted to these exact
instances and their existing U0 children; hierarchy is not fabricated. See
`ip-scope-adaptation-evidence.json` and `validation-fresh-mapping-first.json`.
The following mapping run remains explicitly unqualified until all gates pass.

The next diagnostic passed management in both formal entries and proved the first
two inactive lanes. CommonCDC remained blocked at the third instruction lane,
whose emitted specialized module has no payload ports. The updated proof handles
absent payload ports only while retaining no-RAM, full INIT-zero state induction
and invariant-zero/unobserved valid requirements; live-state negative controls
still reject. Real-netlist acceptance of that update is pending.

Remaining coverage was 479 no-clock pins / 1179 internal endpoints, all in the
imported debug hub. The retained original routed-DCP XDC already declares that
exact USER1 BSCANE2 INTERNAL_TCK at50ns. `debug_hub_clock.tcl` restores that source
only after exact primitive/unique-chain ownership checks, without path exceptions.
Its provenance is in `debug-hub-clock-reference.json`; the following run is pending.
An intermediate explicit clock-contract check stopped at the top raw-UART alias;
the updated query checks actual connected net segments when the hierarchical pin
has no direct clock object. It never creates a substitute UART clock.
Diagnostic post_opt-entry execution does not imply opt_design has run.


Mapping r7 reached 24 clock objects, no_clock=0 and internal unconstrained=0.
The raw-UART top input is actually specialized to GND; UART50 is checked at its
functional uart/uart/clock endpoint, together with real AON50 and MIG UI250.
Three instruction lanes passed full zero-state induction. The next active
valid-only instruction response lane has no data ports/storage; a new absence
proof retains its complete Gray scopes and checks every remaining control FF.
That proof's positive/negative controls pass; mapping r8 is still diagnostic.

The old-netlist CDC report retains 23 Critical rows: 21 asynchronous reset
assertion rows (not yet formally signed off), and two quiesce launch-fanout rows
at the managed RX agent and always-running ingress. Their roles cannot simply
share a stopped-domain synchronizer. The source repair synchronizes quiesce once
in the running raw parent, feeds ingress directly, and retains two ordinary timed
managed-domain progress stages plus ACK. Default unrelated asynchronous agents
keep their original crossing. ACK remains high while stopped even if raw quiesce
clears; source/target reset and owner/drain behavior remain.

Production Scala compile, affected structural suites and native actual-component
cycle tests pass. The cycle fixture checks stopped ACK retention, raw activity wake,
64-cycle complete payload delay, two real managed request-progress edges, cold
reset while stopped, and a rejecting bad oracle. This is not full MAC traffic or
new-netlist CDC/STA acceptance. See validation-shared-quiesce.json. New production
RTL generation, MAC complete-form review and synthesis are still pending. The
preparation helper now binds its explicitly supplied commit to Git HEAD and can
reuse the existing fourth debug-hub DCP without regenerating IP.


Production RTL for source76c7d983 was regenerated (237 inputs), and its single new
synthesis/link run completed successfully with four unchanged IP DCPs. The complete
TX encoder and its parent instance are unchanged; the additional admitted complete
parent hash is bound to quiesce-mac-control-form-review.json, with mapped proofs
still required. A focused actual primitive census found the valid-only FIFO's
source-domain full_reg; the absence proof now includes that exact control flag,
with a wrong-clock negative control. No payload/Gray exception is weakened.

The explicit DIAGNOSTIC_IMPLEMENT_NO_BIT mode runs the real formal entries around
opt_design and then place/phys_opt/route only with zero no_clock/internal gaps,
complete reviewed scopes and runnable native implementation DRC. It preserves all
CDC reports and asynchronous IO/reset review status. Known asynchronous serial
pads retain positive explicit max-delay and direct two-stage structure checks;
unknown IO roles or nonzero clock coverage fail. Final board signoff and all reset
protocol review remain separate; no bit or download exists in this entry. This
new diagnostic mode is prepared and parser/negative controls pass, but its native
implementation run has not yet completed.


One batch inspected all26 Held lanes in the frozen new netlist:1944 real FF-driven
outputs,1111 genuinely unconnected outputs, and two scalar1-bit output registers.
The missing indexed output0 was an unconnected port, not a functional wiring gap
or a renamed active FF. The collector now records unconnected outputs, follows the
actual owned Q driver for live outputs (including scalar form), and preserves the
same per-bit RAM/source-clock/read-address proof and min-period payload budget.
Entirely nonobservable payloads additionally require no live source-data consumer,
no RAM/payload storage, and a complete local control-state census. Gray constraints
remain mandatory. Unknown storage/state/source-data consumers still reject.
All lane failures are now collected in one read-only pass, before any CDC exception
is applied, preventing one failed old name from hiding other lane discrepancies.
See held-output-mapping-evidence.json. Native implementation remains pending.
