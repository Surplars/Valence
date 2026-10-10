# Posted-store merge: original WRITE benefit and COPY cost

The corrected optional path stays default OFF. On the unchanged Bare benchmark,
WRITE18 drops from215756 to112826 ROI cycles (47.7067% fewer cycles,1.91229×
architectural byte throughput). COPY19 rises from383603 to452641 cycles
(17.9973% more cycles). These are two specific physical integer workloads,
not a general benchmark-suite improvement.

## Activation and default

`postedStoreMerge` remains default OFF. Enable it only for an evaluated workload;
these COPY results do not support enabling it for general use. The complete
measured native-export activation is reproducible with an already prepared
toolchain:

```sh
python3 -B fpga/next/export.py \
  --output build/fpga-next/posted-store-measured-on \
  --lsu-entries 4 --data-translation-entries 16 \
  --virtual-ram-load-precheck --physical-load-ingress-flow \
  --load-order-older-retire --fetch-previous-packet \
  --dma-line-transfers --dma-line-entries 4 \
  --prepared-store-lookahead --store-next-line-prefetch \
  --store-prefetch-mru-insertion --posted-store-merge --emit
```

For the measured OFF selection, remove only `--posted-store-merge` and use a
fresh output directory. Keep translated-response empty flow and prechecked
request flow disabled. The command emits native hardware; the separately
pinned benchmark receipts below describe the actual guest replay environment.

## Exact source and environment

Both models were freshly built from `0658f2d4a543ba5849498af626eec0a248363540`
(tree `cc1d50b223fc0b6ebec448292ce8964986b56af2`). The same final Board profile
is audited in [the delivery record](posted-store-delivery-review.md): DMA4,
LSU4, D16/I8/PTE4, prepared stores, physical ingress, history/prefix,
store-prefetch/MRU enabled, both request/response-flow experiments OFF.
Only posted-store selection differs between the two sides.

The original 6104-byte portable guest has SHA256
`3af27dccda6acd677bb01fdad4d240ffee2f9af1c1fb4181a71c43ff2087a810`.
Its original 1472-byte supervisor kernel and complete benchmark/guard/flush
oracles are retained. The sidecar adds passive bus and full-token owner
observations and never changes ready or memory timing. The ordinary multi-ID
DDR host has eight read credits,32-cycle due time, one-cycle beat spacing,
normal B+3 and periodic ready stalls. The functional fixture's256-cycle B hold
is absent. The unchanged precise-trap negative rejects on all four executions.

The machine-readable [result file](posted-store-seal-performance.json) pins all
four terminal receipts, both model receipts, final-instance audit, functional
gate and complete ROI/flush bus and owner summaries. Runtime receipts and raw
traces retain complete host, tool, model and guest hashes. Earlier source8f9
WRITE268913/COPY452643 were performance regressions; correctness oracles passed.
Those results remain preserved and are not current measurements.

## Result and useful work

| Case | OFF ROI | ON ROI | OFF flush | ON flush | OFF useful B/cycle | ON useful B/cycle |
|---|---:|---:|---:|---:|---:|---:|
| WRITE18,131072 written bytes | 215756 | 112826 | 10690 | 10647 | 0.607501 | 1.161718 |
| COPY19,131072 read +131072 written bytes | 383603 | 452641 | 5618 | 5666 | 0.683373 | 0.579143 |

Useful bytes count the program's architectural payload. Raw refill/writeback or
prefetch traffic is not added as useful work. COPY counts both the architectural
read and write; destination-only copy throughput is half its listed value.

Corrected WRITE has2048 original line owners with eight accepted members each,
16384 complete token drains and2048 owner releases. The original bug produced
2047 single-member owners and one three-member owner. The exact actual-edge
cause and old-source counterexample are in [the seal correction record](posted-store-younger-preparation-seal.md).
COPY retains2048 single-member owners: intervening loads remain real ordering
boundaries. Both ON ROIs allocate zero store prefetches, while OFF allocates2015
useful store prefetches. The episode's prefetch exclusion remains a separate
cost; this correction does not implement posted/prefetch coexistence.

## Bus accounting

| ROI quantity | WRITE OFF | WRITE ON | COPY OFF | COPY ON |
|---|---:|---:|---:|---:|
| Whole bus empty cycles | 99152 | 117 | 185707 | 256043 |
| Mean read outstanding | 0.370520 | 0.708870 | 0.416696 | 0.353128 |
| Mean write outstanding | 0.122736 | 0.235974 | 0.068777 | 0.057114 |
| Read outstanding without RVALID | 63542 | 63532 | 127024 | 127017 |
| R backpressure cycles | 0 | 0 | 0 | 0 |
| Both read/write outstanding | 0 | 0 | 0 | 0 |
| Same-cycle R/W acceptance | 0 | 0 | 0 | 0 |

The numerator for outstanding is the pre-edge accepted responsibility count.
AR/AW/R/W fire, valid-but-not-ready and no-offer buckets each sum to the window
length, with separate complete histograms and cross-window carry in the JSON.
No ARVALID means no offer, not proof that memory has no work. The results show
WRITE removes empty gaps; they do not establish overlapping read/write traffic.

WRITE ROI+flush has identical R wire/payload131328 bytes and W wire/strobe163840
bytes on both sides. ROI alone differs by one64-byte read response crossing its
boundary (OFF131200, ON131264; the flush compensates). COPY ROI+flush has identical
R262464 and W147520 bytes. Wire bytes and requested read payload/strobed write
bytes are recorded separately even when equal for these full-width transfers.
No excess PF traffic is counted as an efficiency gain. The passive bus ledger
does not attribute an external AXI B directly to a particular posted token;
the independent coherent owner ledger supplies the token/WB/drain checks.

## Scope

The directed physical CPU/cache/home gate and original benchmark oracles pass;
performance remains workload-dependent. Sv39 performance, a full-workload
suite, posted plus translated-response-flow ON, synthesis area/timing and actual
board speed remain unmeasured here. Native declared-storage cost is separately
bound to its own same-source export; it is not a synthesized-area estimate.
