# Focused resource-reuse lifecycle gate

Production is frozen at4d3f1b57643ac9e59d379192e25e03372f6bd2c5; passive/native test fixture commit3969476cad0775f5b6de405502a4e6822f566311. No fixture drives internal DUT state. The existing exact frontier/LRU/posted-priority backend+translation+cache focused assembly is compiled once with both default-OFF resource flags explicitly ON. No full board model is compiled.

The native worker's one Scala compile and source-bound classpath are reused verbatim. All four native modes establish each resource group's actual delta and strict OFF equality separately. This focused runtime validates the combined behavior; it does not mechanically compile four equivalent large hosts.

The original26 reviewed raw-instruction cases and all their existing expected bytes, retirement, exceptions, proof, cache ownership and timing assertions are retained. A new independent accepted-rename ledger checks the actual shared payload on the next clock, original full64-bit tags, all early captured-store write grants including stale/kill suppression, and the final accepted LSU class/index. Canonical-load beat and lanes come from independent raw addresses, widths and page-table mappings; noncanonical serial-load replay payload is excluded by its original validity contract. No current backing queue token-index field is read: the exact actual ON layout reconstructs only fixed row identity, with full tags checked against accepted rename events.

New raw-instruction cases cover B/H/W/D, two early stores, all64 row STORE→LOAD→STORE generations, and a real frontier winner different from the staged original memoryChoice. Witness totals are reported, not inferred. Missing required witnesses are a coverage blocker, never success.

Host oracle negatives run first: unsafe virtual-store VA replacement by PA, forbidden store/atomic load writes, killed writes, stale same-slot full tag with bit63 changed, wrong actual canonical beat, and independent different-row writes. Runtime negatives perturb only observation/expectation data and must reject; they do not alter architectural expected outcomes to agree with the DUT.

Same-row retire+allocate and kill+allocate are prohibited by the original ledger: RenameRob allocation uses old count+lane<robEntries (line358) and allocationPrefix includes !recoveryCycle (line317). Real event nonoverlap is asserted. Different-row concurrent retirement/allocation and immediate later generation reuse are measured; impossible same-row events are not manufactured via internal writes.

Budgets: one heavy stage at a time; Java/GSIM900s each; one O1+ASAN/UBSAN model Clang1800s; host link180s; each short runtime120s; initial free disk740MiB and runtime floor700MiB; logs32MiB. The historical same-size focused model used297s and6.1GiB RSS. Actual stage metrics are recorded independently in fresh receipts. LeakSanitizer is disabled only for the known environment limitation; ASAN/UBSAN remain enabled.
