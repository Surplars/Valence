# Default-OFF distinct-way C-before-E release

`distinctWayRelease` / `--distinct-way-release` lets an ordinary read reserve the
other cache way beside one already-issued checked-store prefetch. A dirty victim
can complete its C burst before that prefetch's E. Same-set A remains serialized
through E. The original offered-C priority, clean Release ordering, posted
live/intent exclusion and DDR host AW/pending-R fence remain in place.

The option remains false in every default and recommended preset. Both independent
memory-resource options, `reconstructIssueTokenIndex` and
`sharedMemoryAddressState`, also remain false. This experiment does not qualify a
joint resource-ON/release-ON executing CPU or promote a new preset.

## Executing CPU results

The original Bare case 19 ran fresh OFF and ON on the same frozen candidate source,
with the original guest, exact reviewed profile and original workload boundaries.
These are kernel cycles and a separately reported flush tail:

| Original workload | Release OFF | Release ON | Result |
| --- | ---: | ---: | --- |
| Bare case 19, 128 KiB COPY | 380,840 / 5,572 | 334,071 / 5,558 | 46,769 fewer kernel cycles (12.280485%); 13.999719% higher payload/cycle |
| Original Sv39 case 21 | Historical 345,578 / 5,565 | Fresh 345,578 / 5,565 | No change; exact original raw streams and stdout |

Case 19's ON raw data differs and passed all original parsers, primary checks and
newly executed trap-negative control. Fresh OFF case 19 and fresh ON case 21 each
have all 18 original raw sidecars and both stdout logs byte-identical to their
pinned historical case. Their successful original parser results were reused
under exact input/byte binding, rather than reported as newly rescanned. Each
positive and trap-negative DUT execution was new. Unequal generated C++/header
objects were not reused.

Original result rows retain fields `mode, test, op, count, passes, ticks, flush,
result`: OFF 19 `[0,1,2,16384,1,380840,5572,0]`, ON 19
`[0,1,2,16384,1,334071,5558,0]`, ON 21
`[1,1,2,16384,1,345578,5565,0]`. The workload index (19/21) is separate from the
row's `test` field. Host wall time is not hardware performance.

## What the original traces establish

All 2,015 matched ordinary-demand dirty eight-beat C bursts with ON finish before
the matched store-prefetch first D beat. Historical OFF has no matched burst
finishing before the prefetch's last D. The original traces contain no explicit
E event, sink or cycle: E timing remains **UNKNOWN**. C-before-E follows from the
pinned acquire engine's last-D-to-E order, not an invented E observation.

The demand is joined by its full CPU identity, physical address, opposite cache
way, later refill and the absence of an intervening install. C itself does not
carry that CPU token. PF generation reuse is disambiguated by the exact
allocation/A/refill episode; PF and ordinary demand do not acquire a fabricated
posted cohort identity.

Nonoverlapping accepted-cycle intervals account for the 46,769-cycle kernel gain:
46,790 fewer cycles from PF allocation to demand acceptance, minus 28 extra cycles
from demand acceptance to refill, plus 7 fewer subsequent cycles. This is exact
temporal accounting, not exclusive stall-cause attribution. The read-outstanding
cycle sum remains 159,869 and read-outstanding-without-R-valid remains 127,007.
No faster DDR service or hidden DDR latency is claimed. The inherited
cross-interval external ownership join remains UNKNOWN.

## Focused correctness and native state

The real-cache/mixed-home focused gate passed 18 OFF and 18 ON cases, plus two
nonzero independent directory-mutation controls. It covers dirty, clean and invalid
other ways, first-C/E and last-C/E coincidences, pending-victim exclusion, reuse
before delayed ReleaseAck, flush and PF/demand denied-only or corrupt-only errors
at beats 0, 3 and 7. See the [component scope and runner](../../simulator/gsim/distinct_way_release/README.md).
The component has `postedConfig=None`; it does not dynamically qualify posted
live/intent gates or the CPU retirement boundary. Its cycle counts are fixture
timing, not the CPU measurement above.

The native OFF/ON census adds exactly two scalar issued-owner bits: 127,785 to
127,787 scalar declaration bits. Array declaration bits remain 735,863. All 100
RAM instances, their geometry and ports, 484 production instances and top-level
ports are unchanged. This is a literal native declaration census, not mapped
LUT/FF/BRAM, PPA, STA, routed frequency or board throughput.

The separate memory-resource experiment's 4,800-bit reduction retains its own
qualification. It is not added to this result as a jointly executed configuration.

## Integration and retained failures

The executing CPU and original native/component sources were frozen at local
`e8c1504da785486d761f213a5e8589a00ba0618c`, tree
`1f0f32c87e54ffb47d86273c86261a2944215c0e`. Integration adds those changes to the
published-equivalent `bcd22d7c551ed974fdf0295566c76cf17a68cc1b` tree
`47046da3e74dd2b8a488dadf313cc7030f3be549` (published dev `6744b01`). Cache/home
production files exactly match the candidate; the existing resource backend,
parameters and storage files exactly match the published resource source. The
combined FPGA config is the exact additive plumbing of their independent flags.

A source-bound direct-scalac build (not a new Mill build) compiled every production
Scala source and the 20 needed test/audit sources. Sixteen configuration tests and
ten no-build CLI cases passed. The two actual native sides on the merged source
have complete corresponding constructor/profile fields; the only added resource
metadata fields are explicitly false. All 275 raw native files per side, including
`filelist.f`, are byte-identical to their respective qualified candidate export,
without normalization. Raw CHIRRTL bytes differ and are retained as distinct inputs;
no raw-FIR identity is claimed. No CPU, cache runtime or large Clang build was rerun
for this integration bridge.

Two bridge attempts remain failures in the evidence: first, the in-memory CHIRRTL
API rejected `--target-dir` before elaboration; second, that in-memory API omitted
DedupGroupAnnotation records and changed queue/module deduplication. Those outputs
were rejected. The successful bridge restored the original `emitCHIRRTLFile`
semantics, compiled only two repaired test sources into a fresh overlay, and bound
the prior fresh production/test classes by every byte hash. These were test export
path failures, not production RTL reversions. The earlier focused header precheck
failure and OFF split-generation recovery remain in the original evidence too.

The [machine-readable evidence](distinct-way-release-evidence.json) pins the
receipts and scopes. [Reproduction sources](../../simulator/gsim/distinct_way_release/reproduction/README.md)
include exact small helper snapshots and reuse mappings. Generated models, native
RTL, binaries, large raw traces and logs are intentionally outside the source tree.

## Payload bandwidth and AXI utilization

Rates below use the original 100 MHz reporting clock and 131,072 useful COPY bytes:
`MiB/s = payload_bytes * 100000000 / cycles / 1048576`. They are cycle-derived
model rates, not measured FPGA frequency or a routed-timing claim. The flush
column includes the separately measured flush tail in the denominator.

| Workload / side | Kernel payload MiB/s | Payload MiB/s including flush |
| --- | ---: | ---: |
| Bare 19 fresh OFF | 32.82218254 | 32.34889186 |
| Bare 19 fresh ON | 37.41719575 | 36.80486649 |
| Sv39 21 historical / fresh ON | 36.17128405 / 36.17128405 | 35.59803271 / 35.59803271 |

Bare payload throughput improves 13.999719% in the kernel and 13.774737% including
flush. COPY's architectural semantic traffic is one payload read plus one payload
write, so read-plus-write semantic bandwidth is twice the payload rate. Accepted
AXI wire traffic is different: it includes fetch, line allocation/read-for-ownership,
coherence and flush. The additional traffic is retained; it is not all declared
useful COPY payload or independently proven useless traffic.

Each accepted R/W data beat is eight bytes. The nominal 64-bit, 100 MHz interface
ceiling is 800 MB/s = 762.939453125 MiB/s **per direction**. Two independently
saturated R and W channels would total 1,600 MB/s = 1,525.87890625 MiB/s; this is an
interface arithmetic ceiling, not a claimed DDR-controller or workload result.

| Bare case 19 ROI metric | Fresh OFF | Fresh ON |
| --- | ---: | ---: |
| AR / R / AW / W handshakes | 4099 / 32792 / 2049 / 16392 | 4099 / 32792 / 2049 / 16392 |
| R beats / cycles | 8.61044% | 9.81588% |
| W beats / cycles | 4.30417% | 4.90674% |
| (R + W) beats / cycles | 12.91461% | 14.72262% |
| Wire use / independent two-channel ceiling | 6.45730% | 7.36131% |
| Whole-bus idle cycles | 183883 | 137048 |
| Read-outstanding cycles without R-valid | 127007 | 127007 |
| Mean / peak accepted read owners | 0.419780 / 2 | 0.478548 / 2 |
| Mean / peak accepted write owners | 0.0685774 / 1 | 0.0783546 / 1 |

The combined beat/cycle percentage adds both channels and therefore has a
200% theoretical maximum; dividing it by two gives the explicitly separate
independent-two-channel utilization row. These are accepted transfer beats,
not useful-payload utilization. Whole-bus idle is a separate raw statistic.
Read and write owner means use pre-edge accepted ownership.

Including flush, both Bare sides have AR/R/AW/W totals
`4100/32800/2305/18440`, with 262,400 requested read bytes and 147,520 strobed write
bytes. Sv39's corresponding totals are `4162/32848/2305/18440` on both sides.
The original host prevents AR admission behind its AW/pending-read fence; measured
simultaneous R/W and simultaneous read/write ownership remain zero. That host
scheduling restriction is unchanged and does **not** establish an RTL half-duplex
restriction or a DDR latency improvement.

## Exact opt-in export profile

The following native export entry is generated from the actual CPU `canonical_flags`
plus `--distinct-way-release`, and checked against the successful merged native
constructor audit's complete `canonicalOptions`. It selects the measured
ROB64/PRF64/LSU4, D-translation16, DMA4, two-issue profile with frontier, LRU,
posted priority, posted/prefetch coexistence, head offer and canonical overlap.
This is an opt-in R64 experiment. Generic defaults stay false; the R16 recommended
preset has not been promoted or changed.

Replace `/absolute/fresh-native-output` with a fresh output directory. This is a
native export command only: it neither installs firmware nor runs the DDR-host CPU
workload. It was documented here without launching another export or test.

```sh
mill -i IonSoC.test.runMain ooo.FpgaNextMain /absolute/fresh-native-output \
  --canonical-virtual-store-overlap \
  --data-translation-entries=16 \
  --distinct-way-release \
  --dma-line-entries=4 \
  --dma-line-transfers \
  --fetch-previous-packet \
  --load-order-older-retire \
  --lsu-entries=4 \
  --memory-proof-frontier \
  --physical-load-ingress-flow \
  --physical-regs=64 \
  --posted-prefetch-coexistence \
  --posted-prefetch-head-offer \
  --posted-preparation-priority \
  --posted-store-merge \
  --prepared-store-lookahead \
  --rob-entries=64 \
  --selected \
  --store-next-line-prefetch \
  --store-prefetch-lru-victim \
  --store-prefetch-mru-insertion \
  --virtual-ram-load-precheck
```

For the OFF side remove only `--distinct-way-release`. The actual complete
constructor records keep `reconstructIssueTokenIndex=false` and
`sharedMemoryAddressState=false`; omit both resource-enabling flags. They also
keep `translatedResponseEmptyFlow=false`, `precheckedDataRequestFlow=false` and
`flowTileLinkResponse=false`. Prefetch candidate lifetime remains 1, break-on-store
false and DMA yield 0. No return-flow or resource-ON CPU qualification is implied.

For the separate executing-CPU replay, the original firmware/DDR guest path is
`<recovery-workspace>/posted-preparation-priority-cpu-host-r2/guest.bin`, where
`<recovery-workspace>` is a caller-chosen restored evidence directory. The binary's
SHA-256 is `3af27dccda6acd677bb01fdad4d240ffee2f9af1c1fb4181a71c43ff2087a810`.
The exact host/model/guest run and restore contracts remain in the pinned CPU
source and terminal archives; this export example does not substitute a different
firmware image, guest, DDR host or workload.
