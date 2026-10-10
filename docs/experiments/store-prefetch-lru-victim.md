# Store-origin prefetch LRU victim experiment

Current integration status and exact opt-in commands: [source checkpoint](frontier-lru-opt-in.md). Initial-checkpoint statements below retain their historical scope.

This independent default-OFF experiment changes a captured store-origin prefetch candidate to invalid-first, then ordinary two-way LRU replacement. Read-origin prefetch retains clean-first selection and clean-only admission. The selected set always comes from `candidateAddress`; no upstream request index is reused. Existing permission, candidate lifetime/cancellation, MSHR, dirty release, held acknowledgement, probe and flush responsibilities remain in force.

The motivating CPU trace has 672 repeated ordinary source-line reads after store-origin prefetch selects the newly fetched clean source instead of the dirty LRU destination. This policy changes victim choice without adding a line-residency CAM. It may increase dirty writebacks or useless-prefetch cost. Source-level plausibility is not performance qualification.

`CoherentCacheConcurrency.storePrefetchLruVictim` and `FpgaNextConfig.storePrefetchLruVictim` default to false and require `storeNextLinePrefetch`. Both native and board command lines accept `--store-prefetch-lru-victim`. No recommended preset enables it. The full Scala reports include the new Boolean on both sides; native exporter preflight preserves historical omitted-option profile bytes and adds the experimental field when enabled.

Pure checks:

- `python3 -B simulator/gsim/test_store_prefetch_lru_victim_cli.py`
- `mill -i IonSoC.test.testOnly ooo.StorePrefetchLruVictimConfigSpec`
- `mill -i IonSoC.test.runMain ooo.StorePrefetchLruVictimProfileMain <fresh-directory> off|on`

`ooo.StorePrefetchLruVictimNativeMain` audits the actual native constructors and emits a single native model. Its OFF/ON pair retains the reviewed ROB64/PRF64/LSU4, 139-field core with memory-proof frontier ON; only this new cache policy differs. The three actual cache constructors must report all 11 fields (the 10 original fields plus the new policy Boolean), and six core plus two DDR records must remain identical.

At the first source checkpoint, Scala compilation, actual replacement/writeback tests, CPU performance and native/resource/timing results are **unqualified**. Required directed tests use the real qualified cache/home protocol: dirty LRU old line and clean MRU new source, both way placements, original clean-first reload versus LRU seven-word hits, full eight-beat dirty release and held acknowledgement, read-origin unchanged behavior, invalid ways, WRITE dirty streams, error/probe/flush, same-edge owner reuse and one-way behavior. Preserve original CPU programs and full data/retirement oracles; report primary ROI, drain tail and read/write traffic separately.
