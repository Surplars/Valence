# R38: use the completed CPU release for distribution PRE

R37 improved CPU setup from -2.619 to -1.709 ns and retained zero hold failures,
but exposed a new reset path. The immutable report ZIP has SHA256
`a2a87934fe2b0207029756abfabffece1bf604b91a1b414f8c76871d0a8c979c`.
`started_reg/C` (fabric250) reaches a distribution replica PRE (CPU300) through
one LUT2 and a reset net with 242 loads. Recovery is -2.891 ns, requirement
0.667 ns, data 2.491 ns, skew +0.171 ns and uncertainty 1.171 ns. The 242 loads
are not evidence that there are exactly 242 distribution FFs.

The R37 driver used raw `startupReset` at PRE and the completed three-stage
`cpuRelease` at D. Replication improved the original functional reset fanout,
but also replicated this raw cross-domain PRE endpoint. It must not be swept
into the twelve independently proved gate-reset entrance exceptions.

## Minimal source correction

`ResetDistributionDriver` now has only a CPU clock and the completed local
`synchronizedReset`. The ordinary FF has D=0, PRE=`synchronizedReset`, INIT=1.
Its raw `asyncReset` input is removed, including both platform and test wiring.
The full original three-stage ASYNC_REG chain is unchanged; the new driver is
still not ASYNC_REG, so physical replication remains legal.

Cold assertion propagates asynchronously through the original chain's final
Q and then the distribution PRE, without requiring any CPU edge. Following
deassertion, the original chain releases after edge three, and the distribution
FF releases at edge four. CPU state can first run at edge five, as in R37.
Normal DFS never asserts this cold-reset chain and must retain accepted owners.

Both the final synchronizer Q to each distribution PRE and every distribution
Q to functional CLR remain real timed recovery/removal paths. No new false
path, multicycle constraint, relaxed target, or reset-stage bypass is added.
The fanout moves to the completed local release Q, so timing improvement is a
candidate, not a guarantee. Mapped copies must meet timing to release together.

## Remaining measured physical issue

R37 still has a functional distribution recovery path of -0.642 ns, from
`distributed_reg_replica/C` to the arithmetic adder's `magnitudeValid_reg/CLR`.
Its net has fanout250 and 3.381 ns routing, from SLICE_X106Y130 to X7Y301.
This is better than R36's -1.564 ns functional reset path but not passing.
Changing the upstream PRE does not by itself prove this distant branch fixed.

## Short checks and mapped ECO boundary

Incremental compile and real reset-fixture emission pass. Icarus passes 456
checks across 12 stopped-clock/phase rounds, including an accepted owner during
normal DFS and a subsequent real cold-reset assertion, clear and four-edge
release. Early release and lost-owner observation negatives are rejected by
the ordinary oracle. The emitted driver explicitly has D=0 and only the local
release on its asynchronous control. No full-SoC resimulation is claimed.

An existing routed-netlist ECO is possible in principle without adding FFs:
after an actual census proves every distribution copy has identical original
D/PRE semantics, preserve C/CE/INIT/LOC/BEL/Q and change only D to ground and
PRE to the existing completed local-release net. Source semantics must match
that exact FDPE transformation. Preserve the original checkpoint, prove the
full three-stage source and all copy pin maps before any mutation, recheck all
Q consumers and unchanged properties afterwards, and reroute only affected
reset connectivity while preserving other routing. The normal complete STA,
including recovery/removal and all hold paths, remains required.

No ECO has been applied or qualified by this source change. Native object
evidence, an independently reviewed bounded mutation and post-route results
are prerequisites; an unsupported topology stops the ECO instead of guessing.
