# Internal whole-line Grant and bounded dual-origin prefetch

Historical snapshot below; follow-up [three-chain scheduling](memory-schedule-overlap.md)
adds a third default-OFF selector and changes current product counts to61/151/22.
These older source-hashed receipts do not automatically qualify subsequent source changes.

2026-10-12. Implemented locally from `dev` at
`f1ef88653dd8f13724742bed7c40888a34242e3b`; no unpublished dot candidate was
available. Both independent options remain **default OFF**. Commit/push had not
occurred at acceptance; source delivery is recorded by Git, without rewriting
these historical receipts. No preset promotion, Vivado, Linux execution, or new
board bit is claimed.

## Structural changes and preserved boundaries

`internalLineGrant` / `--internal-line-grant`: the mixed coherent data home
already owns all512 checked bits. A private `LineGrant` transfers them to the
existing acquire-engine word buffer at once, replacing eight internal64-bit D
beats. This does not widen public TileLink or define a standard TL opcode.
Permission-only Grants and ReleaseAck retain their paths. Original source/sink,
held-owner arbitration, acknowledgment queue and actual E handshake remain:
neither CPU result nor directory completion bypasses the required real ack.

`concurrentReadStorePrefetch` / `--concurrent-read-store-prefetch`: classify
existing live owners by immutable READ/STORE origin, allowing at most one
unattached owner of each class within the same two MSHRs. No new candidate
queue, line buffer, reservation pool, cache capacity or authorization is added.
An offered demand miss has first refusal, including a disjoint-way miss in a
reserved set; the old whole-set predicate was insufficient under independent
demand admission.

Full PA/way conflicts, permission/token lineage, resident read tokens, dirty
victim credit, probe/flush and captured-writeback rules remain. A READ cannot
bypass the required writeback capture/send boundary; STORE's stricter release
gate was not removed. Failed refills cannot install useful tokens. Reviewed
geometry remains two acquire/MSHR owners, two responses and two writebacks;
coexistence also requires qualified durable candidates and independent admission.
Unsupported combinations fail closed. Products are now FPGA60/core151/cache21.
Historical JSON manifests stay byte-frozen. Their complete Python bridges demand
both new fields explicitly, strictly Boolean false (not omitted/numeric zero).

## Matched actual-CPU results

Four fresh full `BoardSocGsim` models share one frozen source/tool closure.
The byte-identical published guest executes64KiB COPY, two measured passes,
S-mode Sv39 and Bare, including the real final clean/flush tail. Published
independent R32/B32 service and READY laws are unchanged. Full constructors and
native assembly contract are checked; only the two new Boolean selectors differ.

Fixed f1 geometry: two-issue RV64GC, ROB16/PRF48/LSU4, 32+32KiB caches,
DTLB16/ITLB8, MSHR2/response2/writeback2, shared DDR slots4/write credits2,
DMA line owners4, pending store-proof rows2/early-load credits2. Full MAC/CMU/
JTAG/peripheral assembly remains. None of these capacities increases. This is
CPU-domain behavioral GSIM, not physical MIG/independent-clock qualification.

| Optional arms | Sv39 cycles incl. flush | Sv39 payload MiB/s | Bare cycles incl. flush | Bare payload MiB/s |
| --- | ---: | ---: | ---: | ---: |
| Neither / fresh f1 baseline | 236951 | 52.7535 | 260694 | 47.9489 |
| Whole Grant only | 250080 | 49.9840 | 237938 | 52.5347 |
| Dual-origin prefetch only | 204976 | 60.9827 | 248721 | 50.2571 |
| Both | 202290 | 61.7925 | 215747 | 57.9382 |

Combined gains: Sv39 **17.1343%**, Bare **20.8332%** throughput versus fresh f1.
Whole Grant alone exactly reproduces dot's Sv39 regression: cycles+5.5408%,
bandwidth-5.2499%. A local transfer improvement alone is not a promotion criterion.

Sv39 ROI traffic stays4160 AR/2048 AW, 32832 R/16384 W beats in every arm.
Retired work stays40984 with the same retired-PC hash, complete CPU/memory byte
checks and drained tagged-store responsibilities. Baseline/combined ROI cycles
228764/194051; tails8187/8239. Accepted cache requests remain32768; valid offers
fall104799->67679. Two-MSHR cycles rise35568/228764 (15.55%) ->53338/194051
(27.49%). Prefetch-only occupancy is higher35.35%, yet both are faster:
shorter owner lifetimes can lower occupancy while increasing throughput.

Not bus saturation: combined ROI R/W beat duty is only about16.92%/8.44%, and
simultaneous R/W fire cycles remain zero. Exclusive diagnostic-priority buckets
still show105102 refill and34905 blocked-offer cycles; these are observations,
not a causal latency partition. Next target is refill/request scheduling and why
independent reads/writes remain serial, not merely more MSHRs. Bare combined AR
increases4124->4908, so its gain is not an unchanged-traffic result.

MiB/s assume a100MHz model timebase and COPY payload, not logical R+W, MIG peak,
measured FPGA performance, workload-independent improvement or10ns STA evidence.

## Necessary short proof and evidence

- 15 targeted Scala configuration checks passed.
- Acquire engine:12 positives across legacy/whole modes, both return orders,
  denied/corrupt, held actual E and retained response identity; four byte/error
  mutations rejected.
- Real cache/home: nine dual-origin/demand-priority positives including dirty
  STORE writeback, actual backing denied/corrupt, probe/flush; three full-PA/
  immutable-origin/dirty-byte mutations rejected. This fixture uses legacy Grant;
  combined success is additionally checked by actual CPU.
- Actual CPU: eight matched positives and12 read/memory/trap negative controls.
- 41 lightweight CLI/historical full-constructor checks passed. Saved actual
  baseline constructor/fabric also passes the dual-credit schema bridge after
  changing only the existing tagged-return selector to its documented rollback
  false value for that check; this is not a new executed rollback model.
- All1231 component/board frozen input hashes and tools match current hardware/
  GSIM sources. All715 board artifacts and saved component model artifacts were
  rehashed. No vendor/generated simulator source or oracle constant was changed.

| Receipt under `build/gsim/` | SHA256 |
| --- | --- |
| `line-grant-prefetch-local-20261012-components-r4/receipt.json` | `ff6977e6eec108d810283b765e87e64cf5a8200b183b012449477e68f08659cd` |
| `line-grant-prefetch-local-20261012-board-r1/receipt.json` | `9341d8d451cbae838fb07f33bba9178e65cb5d8440eaacec1a01973661bd6194` |

Final host bridge hashes/results and CLI log are separately saved as
`line-grant-prefetch-local-20261012-final-audit-r1.json` and
`line-grant-prefetch-local-20261012-final-cli.log`, without rewriting passed
receipts. All build outputs remain ignored/uncommitted.

```sh
# Fresh bounded reproduction; choose a new output path:
GSIM_CXX=clang++-19 python3 -B simulator/gsim/line_grant_prefetch.py \
  --output build/gsim/line-grant-prefetch-UNIQUE_TAG --jobs 2
# --components-only limits work to component proof.
# --skip-components does not itself establish component coverage.
```

Preserved component failures: r1's observer assumed globally one unattached
prefetch; new-mode independent checks enforce one per origin and the same total
two-owner bound, keeping OFF checks unchanged. Dirty STORE-first r3 stimulus
expected READ capture before the required WB-send boundary; fixed stimulus waits
for that boundary instead of relaxing hardware. r2 configured faults without
applying them to backing memory and is not error proof; r4 exercises actual
denied/corrupt results. Model objects were reused only for checked host-only
corrections, with hardware/tool hashes frozen. Early CLI failures (missing new
false fields, native-vs-export selected argument/name assumptions and abbreviated
new flags) were fixed before the final41-test PASS.

Not covered: wide-home errors plus dirty concurrent-prefetch combined stress,
broader workloads, NEMU/full ISA, Linux, wide-data physical routing, timing or
resource utilization. These remain optional candidates, not a board release.
