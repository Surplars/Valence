# Younger store preparation prematurely sealed actual posted owners

The original DMA4 model source `8f9d08a` passed functional qualification but its
unchanged Bare WRITE18 guest took 268913 ROI cycles versus OFF's 215756. The ON
owner trace contained 2048 owners: one with three members, 2047 with one. This
is a negative performance result, not an optimization qualification. Owner
admissions (2050) are not the total number of proof-bearing CPU stores: resident
hits use the ordinary cache path without allocating posted owners.

## Actual edge evidence

The independent passive diagnostic reuses that exact original ON native object,
guest bytes, DDR timing and every original host oracle. Its only host changes
are a passive class, an instance and one sample call. Removing those additions
recovers the exact original host bytes. The entire original guest completed,
all parsed metrics/results matched the original run field-for-field, and the
original precise trap negative still rejected as expected. No RTL was changed.

Receipt: `posted-board-seal-diagnostic-r1/output/receipt.json`, SHA256
`dc6e02b222f7a2a4dfc2d3066a398a4760c2631cbb41d19e287ef149900789c5`.
Terminal status: `PASS_ORIGINAL_ON18_UNCHANGED_WITH_PASSIVE_SEAL_TRACE`.
The 800 pre-edge ROI observations in `positive-seal-edges.jsonl` have SHA256
`4347a3ab96c1cbbb6f94129862808b91f6e0ca171059def098513acf52e9eff2`.

At cycle918117, live owner7208 has sealedRun=0. The ROB head is index2/tag257051
(ordinary ALU); the selected staged store is index3/tag257052. The store is
S-mode Bare (privilege1, SATP0), physical, aligned and PMP-allowed. It is not
head, so postedEligible=0 and startValid=0, but seal=1. Recovery, recovering,
interrupt, system and context boundary causes are absent. At918118 the same
full-token store is head and actually launches with proof, but the owner's
sealedRun is already1. Its actual checked cache proof offer is held from918121
through installation at918199 and the remaining owner drain.

The second line has the same causal sequence: new owner7209 is accepted at
918224; at918225 it is live/unsealed while the prepared young store257082
asserts seal. At918226 that store becomes head and launches, with the owner
already sealed. Its proof-bearing cache request is held from918229 through
918325; ready becomes1 only at918326 after release.

The old source connects preparation to ordering: IntegerBackend's lookahead
selector permits prepared younger physical stores when the ordinary candidate
pool is empty (656–668); memoryChoice validity checks pending/full token
(740–743), while postedEligible also requires ROB head (839–842). The old seal
term was simply memoryChoice.valid && !postedEligible. This sealed a live line
before the candidate had authority to launch. PostedStoreMerge's join predicate
rejects current or latched seal (139–141,215), and its sameLine check prevents a
second simultaneous allocation (136,161). The held store then becomes a
resident hit after install/release.

SB local acceptance and the checked FIFO are not the initial blocker: buffered
writes retain early local ACK; the checked gate permits a saved valid proof
despite external posted busy. The passive trace shows the stalled valid proof
at the real cache boundary. Bare-S has no M-only posted permission restriction:
actual head, natural alignment, guaranteed RAM and current PMP are checked.

## Narrow candidate correction and explicit negative cases

The candidate suppresses only that preparation-induced seal when all of the
following hold: prepared-store lookahead enabled, valid staged full-token
selection, non-head index, saved prepared store, matching token index, ordinary
physical naturally aligned guaranteed RAM integer store, non-atomic and current
PMP permission. This is a preparation classification, not authority: original
postedEligible, head authorization, proof creation and launch gates are unchanged.
The expression exists only inside the optional posted interface foreach.

Young loads, virtual stores, IO/out-of-range stores, atomics, denied or unaligned
stores, unprepared stores and index mismatches still cause the original seal.
Head nonposted candidates still seal. A stale full token cannot make the existing
memoryChoice.valid true. All recovery, interrupt, context and system conditions
retain their original unconditional effect. The host truth-table contract tests
these cases; it is not an executed RTL qualification.

The actual directed CPU/cache regression now passed on the fresh corrected
models, as recorded below. Original-guest WRITE and COPY performance is now recorded separately in
[the benchmark result](posted-store-seal-performance.md).

## Independent remaining prefetch cost

The original WRITE18 OFF run allocated2015 store prefetches, all useful; ON
allocated zero, with identical total R/W traffic. Cache episodeActive explicitly
disables new prefetch creation/allocation, and the entire ON ROI retained one
cohort7208. This is a separate designed mutual exclusion. Fixing preparation
seals alone does not establish a performance improvement or remove that cost.

## Executed correction qualification

The production correction is commit
`0658f2d4a543ba5849498af626eec0a248363540`, tree
`cc1d50b223fc0b6ebec448292ce8964986b56af2`. Both OFF and ON were freshly
elaborated, generated and compiled with the same pinned toolchain. ON model
session43936 and OFF session85952 both exited0. The only changed production
file relative to the qualified original pair is IntegerBackend.scala; cache,
owner, proof transport, translation and all parameter fields remain unchanged.

An attempted OFF object-reuse gate was rejected by its strict complete-FIR
comparison. Its sole remaining difference after source-locator removal was
the built-in assertion message's literal line number, 1985 becoming2000.
The comparison did not erase assertion strings or loosen its rule. The failed
receipt and normalized diff were preserved, and OFF was freshly compiled.
No old OFF execution is described as a new-source execution.

The identical directed guest/host/oracle change was applied to separate old
and corrected host trees:

- Old host `350026c899d4842e9a57da020e9e2510b904c8f8`, tree
  `33821d75681e502bbe35b4f88343148e7d08953d`, using original8f9 models.
- Corrected host `4bf50c7ba539590268b74ef28474a96dbb2da878`, tree
  `7d4cf4aba8424b314659a29f94e8c0220e652520`, using fresh0658 models.

The 249-instruction guest executes41 stores and6 loads. It preserves the
qualified dirty-victim/held-B/ordinary-load/FENCE.I prelude and adds four cold,
nonadjacent cache lines. Each line receives eight distinct naturally aligned
stores separated by actual ADDI and untaken BNE instructions. All expected
instructions, addresses, bytes and per-line store PCs are independently decoded.
The fixed witness requires at least two full-token members on every line before
that original owner's actual installation; it also reports all-eight membership.
Ordinary load/system instructions are kept beyond the ROB during store admission.

The old source completed all final-byte and owner-drain checks, then failed
exactly at `DIRECTED_SEAL_WITNESS_REJECT`: its four member counts were1/8/8/8.
This expected failure cannot be hidden by successful merging on another line.
The old model's OFF/old-only positive runs and precise token/byte controls passed.

The corrected source passed all five cases in session80457, with member counts
8/8/8/8. Every directed store retired, every original owner installed/released,
and the directed ordinary-head sealed-cycle counters were zero. ON still
exercised the real256-cycle B delay, blocked ordinary load (311 cycles), 30 ROB
reuse witnesses and15 retirements while the original write was pending.
These functional delays are not performance measurements.

All six old/corrected OFF/old-only/ON executions have identical guest and full
initial/final memory snapshots, including the old ON run rejected for coverage.
Guest SHA256 is
`f08075097a1c643996e4ee30e4e24496431d9e7544c8900cfcfbf3e5daa2bcff`;
final sparse DDR SHA256 is
`5da92d7e8a1e07fc41a917a13cc354fcf579939cdafb975a2357383cb0321af3`.

| Evidence | Receipt SHA256 |
|---|---|
| Fresh ON model, PASS_MODEL_SIDE | `e6e3b534a42c91341c22d6c034bda42150b66059ab3837b1692113a5c2213b53` |
| Rejected OFF reuse attempt, FAIL | `320bd70c81e73eb1faa7761142c54984f2d7874f7d995b8cc4b23132f8e96b87` |
| Fresh OFF model, PASS_MODEL_SIDE | `f0e108a686d00e5c6e147f8ac03c76218c21fa4f7462fb36f21a5158edf8b603` |
| Old directed gate, intended ON coverage FAIL | `42ba67c96f9479627e945b30510b97ea183e6e4da4ae012a85675710b27c01e1` |
| Corrected directed gate, PASS_REAL_BOARD_FUNCTIONAL_ONLY | `3671b380672d2f38c19bb8ea53bb508c4cab34153fdccd4dc6c56618e9445ea4` |
| Corrected actual-instance audit, PASS_ACTUAL_FINAL_PARAMETERS_SAME_GRAPH | `8716ad2259270788ba4f769b11bc9cf9ea638eb3fa26ec93a50589503b0e3938` |

The actual-instance audit in session60635 reads the same six final core objects,
both DDR configurations, three concurrency objects and actual cache TileLink
parameters. Both audit FIR files are byte-for-byte identical to the corresponding
fresh model FIR files, including source locators. The complete profile still has
DMA4/LSU4/D16/I8/PTE4 and both request/return-flow experiments OFF.

The corrected seal does not create proof, authorize a young store, alter virtual
fault handling or change the head/PMP/launch checks. Loads, virtual/IO/atomic or
unsafe store candidates and all original recovery/context/system/interrupt
causes retain their original sealing behavior. The directed physical-store
composition is the executed correction witness; separate broader CPU/context
qualifications keep their recorded scope. No original benchmark bytes were edited.
