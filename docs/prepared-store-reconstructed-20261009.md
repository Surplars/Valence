# Reconstructed prepared-store lookahead, 2026-10-09

This is a new default-OFF source reconstruction on public `dev`
`926ea18ecab93364a1a7b1ae745fc674c275c2b1`, tree
`7d183c0812fb25eef60b3fc24c6bb8dbf477b51d`. The prior local source and evidence
were lost when the cloud executor filesystem was replaced. This patch is not
byte-identical to the unavailable `7a27878` or combined `0e62d30` checkpoints,
and does not inherit their runtime, native-state or performance results.

## Scope and invariants

The option `preparedStoreLookahead` / `--prepared-store-lookahead` feeds the
existing registered memory-preparation stage. It adds no register declaration,
queue, LSU capacity, StoreBuffer slot, cache credit, or physical request port.
Native emitted state and combinational area/timing have not been measured.

The original `memoryCandidates` pool has priority. Only when that entire pool
is empty may the planner use a mask of already prepared nonhead stores. The
empty-pool decision precedes the planner's issued-owner exclusion. Therefore a
sole original candidate issuing this cycle cannot expose a younger fallback.
New original work replaces a nonhead prefill through the existing planner.

This reconstruction deliberately admits only pending, memory-live, correctly
indexed, ordinary integer stores with saved data/address and an existing aligned
RAM-range classification. It excludes virtual addresses, MMIO/out-of-range or
misaligned addresses, atomic/system/FP traffic, multiply/divide, control flow,
and known fetch faults. Integer FP requests are system requests in this public
decoder. It does not restore posted merge, WB reservation, or store-prefetch code.

The saved range bit is not PMP authorization. All code after the planner's
eligible input remains byte-identical to the verified public baseline, including
staged full-token matching, pending checks, exact-head store launch, current PMP,
interrupt/system ordering and recovery suppression. Prefilling does not issue,
retire, acknowledge or physically write a store. PMP-denied stores still take
the inherited precise path when they reach the head.

The option requires registeredMemoryAddress and parallelMemoryPreparation.
Defaults, two-issue topology, public LSU2/explicit LSU4, fetch history, older-prefix
retirement, stage2/V4 firmware, MAC, DMA and JTAG remain otherwise unchanged.

## New checks and open gates

Eleven host methods passed: six independent policy/source-boundary tests and
five real parser/native-preflight tests. The selector sweep covers 10,432 vectors
with circular ages, both option states and all issued-owner positions at two and
four entries. A directed control distinguishes the forbidden after-exclusion
fallback. Native preflight creates no output and invokes no compiler. Python
syntax and git whitespace checks also passed.

```sh
python3 -B simulator/gsim/fixtures/prepared_store_reconstructed/test_policy.py
python3 -B simulator/gsim/fixtures/prepared_store_reconstructed/test_selection.py
```

`ooo.PreparedStoreReconstructedConfigSpec` supplies three fresh Scala checks for
defaults, exact option/capacity isolation and prerequisite rejection. It has NOT
been run yet. No Scala compilation, RTL elaboration, hardware simulation, native
export, NEMU or firmware/FPGA execution is claimed by this source checkpoint.

Before qualification, run the focused Scala gate and fresh source-bound real CPU
OFF/ON checks: nonhead capture and later head launch, new-load replacement,
branch kill/recovery, full-generation owner reuse, precise PMP/misalignment
faults, MMIO/AMO/FP exclusion and complete cache/StoreBuffer drain. Recheck
unchanged original guest bytes if a verified copy becomes available. New native
exports must measure state/ports and the extra mask/selection cone. Old hashes,
models, receipts, counts and speedups must not be relabeled as reconstructed
qualification.
