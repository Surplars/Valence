# 32 KiB instruction and data cache candidate

This is an explicit `staged-fetch-turnover` candidate, not a change to the legacy defaults or a timing signoff.
The pinned configuration is `simulator/gsim/config/cache32k-candidate.json`; `cache32k.py` uses its exact GSIM and managed-export argument vectors.
It retains two-issue RV64GC (F/D hardware), two LSU entries, 100 MHz target, 460800 baud and 2 GiB DDR.

## Geometry and invariants

Both caches contain 512 64-byte lines: two ways, 256 sets, 8-bit set index, 50-bit physical tag.
The D-cache has a 9-bit physical slot index, eight synchronous 64-bit banks of depth 512, and a 9-bit flush scan.
The I-cache has two synchronous 512-bit banks of depth 256.
The matching home directory contains 512 owners and 512 full 58-bit line tags; directory geometry follows L1 geometry automatically.
No coherence state transition, grant/release ownership, fill engine capacity, probe arbitration or response queue depth changes.
The D-cache remains one outstanding miss; cache capacity alone does not increase memory-level parallelism.

The previous fixed 8 KiB test windows could not contain 512-line conflict addresses. Cache and coherent-DMA fixtures now use at least twice cache capacity; their independent backing oracle has the same bound. The ordinary standalone DMA fixture remains 8 KiB.

## Bounded verification

Source the existing cloud tool environment, then run sequentially:

- `mill -i IonSoC.test.compile`
- `python3 simulator/gsim/cache32k.py --tag UNIQUE --phase checks`
- `python3 simulator/gsim/cache32k.py --tag UNIQUE --phase board-fir`

The checks include independent instruction packets, all-slot residency, high-index reset, same-set conflicts/LRU, held responses, late denied fill and PMP fallback; D-cache all-slot dirty residency/flush, denied refill, independent-hit-under-miss, dirty eviction, probe/backpressured bypass response ownership; and all-slot real home directory residency plus high-slot DMA probe, upper-way probe and dirty eviction. Corruption injection must fail each independent oracle. ASan/UBSan remain enabled.

The board phase only emits FIR and checks actual I/D SRAM/tag/directory dimensions, LSU capacity and DDR bound. The managed exporter is available through `--phase managed-export` but is a separate export action, not included in focused checks.

## Resource and timing risks

I/D data storage each rises to 262144 bits. I-cache tags require 25600 bits; D-cache tags require 25600 bits; home tags require 29696 bits, excluding valid/dirty/LRU/owner metadata. These are logical storage counts, not measured FPGA utilization.
Tag and valid arrays remain registers with indexed selection. The larger index muxes, write/reset fanout and home directory qualification can worsen critical paths; SRAM physical mapping and BRAM fragmentation also require measurement. No 100 MHz timing, board stability, area or workload-speed claim follows from elaboration or GSIM tests.
