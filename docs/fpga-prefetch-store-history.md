# Optional accepted-store prediction history break

`CoherentCacheConcurrency.prefetchBreakOnStore` defaults to false and requires
next-line prefetch. When enabled, an accepted ordinary CPU store clears the existing
read-history valid bit. An unaccepted store offer, DMA probe, uncached operation or
atomic operation does not perform that clear. This changes prediction history;
it does not cancel an accepted prefetch transaction or change its ownership.
The final flush/reset priority, full physical address authorization, finite token
deadline, demand/probe priority, response ordering and every capacity remain intact.

The motivating exact-board trace is recorded in
`fpga-prefetch-board-attribution.md`: all 252 speculative lines in the copy ROI were
replaced unused by its interleaved destination stores. This option is a bounded
policy experiment. Full-board pure-read, copy and mixed-workload results decide
whether it belongs in a selected profile.

Hardware is frozen at `df4594f`. The focused `prefetch-store-history-r2` gate passes
the 512-line/two-way off/on pair at three allocation attempts and an enabled model
whose test addresses cross 4 GiB. All models retain two MSHRs, two writebacks, two
reply credits and four AXI slots. Coverage comprises 36 new history scenarios,
45 existing lifetime scenarios, 22 existing prefetch scenarios and two seeded
CPU/DMA traces per member of the ordinary off/on pair. These include offered
versus accepted stores, held replies, failed write allocation, uncached exclusion,
DMA probes, reset/flush, whole-line permission and page boundaries. Independent
byte/value, premature-clear, missed-clear, expiry and permission mutations fail.

The offered-store fixture holds its request for 65 cycles before acceptance.
History survives the hold in both variants and clears at acceptance only when the
option is enabled. Pure-read prefetch, existing lifetime and both seeded stress
logs are exactly identical across the pair. Previously qualified authorization
and actual-CPU busy-gating binaries are source/artifact bound and replayed with
their negative controls; the context argument remains compositional.

After removing only FIR source-location annotations, default-off full CHIRRTL is
identical to the prior qualified three-attempt model. Enabled and reference models
have identical port, register and memory declarations: the option adds no owner,
credit or payload state. These are structural checks, not mapped PPA measurements.

The receipt is `evidence/fpga-prefetch-store-history-20261008.json`. Reproduction
uses `simulator/gsim/prefetch_store_history.py --tag <new-tag>`, with the qualified
`prefetch-candidate-lifetime-r1` artifacts available for the compositional context
replay. On a fresh checkout, run that existing lifetime suite under its named tag
first. An initial harness compile failure used nonexistent input getters; its
model was preserved and hash-bound for reuse after changing only the observer to
read the actually driven input fields. No RTL correction was needed.
