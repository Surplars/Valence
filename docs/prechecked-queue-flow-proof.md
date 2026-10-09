# Prechecked translated-queue flow qualification

## Scope and proof boundary

This qualification covers the default-off `precheckedDataRequestFlow` option at
exact baseline `e8520ab23fb31cd03566787056d5e937e1aca7c3`. All fixtures hold
`physicalLoadIngressFlow=false`. Both off/on sides enable
`virtualRamLoadPrecheck`; the paired candidate changes only prechecked queue
flow. The existing issue width 2, memory entries 2, registered ingress, checked
permission boundary, owner queue and response handling are retained.

The fixtures compose actual GSIM-generated RTL:

- `adapter`: DataTranslationAdapter, real Sv39 translation service and PMP.
- `adapter-prefetch`: the same composition with actual NextLineAuthorization.
- `backend`: IntegerBackend, DataTranslationAdapter, real CSR/PMP and Sv39
  translation, driven through decoded instruction requests.

The C++ oracle independently supplies page tables, physical address expectations,
permission cases, response data, architectural register state and full ROB
`(index, tag)` ownership. It does not derive expected verdicts from DUT-private
permission or bypass wires. Exposed DUT events establish what happened and when.
These tests are not NEMU differential execution, a full CPU/fetch test, or a
formal all-input equivalence proof. There is no synthesis, routed timing, board,
Linux, installation or publication claim.

## Directed coverage

Adapter coverage includes accepted-to-physical latency; 48 continuous requests;
held physical and response payloads; queue spill with older cold/warm translated
owners; ordered mixed fault/data responses; stale epoch, MMIO/out-of-range,
store, atomic, virtualized, uncached and overrun certificate rejection;
privilege, SATP ASID/root, SUM, MXR, PMP config/address and explicit flush epoch
changes; machine/bare-mode rejection; and trusted same-epoch PA semantics.

Prefetch coverage independently expects a valid same-page next-line permit,
rejects a 4 KiB crossing, rejects a next line outside an 8-byte PMP grant despite
permission for the current word, preserves the permit under downstream hold,
and rejects hints on stores, atomics and uncached traffic.

Backend coverage includes two physically overlapping warm certified loads;
head-serial operation before/after a late certificate; held head request and ROB
slot reuse; response/request pressure; an older uncanonical load; physical-alias
store ordering; MMIO, PBMT and out-of-aperture serialization; real taken-branch
cancellation before issue, after adapter acceptance but before physical fire, and
after physical fire with the old response still outstanding during slot reuse;
SFENCE remapping; PMP CSR drain/revocation; page, access, alignment and downstream
response faults with original VA, PC and full-token exception provenance.

The accepted-then-cancelled load must drain exactly one downstream owner without
retirement. A cancelled-before-issue load must emit no physical request. Recovery
stimuli use genuine taken branches; an earlier invalid external-recovery stimulus
is retained only as failed historical evidence.

One intentional policy change is isolated: enabled flow rejects malformed
alignment or byte masks on forged certificates; default-off preserves historical
behavior. Legitimate LSU certificates cannot contain those malformed shapes.
Legal same-epoch physical addresses remain trusted certificate inputs at the
adapter; the backend producer's independent VA/PA and full-token checks cover
that contract rather than silently repeating a translation in the adapter.

## Reproduction and provenance

Run from the repository with an already verified pinned toolchain cache. Replace
the three example paths below with that cache's actual locations; these commands
do not authorize downloading or installing tools.

```sh
export VALENCE_CLOUD_ENV=/path/to/verified/cloud-env
export VALENCE_GSIM_SOURCE=/path/to/verified/gsim-src
export CHISEL_FIRTOOL_PATH=/path/to/verified/firtool-1.135.0
source scripts/cloud/env.sh
export GSIM_BUILD_JOBS=1
test "$(git rev-parse 8e78b5b^{tree})" = c82f46861725be23b8c4f68630e341b72281c05c
python3 -B simulator/gsim/prechecked_queue_flow.py --tag fresh-tag \
  --baseline-ref 8e78b5b
```

This is a fresh model build, without historical `--reuse` directories. Public
`8e78b5b` has the same source tree as the local historical `e8520ab` used by the
recorded receipt. Optional reuse is only for a separately retained, hash-verified
archive; it is not required by the fresh command.

The runner first runs `PrecheckedQueueFlowSpec` and
`PhysicalLoadIngressFlowSpec`, then builds/runs models sequentially under
AddressSanitizer and UndefinedBehaviorSanitizer. Negative controls poison
physical address/shape observation, response data, fault observation and next-line
permission; backend controls poison architectural results, full-token ownership
and the certificate physical address. A control passes only by rejecting its
specified independent-oracle mismatch.

Optional object reuse requires byte-identical FIR plus recorded generated-C++ and
object SHA256 matches and post-copy hash verification. A prior interrupted model
without a complete output manifest is rebuilt. Current source hashes are frozen
before execution and checked again at completion.

The shadow is actual RTL compiled from `git archive e8520ab`, with only the new
wrapper parameter assignment removed because that parameter is absent in the
baseline. It runs the same independent drivers and compares every reported case,
cycle count, pressure counter and trace exactly with current default-off.

## Result

PASS, 2026-10-09 UTC. Frozen receipt:
`build/gsim/prechecked-queue-flow-r4/receipt.json`.
Receipt SHA256: `3f1ea225b70ea7e158844faa19daeffd9ae4cd1739417085aa8262ffd1b42937`.

- Configuration: both suites, 4 tests passed.
- Adapter: 9 cases per side; prefetch adapter: 10 cases per side;
  backend: 20 cases per side. All paired functional checks passed.
- Actual archived-baseline shadow: all 39 cases passed and exactly matched
  current default-off in every reported field, including cycles and pressure.
- Total: 117 positive case executions and 22 correctly rejected poison controls.
- Independent artifact audit verified the 213 frozen source files plus every
  recorded FIR, generated C++ unit, model object and runnable binary hash.
- Object reuse was offered but not used: changed production source locations
  made FIR unequal, and interrupted backend output had no complete manifest.
  The reuse validator's synthetic hash-drift/interruption controls also passed.

Measured accepted-to-physical latency is 3 cycles off and 2 cycles on, with or
without next-line prefetch. All four adapter variants accept 48 requests across
47 cycles and issue them across 47 cycles: II=1 is retained, not newly obtained.
The checked and ingress register cuts remain. These are real RTL event timings.

Selected backend observations (off → on): head-serial warm 55 → 55 cycles;
head-serial cold 72 → 72; head-serial physical fault 56 → 56; backpressure
160 → 159; older uncanonical load 138 → 137; physical-alias store ordering
111 → 110; cancelled-response/token reuse 480 → 478. The intentionally held
warm-overlap case remains 115 → 115 because its fixed response-release time
masks the earlier request. These workload-specific counts are not whole-CPU
bandwidth or frequency claims.

In the enabled backend, warm overlap reaches two physical owners. The
accepted-before-physical cancellation case drains exactly one cancelled owner.
The after-physical cancellation case reuses cancelled ROB slots while the old
response is outstanding, then retires only the independently tracked live tokens.
The before-issue cancellation case emits no cancelled physical traffic; its final
reported physical count includes a subsequent new, legitimate load.

`verification-summary.json`, `artifact-audit.json`, `reuse-validation-selftest.log`
and all positive/negative logs are beside the receipt. Historical r1 failure, r2
abort and restart-interrupted r3 remain intact and are not counted as completed
qualification. No production file was edited while completing this proof.
