# Context-owned instruction prefetch: integration draft

Status: source draft only, 2026-10-27. No compilation, elaboration, GSIM, mapping,
commit or publication has been performed for this draft. No safety, IPC, bandwidth,
area or timing result is established by this document.

## Configuration and ownership

`contextOwnedInstructionPrefetch` defaults to false in `FpgaNextConfig` and
`OooParams`. The explicit `FullR1M3ContextFetchPrefetchExperiment` profile is
currently exactly `FullR1M3EfficiencyRefactor4` plus that flag. The separate
`ExperimentalContextFetchPrefetch` memory policy requires the flag and all inherited
geometry/permission contracts; old policies reject the flag. All old named profiles
remain false. No board factory silently enables this experiment. The fifth resource nomination is retained as a separate reproducible profile,
not inherited by this experiment: its measured resource result was mixed-negative.
The context-prefetch profile explicitly retains nomination OFF; fifth retains context OFF.

No demand-owner, result-ledger, cache/Home credit, issue/writeback width, ISA/FP,
PMP or VM capacity is changed by the integration. The legacy instruction prefetch
flag stays false. Cache/translation implementation is owned separately from this
integration change.

## Observer and controls

`RegisteredFetchPacket.io.speculationCancel` exists only when the flag is true.
Its value is exactly the existing `cancel || rawCorrection` expression. It is an
observer, not a replacement cancellation predicate. `IntegerCore`, `MachineCore`,
and `MappedMachineCore` forward it as optional `fetchSpeculationCancel` outputs.
There is no new input into their original frontend control path.

The tile connects both adapter and cache `speculationKill` to the union:

- packet cancellation/raw correction;
- core redirect and trap;
- fetch invalidation, fetch pause, VM flush and FENCE.I flush;
- recovery, runtime park stop-admission and external hold.

The adapter's full 64-bit `speculationMinimumSequence` and boolean
`speculationAgeUsable` connect directly to the cache. The adapter receives
`speculationDrained = frontend.quiescent && adapter.idle && cache.idle &&
!frontend.memory.request.valid`. These optional ports are absent when disabled.
There is no independent queue and no permission to withdraw held TL A or discard
joined demand completion. Kill/age only qualify optional speculative opportunities
and installation; ordinary request/response ownership is retained.

Existing backend drain behavior (not modified here) decodes PMP CSR access,
MRET/SRET, satp/SFENCE and FENCE.I heads. `pauseFetch = drainFetch || barrierActive`;
system admission requires `!drainFetch || fetchQuiescent`. Thus full fetch-idle
must include speculative accepted-before-A, held-A, all eight D beats, held
completion, joined reply and fallback lifetimes. Automatic traps are independently
included in K and are not assumed to await that drain. No unsupported warm-reset
or debug behavior is inferred.

## Physical metadata / authorization

The coordinated physical context ABI retains `privilege: UInt(2)` unconditionally.
With `withSpeculationContext=true` only, it additionally carries
`sourceSequence: UInt(64)` and `identityTranslation: Bool`. Identity provenance is
captured M/Bare mode, never virtual/physical address equality. The tile passes the
new constructor flag through translation, physical request buffering and cache;
the buffer keeps metadata attached to the original request handshake. Privilege
consumers must select `.privilege`, not use packed context as privilege.

The tile supplies its existing explicit physical side-effect-free RAM ranges to
the cache. Config/policy validation rejects missing ranges and ranges outside the
actual RAM aperture. Cache-side full-next-64B Execute-PMP, no-4KiB-crossing,
single-credit/no-chain checks are separate required implementation contracts.

The agreed cutoff is `C = nextToken + publicRequest.valid` on K, including an old
held unaccepted offer. Wrap ambiguity/rebase may change only new cutoff state,
never the existing demand `nextToken`, `nextResult` or ledger. The cache's old
address shortcut is permitted only when *both* prefetch features are disabled;
new speculation uses the original locked whole-payload arbitration.

## Draft verification surface

- `ContextFetchPrefetchSpec`: exact one-flag inheritance, old-profile exclusion,
  malformed configuration/policy rejection, 2-bit versus 67-bit physical context,
  optional packet observer, actual tile optional controls/range policy.
- Existing pure profile descendant sets explicitly include the new descendant;
  their architectural expectations and data oracles are otherwise unchanged.
- `ContextFetchPrefetchBenchmarkGsim`: same passive CPU fixture and coherent-D
  benchmark input as fourth, same `[0x80200000,0x80220000)` safe fetch range.
  This is only source preparation, not an executed benchmark or safety oracle.
- Independent directed behavioral tests are still required for held offers,
  same-cycle kill/join, late D error and fallback, wrap, full drain and permission
  denial; their golden permission decisions must not read DUT authorization bits.
- OFF whole-graph equivalence and normal external top ABI still require actual
  elaboration/normalization evidence after the complete batch is frozen.
