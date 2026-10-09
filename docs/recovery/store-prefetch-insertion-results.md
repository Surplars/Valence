# Store-origin prefetch MRU insertion: measured default-OFF candidate

## Result

Fresh source-bound OFF/ON CPU models change only `--store-prefetch-mru-insertion`. Both enable D16/I8/PTE4, virtual-RAM load precheck, checked-store next-line prefetch, prepared-store lookahead, LSU4, physical ingress, older-retire prefix, previous-packet fetch and DMA4 idle. Existing physical posted-store merge/WB implementations are absent from the recovered baseline. Both runs execute the exact same formal 1472-byte supervisor kernel and immutable 6104-byte guest.

| Sv39-4K 128-KiB case | MRU OFF ticks | MRU ON ticks | Throughput change | Flush OFF / ON |
|---|---:|---:|---:|---:|
| WRITE20 | 207483 | 207483 | 0% | 10681 / 10681 |
| COPY21 | 633266 | 497148 | +27.3798% | 5636 / 5574 |

COPY saves 136118 kernel cycles; kernel plus flush throughput improves 27.0885%. No favourable performance threshold is part of acceptance.

### Actual COPY mechanism and traffic

- Store-origin allocation: 2015 / 2015; useful: 0 / 2015. Read-origin allocation/useful remain zero.
- Actual full-PA/index PF install followed by matching A-demand eviction before use: 2015 / 0.
- ON has 1763 later observed evictions, all after the PF line was used. Probe/error count is zero in this ROI. The separate chronological next-B-store counters do not prove direct causation across intervening refills.
- AXI read requests: 6176 / 4161. Accepted R beats: 48963 / 32843. This removes exactly 2015 complete eight-beat line reads; declared beats are 48960 / 32840, reflecting outstanding reads across ROI boundaries.
- AXI write requests: 2049 / 2049; accepted W beats: 16392 / 16392. Flush write requests/beats remain 256 / 2048. PF release-owner occupancy is 6082 cycles on both sides. The fixture does not claim full-CPU C-channel beat attribution.
- WRITE origin counts and all ROI traffic are identical: candidate2047, allocated/useful2015, AR2081/R16424, AW2048/W16384.

Demand replacement is invalid-first then LRU. The preference for clean victims belongs to prefetch allocation. The confirmed defect addressed here is inserting a successful store-origin prefetch as LRU, allowing the next source-line demand to evict it before the destination store uses it.

## Policy and preserved responsibilities

`storePrefetchMruInsertion` is independently default OFF and requires checked-store prefetch. Only a successful refill with captured per-MSHR store origin inserts MRU. Read-origin prefetch remains LRU; demand fills/hits retain their prior replacement updates. Error fills do not touch replacement. No new request/response/permission/admission/drain/exception or coherence behaviour is introduced. Ways1 is legal and has no replacement metadata; default-OFF legal capacities1/2/4 remain elaborated, while prefetch retains its existing minimum two MSHRs.

## Fresh gates

- Scala: two configuration suites and 38 actual capacity elaborations; selector eight checks.
- Independent host replacement/origin oracle: 472 checks and five hostile mutations, ASan/UBSan.
- Actual MixedCoherentLineHome/AXI cache gate: six scenarios on each policy and four negative controls per side. The original dirty victim, backpressure, late ReleaseAck, MSHR-reuse/stale-owner ABA, refill error, probe/DMA and flush checks remain. New store-origin conflict checks full PA, actual victim, dirty C and later store hit; read-origin LRU is checked independently.
- Native OFF/ON: exactly two additional scalar bits in `NonBlockingCoherentLineCache`, retaining the two captured store-origin bits for functionality. Array state and all fixed-RAM geometry/port helpers are unchanged; no verification assertions/shadows are counted. This is a native declaration/reachable-state proxy, not mapped FPGA area/timing.
- Fresh whole-CPU OFF/ON models each pass the original RV64GC/32FPR/FCSR/Sv39 ECALL/compressed/DDR smoke and a corrupted-anchor negative, 33370 cycles each.
- Every WRITE/COPY singleton completes independent verification of both 16384-word buffers, three ordered initial faults, one S ECALL, exact accepted ROI/terminal markers, two consecutive all-owner drain checks and an executed trap-order negative. The runner strictly binds all 1954 tracked source files, exact tools/argv, generated artifacts/objects, header ABI, model geometry and four terminal model/smoke receipts.

## Identities and reproducibility

Functional commit: `0d17c8d00b56ef698c5d3c71353beebc612ef5ca` (seven files). Qualified source including cache tests/passive observations: `6d7a79c2f5095157d65943ff13ed756ee3d10923`; src/main tree `80a8a05d3a167825a98b240661610c70ac6202de`. The qualification tree remains clean and unmodified. This report is a later external documentation artifact, not a change to the tested source inventory.

Actual directories under recovery-20261009-1816:
- `store-prefetch-insertion-candidate/build/gsim/store-prefetch-insertion-r1/receipt.json`: `18765e5fc6aa00e3c00e9fdb90ca040a14f164e5abe0b0707160fdc4de652e85`
- `store-prefetch-insertion-native-r1/comparison.json`: `080221e5320da85a0e7275a5e373da1d520f35e2a975a83259e96e56ead5222c`
- `store-prefetch-insertion-board-r1/model-OFF/receipt.json`: `dcdd3808f021c1cc640f2649f56cd67b291e96fb73d446c96b393e9f0aedd950`
- `store-prefetch-insertion-board-r1/model-ON/receipt.json`: `5d401331aeb7d31b9d5739d591626f37fa843a341a3a0a25a46a775cdf3f9089`
- `formal-store-pf-mru-replay-prep-r1/pins.json`: `28dacb0908a07616a7f2ae86db9338d252335de2d5bcded8d002d98bf32570c2`
- WRITE pair: `1583f72ea4c56c85279bc2e19851c01e676aa971ea14a2f31b9b500cf3e04ee5`
- COPY pair: `80702c16a75b58d8b0abc7d1af444fca5d90072144e3df643bae7d25ff3b127b`

The raw strict replay and native runners are preserved with their execution paths and original source hashes in the evidence archives. They are execution-bound snapshots; copying them to a different tree does not create new qualification. A new integrated source needs new source bindings and fresh applicable gates. No old lost-volume PASS, old6a26 full54 result or historical FPGA result is inherited.

Persistent evidence IDs:
- Complete6d7a source bundle: libfile_1fb153156734819187cba657385168ad
- Cache models/gate: libfile_1bb7c95ece4881918b6c4c554f6c6418
- Native outputs/census: libfile_6c7b0816fc7c8191b3451bf75ed57d35
- Formal source preparation: libfile_398b9137de608191bf9f5bbe1ccfe63b
- Complete fresh CPU models/GC: libfile_14d0cc0727488191b69af0887269f916
- WRITE raw results/hosts: libfile_61f3bf1a4dfc8191b1446d7271fdee46
- COPY raw results/hosts: libfile_6ecce36172f08191a3db2c5c30cad4be

## Integration boundary

Apply only the functional0d17 commit to delivery6a26. Copy the new StorePrefetchInsertionSpec and six files under simulator/gsim/store_prefetch_insertion. CoherentCacheHomeGsim needs only its MRU constructor/config argument and the new StorePrefetchInsertionGsimMain. The 81-line passive observation delta is already present in delivery6a26 and must not be reapplied. Keep the old qualified full54 tree immutable. Board timing, actual FPGA bandwidth, Linux workloads, integrated MRU IRQ/DMA and broad ISA regressions are separate qualifications.
