# Reconstructed default-eight D-TLB experiment

This is new source recovery on public commit
`926ea18ecab93364a1a7b1ae745fc674c275c2b1`, after loss of the previous executor.
It is NOT restored commit fd9d719 and does not inherit its historical PASS,
model identity, timing, performance, or resource results. The former private
posted-store candidate chain is not part of this public parent.

## Reconstructed bounded change

`dataTranslationEntries` is legal only for 4, 8, 16, or 32, with default eight in
every profile. Native and GSIM selectors/receipts carry it explicitly. The real
MachinePlatform D service alone receives it; instruction translation stays at
eight and both selected board PTE caches remain four. Natural replacement wrap
uses exactly 2/3/4/5 index bits. Demand and optional read-only load peek continue
to use the same associative lookup function. Keys, privilege, permission/global
policy, SFENCE, PMP, context, full-token ownership and final faults are unchanged
relative to this public parent. No store merge, posted writeback or new protocol
was introduced during recovery.

## Fresh validation status and plan

Host-only CLI tests can run without installs or builds. All Scala tests, actual
GSIM capacity/permission/replacement checks, real CPU aliases/current kernel,
and native resource comparison MUST be rerun before qualifying this new source.
No heavy work is included in this recovery patch.

When a toolchain and slot are separately authorized:

1. Run `mill -i IonSoC.test.testOnly ooo.DataTranslationCapacitySpec`.
2. Emit `ooo.DataTranslationCapacityGsimMain <fresh-dir> 16`, build with the
   existing supported GSIM toolchain, and compile `virtual_load_precheck.cpp`
   with `PRECHECK_ENABLED=1` and `DTLB_ENTRIES=16`. Exercise all high-half slots,
   N+1 replacement, failed-walk nonallocation, full wrap, flush, no-side-effect
   peek and inherited permission/fault controls; reject address poison.
3. Emit the actual selected board with explicit `--data-translation-entries=16`
   and verify emitted I8/D16/PTE4 plus unchanged selected parameters.
4. Recover byte-identical alias/current-kernel guests and observers from a
   persistent original source, verify original hashes, then replay. This worker
   does not possess the original alias guest or full observer bytes; hashes and
   historical measurements alone cannot substitute for those inputs.
5. Export D8/D16 from this same new source and compare literal reachable state,
   fixed RAM ports, and unchanged I/PTE geometry. Historical +1657 literal bits
   is a transcript record, not a resource result for this reconstructed source.

D32 is only a legal parameter. Do not claim D32 behavioral/capacity qualification
without its own independent boundary probe (including 33 entries). Mapped FPGA
area, routed timing, power and physical board behavior remain unverified. Keep
the default at eight; associative comparator/mux fanout is a timing risk.
