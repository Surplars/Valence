# Experimental A1 telemetry physical coverage

This is a source-level constraint candidate, not mapped or routed validation.
The frozen I1 image and its delivered receipts are unchanged.

`valence_performance_telemetry_constraints hier 3.0` retains the default I1
contract of exactly sixteen 32-bit Gray banks. Explicit third argument
`a1-experimental` requires those same banks plus exactly the 32 retained bits of
`cpuRetireLane1/graySync0_1_reg[0..31]`. The common wrapper accepts the explicit
`valence(telemetry_physical_profile)=a1-experimental` selection; no emission or
board profile enables it automatically. Missing, extra, duplicate, wrong-bank,
or wrong-bit cells reject before constraints are added. The register bridge,
3 ns datapath-only max delay and bus skew budgets are unchanged. No clock
relationships or false paths are added by this Gray helper.

The additional counter bank also instantiates another source-reset synchronizer.
Its unused counters are synthesis-pruned, so its retained functional reset loads
must be obtained from the actual mapped graph, not inferred as 519 or 65 cells.
The existing `monitor_reset_entry` helper now explicitly refuses a graph with
`cpuRetireLane1` registers. Its I1 proof still covers exactly six PRE endpoints,
1038 functional CLR endpoints and four interstage D endpoints. No A1 PRE
exception is implemented or authorized by this patch. A future mapped census
must prove the third chain, polarity, clocks, exact final loads and all retained
functional/interstage timing before a separately reviewed extension.

Focused Tcl mocks exercise default I1 and explicit A1 Gray coverage and malformed
census rejection before mutation; they do not establish Vivado API behavior,
metastability margins, implementation runtime or timing closure. Actual A1
synthesis may retain a different naming/merging shape and must fail closed rather
than be admitted by loosening the census.
