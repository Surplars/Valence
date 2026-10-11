# Optional bound-store/prefetch profile v1

Status: **bounded compact combination qualified; explicit optional profile prepared for publication review**. B′ + B2 + read-prefetch store hold and the equivalent translated-proof compaction pass the focused gates, original Sv39, Bare and fixed-burst CPU checks below. The final complete old/new constructors pass, and all 293 native ON files exactly match the qualified compact export. The rollback OFF bridge preserves its three raw differences under a narrow declaration/expression proof. Nothing here promotes a default or claims mapped resources, STA, routing, or board operation.

The machine-readable [evidence index](../experiments/bound-store-prefetch-evidence-v1.json) records exact source hashes, immutable receipt hashes, actual Library recovery identities and archive-member bindings. Failed attempts remain in those recovery packages. The public source contains the final fixtures and independent oracles, not generated DUTs, objects, binaries, full images, traces, or historical run grants.

## Entry and rollback

Run the explicit, fixed optional entry from a checkout:

```sh
python fpga/next/board_bound_store_prefetch.py --output /tmp/bound-store-prefetch-native
python fpga/next/board_bound_store_prefetch.py --print-native-options
python -m unittest discover -s fpga/next -p 'test_board_*.py'
```

The first command performs source-only preflight and does not create the output directory. `--emit` requests official native export only. It is a separate, resource-consuming stage, not physical qualification. No arbitrary geometry, perimeter or feature override is accepted by this entry.

The complete `board_pmp_publication.py` profile is preserved in its original order, including tri-speed Ethernet, JTAG USER chain 2, RAM/peripherals and service geometry. The only appended arguments are:

```text
--frozen-store-proof-transport
--pending-virtual-store-proof
--pending-virtual-store-proof-slots=1
--bound-head-store-overlap
--read-prefetch-store-hold
```

These select four Boolean policies and one proof slot. Effective geometry is issue 2, ROB16, PRF48, LSU4, DTLB16 and PMP16. The full constructor has 53 profile, 148 core and 17 cache fields; ROB/PRF overrides remain `null` while their effective core capacities remain 16/48. The complete object is pinned independently to an executed historical constructor, not inferred from these five flags.

All generic constructors and old entries retain false policy defaults and one proof slot. The private compact transport representation adds no CLI flag or constructor field. Rollback is `fpga/next/board_pmp_publication.py` at published commit `7cc549ce32eac03a59adbf1ae388bf9dbae1ff25`, tree `82adf9aacea6f83603a88c4cb66a5341cfa3bbc6`. Existing serialized preset/profile bytes and native argument lists remain unchanged. Old complete constructor comparators explicitly require the added false fields and retain whole-object equality, including unknown-field rejection. Missing fields, unexpectedly true fields and wrong/missing slot counts are tested. Constructor-only input rejects unknown options, duplicates and valued Boolean forms.

## Invariants

B′ reserves a pending-store proof row before the hit-only write query. The independently validated result must match the complete live owner token, authorization epoch, VA, PA, size and mask. Same-edge clear/consume wins. A bound proof is not lost because store data becomes ready or a younger load dies. The exact frozen PA transfers at the real protected head-store LSU start; kill removes only the killed owner. No query result changes canonical-store ownership, actual request acceptance, late response/error handling, forwarding, serial drain or ordered retirement.

Only stores older than the currently selected load can justify bypass. Every such store needs canonical authority or an exact pending proof, and physical byte intervals must be disjoint. One global early-load credit moves through reserved and started states and returns only after its complete original owner has drained. Readiness gates new offers; it does not revoke a committed held offer or an accepted response obligation.

B2 lets an exact bound ordinary virtual head store use an actually idle LSU slot while all pre-edge busy co-owners are parallel, noncancelled, successfully prechecked ordinary virtual RAM loads. Their saved epochs agree and complete PA byte intervals are disjoint. Request, response and done owners, including error completions, remain checked. A completing slot is not an idle target on this branch. The store remains serial; new starts wait for its actual checked callback under the existing canonical-owner rule. Real decoded recovery suppresses new starts and preserves accepted-read drain. Saved index inequality is valid only under this integration lifetime invariant; a forged stale standalone token is not presented as legal CPU traffic.

Store hold retains only a read-origin prefetch candidate suppressed solely by an actually accepted ordinary legacy-hit store. Its existing finite countdown continues. It does not allocate on that edge, change write priority, broaden the other 17 gates, or admit posted/fallback/nonlegacy/held-demand/maintenance exceptions. The isolated hold change adds no register, memory or port declarations.

Compaction replaces the redundant full proof stored in the translated queue with a private checked-valid witness. The complete input proof is validated before acceptance; full owner token, epoch and PA remain available through the unchanged request/context path. Final PMP and physical checks remain. Reconstructed proof outputs preserve exact public ready/valid/payload behavior. Invalid payload is poisoned by the independent host and never treated as authority.

The test-only `TranslatedFrozenProofReference.scala` is frozen from the qualified `82c6dce` adapter. Its provenance and exact SHA are in `simulator/gsim/bound_store_prefetch/frozen-reference-v1.json`: one leading comment and five class-name prefixes are the only transformation. Do not regenerate it from the current DUT. The selected final B2 bank/transport source prefix is byte-identical to the compact focused run; its backend-only fixes remain preserved.

## Measured scope

The compact combination reproduces the uncompressed combination byte-for-byte in complete stdout, all 105 fields, full AXI and supply traces, ledgers, final bytes and replies for all three CPU cases. The rows below therefore apply to both, using the identical workload and stated service law. Inclusive cycles include clean tail. Throughput gain is baseline inclusive cycles divided by candidate inclusive cycles minus one; it is not the same percentage as cycle reduction.

| Configuration | Service/workload | ROI | Tail | Inclusive |
|---|---|---:|---:|---:|
| Published7cc | Original Sv39 | 250604 | 8187 | 258791 |
| B′ | Original Sv39 | 259554 | 8185 | 267739 |
| B2 | Original Sv39 | 297042 | 8030 | 305072 |
| B′ + B2 + hold | Original Sv39 | 247034 | 8189 | 255223 |
| Published7cc and combination | Original Bare | 251815 | 8053 | 259868 |
| Published7cc | Fixed-burst Sv39 | 250170 | 8188 | 258358 |
| B′ + B2 + hold | Fixed-burst Sv39 | 243398 | 8190 | 251588 |
| Published7cc + hold only | Original Sv39 | 250604 | 8187 | 258791 |

The original-law bandwidth figures below use the profile's nominal 100 MHz to
convert simulated cycles, not a measured board clock or timing closure:

| Original Sv39 metric | Published7cc | Compact combination |
|---|---:|---:|
| ROI payload MiB/s | 49.879491 | 50.600322 |
| Including clean tail, payload MiB/s | 48.301525 | 48.976777 |
| Accepted R beats / ROI cycles | 13.101148% | 13.290478% |
| Accepted W beats / ROI cycles | 6.537805% | 6.632285% |
| ROI AR / R / AW / W events | 4160 / 32832 / 2048 / 16384 | 4160 / 32832 / 2048 / 16384 |

The beat fractions include cache-line and page-table traffic and are not effective
payload utilization. Accepted traffic does not increase. These compare the final
combination directly with published7cc; improvements from different generations
are not multiplied together. The fixed-burst law remains a separate experiment.

Original-law inclusive throughput improves by 1.397993%, with 1.378719% fewer cycles than published7cc. Hold removes 49,849 inclusive cycles relative to the negative B2 experiment. Fixed-burst throughput improves by 2.690907%, with 2.620395% fewer cycles. Bare is unchanged. Hold alone on published7cc has byte-exact stdout, full AXI and full supply traces and zero cycle benefit. This newer isolation result supersedes the older follow-on summary's “isolation not run” sentence. No general workload speedup is claimed.

The CPU receipt's top-level `PASS_NEGATIVES_ONLY` describes its final stage. Its stage map and paired summaries separately establish the original Sv39 run, three read/memory/trap corruption controls, Bare, and the second service law. The fixed-burst comparison uses its top-level paired result, not the original-law references embedded inside that receipt. No third service law, NEMU-wide ISA qualification or long OS simulation is claimed.

## Independent coverage and corrected failures

- B′ bank1/bank2 each passed separate ASan and UBSan, with complete-tag and double-reserve controls. Real decoded backend OFF/ON and frozen transport cover data, retirement, token identity, malformed masks, atomics, actual physical errors and legal drains. Two proof slots are component coverage, not this board default.
- B2 retains the genuine B′ ON1 OLD model, new actual LSU slot controls and real decoded NEW backend, with full owner/epoch/PA interval checks, idle-target checks, ordered load/store errors and genuine branch recovery. Synthetic trusted qualifier boundaries remain distinct from real ROB ownership.
- Hold has 12 schedules in each OFF/ON mode, 24 exact 128 KiB final images and actual hold-NEXT mutation rejection. Extras add denied/corrupt/probe-flush schedules on exact ON64 objects plus real test-only 2-bit generation exhaustion, fallback and nonposted mutation controls. The board generation capacity is unchanged.
- Compact focused parity has 24 required terminal command passes, 89 requests, 79 physical transactions, 10 ordered faults, 60 certificates and 19 delayed translations. It covers sizes 1/2/4/8, PA above 32 bits, FIFO/backpressure, mixed physical/prechecked/nonfrozen traffic, stale/canonical faults, legal drained context changes, malformed shapes and in-flight context assertion controls. The original real-translation/StoreBuffer transport and token/mask/atomic negatives also pass. The separate whole-CPU parity gate also passes all three cases. The original-law read/memory/trap corruption controls retain their original nonzero exits and rejection anchors.

Earlier fixture failures are retained, not relabelled as passes. B′ fixes corrected the BoringUtils vector probe, legal decoded recovery and response-FIRE accounting. B2 fixes corrected OLD completion/replacement versus co-ownership, local redirect observation and generated vector getter limitations. Hold fixes corrected prerequisites, uncached read mask, held-store flush image timing, posted-proof stability, real backing-error premises and fallback getters. Compact host recoveries corrected an expectation that an offered upstream response had already handshaken downstream. Production remained unchanged through those compact host-only repairs. A fixed-burst postprocessor initially requested a nonexistent stdout record; its correction used the already byte-equal raw trace, without another host link or DUT run. Exact failure receipts and terminal ancestry appear in the evidence index.

## Native declarations and physical limits

For the uncompressed combination, official native output retains 2,858 more declaration bits than exact7cc: 1,178 scalar register bits and 1,680 array bits. The original FIR difference of 4,399 bits reconciles as minus 1,269 assertion-history bits, minus 280 constant FP-proof bits and plus eight retained integer control bits. These are generated declaration counts, not mapped FF/LUT/BRAM usage.

The compact translated queue saves exactly 1,112 array bits with zero scalar-register change. The resulting native increment over published7cc is **1,746 declaration bits: 1,178 scalar + 568 array**. Native ON is byte-identical across all 293 files to the compact qualified export.

Rollback OFF is byte-identical in 287 of 290 files. Its preserved raw FAIL and exact diffs identify two unchanged continuous-wire declaration moves in IntegerBackend, one collision-free temporary rename in ParallelLoadStoreUnit, and three temporary renames plus one scalar bitwise-AND operand move in the cache. A separate token/assignment-tree certificate permits only those exact changes; every other token must match. Four substantive logic mutations are rejected. This proves the stated default-disabled semantic boundary; it does not call the old generated output byte-identical.

Timing remains unmeasured. B2 adds saved-owner, full-PA interval and epoch comparisons to admission selection; pending proof selection and existing rank/age qualification also contribute combinational work. A smaller retained-state count does not establish a low LUT cost or a short critical path. There is no synthesis, STA, placement/routing, bitstream or board result for this assembled source.

## Replaying from an independent checkout

The source-only board preflight and Python tests above need no historical recovery workspace. Component and CPU runners accept explicit current source, tool and output paths. They create fresh contracts binding current source and tools. A missing or mismatched input fails before model generation; old run grants are evidence, never continuing authorization.

The CPU replay uses the exact existing 17-file `prefetch_demand_adoption/cpu_snapshot` host source by digest. It does not duplicate that snapshot. The three `bound_store_prefetch/burst_locked` files provide the fixed service-law header and independent unlock/held-data/last-release controls. Original assembly and linker sources stay in their existing locations; generated guest binaries must be rebuilt or supplied from a digest-bound artifact, not silently copied from an old workspace.

For the compact/reference adapter and original transport pair, use the existing
sequential stages with explicit tool inputs:

```sh
python simulator/gsim/translated_frozen_proof.py freeze --output /tmp/compact-pair --toolchain-root /path/to/tools --preflight-only
# After reviewing the preflight, run freeze, config, emit, generate, sanitized in order.
```

The wrapper verifies the immutable qualified reference before running tools. Its
16 compact negative controls and the three original transport controls retain
nonzero-exit and specific-anchor requirements.

Use each runner's `--help` and the CPU runner's `--list-required` to obtain explicit input requirements. Download recovery files by the actual Library identities in the evidence index, verify archive SHA-256 before unpacking, and pass extracted artifact roots explicitly. Private Library access is required for those immutable historical artifacts; the IDs are not anonymous public URLs. A checkout without them fails with a precise request rather than accepting an unknown model. Fresh staged component-model builds are the supported portable path; B′/B2 object relinking is deliberately unavailable without a separately reviewed compiler-dependency closure. Hold model reuse requires its explicit digest-bound closure, including compiler dependencies and a closed generated-file inventory. Public replay preparation is not a claim that a new clean-checkout DUT run has been executed.
