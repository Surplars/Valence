# Optional store-prefetch MRU delivery composition

This describes the tested 9483 source composition. See
[the publication status and explicit profile](cloud-delivery-20261009.md) for the
current qualification boundary, including the completed D16 54-case ROM menu
and the separately bounded optional D32 and minimum D4 experiments.

This new checkpoint starts from delivery
`6a26b9cd6f967be88f2c0633aacf24e5a89d7ce2`. It applies only the seven-file
functional MRU delta `0d17c8d00b56ef698c5d3c71353beebc612ef5ca` and the selected
tests from qualified candidate `6d7a79c2f5095157d65943ff13ed756ee3d10923`.
The existing 81 lines of passive cache observations are not added a second time.
The source-bound fixture runner gains an explicit `--tool-files` argument for
already installed tools and serial Mill jobs. The actual host/cache oracle
bodies remain byte-identical to their qualified inputs.

Defaults remain D8, prepared-store OFF, checked-store PF OFF and MRU OFF.
`--store-prefetch-mru-insertion` requires `--store-next-line-prefetch` at both
configuration and command-line boundaries. Read-origin prefetch keeps LRU
insertion. Successful store-origin fills use their captured live MSHR origin to
update the existing replacement bit. Demand behavior, permissions, admission,
owner/drain capacity, BootROM, DMA, MAC and JTAG source paths are unchanged from
6a26. This source does not restore the lost posted-store/WB-reservation work.

## Measured reason to pair the experimental options

The separately bound PF-only 128-KiB Sv39 COPY experiment issued 2015 additional
complete cache-line reads. The observer saw all 2015 installed store-prefetch
lines evicted by their matching A-source demand before use. The later B-store
hit/miss association alone does not exclude an intervening refill; the stronger
evidence is the full-PA install-to-eviction chain. PF-only COPY therefore has a
documented traffic regression despite passing its functional checks.

A new, same-source whole-CPU MRU OFF/ON pair used candidate 6d7a, checked-store
PF ON on both sides, and the same immutable formal guest/kernel:

- WRITE20: 207483 kernel ticks and 10681 flush-tail ticks on both sides.
- COPY21: 633266 to 497148 kernel ticks; AXI read requests 6176 to 4161 and
  read beats 48963 to 32843. The reduction is exactly 2015 eight-beat line reads.
  MRU ON reports 2015 useful store-origin prefetches. Write requests, write
  beats and flush-tail cost do not increase.

The pair checked every case's complete buffers, precise faults and return,
captured origin/full-owner lineage, terminal drain and deliberate negative
controls. The model archive is Library
`libfile_14d0cc0727488191b69af0887269f916`; the COPY result archive is
`libfile_6ecce36172f08191a3db2c5c30cad4be`. Their immutable receipts retain the
6d7a identity. These measurements support enabling checked-store PF and MRU
together when trying this specific experimental streaming profile. They do not
establish a general bandwidth benefit, board behavior or complete Linux gain.

The complete prior-source measured report and immutable evidence identities are
in [store-prefetch-insertion-results.md](recovery/store-prefetch-insertion-results.md).

## New delivery validation boundary

The tested 9483 integration passed fresh source-bound Scala/config checks,
a C+MRU full-Board model, actual RV64GC positive/negative runs and native export.
The native comparison records its exact reference and byte or syntax equality
scope. Existing receipts retain their tested source identity; later publication
children change documentation only. The C+MRU profile is the previous selected
C profile, D16/precheck ON,
LSU4/DMA4, physical load ingress, older-load retirement, previous-fetch packet,
prepared-store ON and checked-store PF ON, with only MRU added.
`prefetchBreakOnStore=false` remains unchanged.

New timer, M/Bare NEMU, CPU+DMA and formal WRITE/COPY gates passed with their
own strict source/model/tool bindings. The complete original 54-case ROM menu
also passed on the D16 9483 model, including monitor return, `h`, final context,
data and one empty owner snapshot. Its same-ABI checkpoint lineage and exact
terminal evidence are recorded in the publication status document. The
interrupted 6a26 run remains incomplete under its original identity.
Mapped/routed PPA, FPGA timing, general Linux workloads and controlled Sv39
late-cancel/ROB-reuse remain outside this qualification. D32's separate
alias/formal READ qualification does not extend the D16 full-menu result.
