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
