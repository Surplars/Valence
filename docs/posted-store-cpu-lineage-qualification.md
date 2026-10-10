# Actual CPU posted-store lineage qualification

On 2026-10-10, assigned serial execution session 28310 finished with exit 0 and
`PASS_CPU_LINEAGE_SYNTHETIC_RETENTION_ONLY`. The default-OFF candidate passed
all five OFF programs, all five ON programs, and both deliberate ON full-token
and byte-oracle mismatches. The negative cases exited exactly 1 with the expected
original LSU lineage diagnostic, not a timeout, crash, or sanitizer failure.

This executes the real CPU, ROB/head/PMP authorization, four LSUs, registered
request FIFO, StoreBuffer, response ownership, translation adapter, real Sv39
walker, checked ordering boundary, and APLIC. The downstream remains the stated
512-cycle retained-owner environment. It does not qualify a real CPU/cache/home
combination, FP/atomic origins, fast buffered-store retirement, throughput,
resource use, timing, or physical-board behavior. Both prechecked request flow
and translated response empty flow are OFF.

## Exact identities

- Final tested host/launcher source: `5346b87b6ffcb5a09a5b6ee8d463f4a3b604593a`,
  tree `032cb39b90dd6eb7d9432646d95552c54642b30b`.
- Actual emitted/generated RTL source: `abb9712cdb6a317ba8382e366a6d861c95b828a1`,
  tree `55ca45e33331eea4ecbc1a13ba42eb3b7ed881c1` (attempt r3).
- All production `src/main` bytes equal cache-qualified source
  `bc518ec83fc51bbef9e5376f9cee0e1e10200848`.
- Recovered tool-file receipt SHA-256:
  `0743301bca2da57ef871ab1cbc1184c831341269d1e4db377cb1628e29ea0512`.
- Final binding SHA-256:
  `4daa80ef75b4b3c5c7e93284494938da484f699bae480612d6473bda93e80289`.
- Final runtime receipt SHA-256:
  `79a85d13486295a5f6c4020f53d6a8e6dee796da89557ad2a21888a96c92ef80`.
- Raw runtime receipt and all twelve per-case logs/JSONL traces/results:
  `/workspace/scratch/41e4a649bb60/recovery-20261009-1816/posted-cpu-lineage-gate-r6/`.

The strict launcher rechecked the complete source inventory and pinned tools
before and after each command. The reused r3 FIR/header/generated C++ and r4
native objects have exact hashes recorded alongside the final host source. Only
declared host/launcher/test/document files changed; Scala/RTL/build/tool changes
would reject reuse. Both real headers passed new-host syntax before linking.
This is explicit model reuse with a new host identity, not a claim that the full
source inventories are identical. Raw guest encodings, interpreter and external
stimulus were preserved throughout the corrections.

## Executed evidence

The ON physical program retired 117 instructions and exactly nine stores. It
observed 84 ROB index reuses while an external posted owner was live, including
five reuses of an already acknowledged store's index with a different full tag.
It retired 86 instructions during retained ownership. Ordinary load wait was
931 cycles; APLIC, FENCE, FENCE.I and context-CSR waits were each 511 cycles.
Recovery overlapped retained ownership twice. Actual held returns occurred
twelve times. These are adversarial correctness counters, not performance data.

Both variants delivered precise misaligned-store cause 6, locked-PMP store
cause 7, and Sv39 store-page-fault cause 15. The virtual-fault program performed
exactly one independently predicted PTE read. The separate successful virtual
store performed exactly two PTE reads, one request and response at every
required stage, one original-token completion, and zero traps. Its translated
physical request retained no posted proof; the later physical load checked the
stored bytes. The OFF physical program had zero proofs and passed the same raw
architectural and byte-memory oracle.

The runtime also executed its explicit host sensitivity controls for old-owner
epoch crossings, an old reply on the same sampled tick, store/older-load
cancellation, wrong full tag/epoch, omitted late response, fake completion and
fake retirement. These qualify the host checks' rejection paths, not injected
DUT-fault coverage. The cancelled physical speculative load in the OFF branch
case was classified by actual redirect/full rename order and raw LOAD opcode;
all accepted requests, data responses and transport owners still drained.

## Preserved failed attempts

Attempts r1-r5 are retained under the same recovery directory. r1 rejected an
inherited environment hash change before running tools. r2 compiled 191
production and 230 test Scala sources, then rejected an overly broad OFF port
census. r3 passed both actual board ON/OFF configuration/elaboration tests and
generated both CPU models, but its host read an input-only GSIM signal as a
getter. r4 passed all OFF cases and three ON fault cases, then exposed an epoch
oracle that counted a new request in its own older-drain predicate. r5 passed
all ON cases, then exposed an omitted host cancellation lifecycle for the OFF
physical speculative read. The production sources were unchanged by all these
host/evidence corrections. No failed attempt or historical lost result is
promoted to a CPU runtime pass.

The next required gate is a real executing CPU with the actual posted cache,
coherence home and AXI response/drain path, with a same-guest OFF control. The
original benchmark bytes must remain separately pinned for any later throughput
comparison.
