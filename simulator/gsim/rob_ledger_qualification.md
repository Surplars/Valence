# FPGA-next ROB ledger full-generation qualification

This focused qualification uses `FpgaNextConfig.Candidate.coreParams` from the
frozen integration source. It emits two fresh models, changing only
`bankedRobPayload` between the register comparison and selected banked design.
No production RTL is modified.

## Reproduce

Use the already provisioned cloud toolchain; this runner does not install tools,
fetch dependencies, or rebuild shared GSIM sources:

```sh
export VALENCE_CLOUD_ENV=/path/to/verified/tool-cache
export VALENCE_GSIM_SOURCE=/path/to/verified/gsim-source
source scripts/cloud/env.sh
export GSIM_BUILD_JOBS=2
python3 simulator/gsim/rob_ledger_qualification.py
python3 simulator/gsim/rob_ledger_qualification.py --build-run --tag fpga-next-rob-ledger-full64-r1
```

The output directory must be new. The runner saves the effective full parameter
map, source hashes before and after execution, CHIRRTL, generated model C++ and
header, separate compiled objects, executable, compile/generation logs, every
positive/negative log and a receipt with SHA256 and byte counts. The native
executable can replay a case directly with `ASAN_OPTIONS=detect_leaks=0`.

## Independent oracle and bounded cases

The existing `backend.cpp` deque, architectural map and physical-identity set
remain the expected-behavior oracle. The runner creates a saved adapter header
with three observation hooks, then includes it in the new driver. These hooks
only mutate sampled DUT outputs for negative controls; no expected result,
allocation choice, transaction order or payload comparison is replaced.
Renaming the inherited `main` also requires an explicit success return.

The paired models run:

- Existing three-seed, 18,000-random-cycle ledger, including RAW/WAW, x0,
  stale/duplicate/wrong-path completion, retirement, rollback and capacity checks
- Existing trusted head trap and head system authorization suites
- Every one of 64 generation bits independently mismatched on both completion
  ports and on recovery; valid full-width owner controls still finish normally
- Simultaneous two-lane allocation, completion and retirement
- 24 complete ROB allocation wraps; 352 stale completions/recoveries against a
  newly live owner of the same index, after retirement and inclusive flush
- Two-wide payload reads at every head index, including an allocation/retirement
  pair straddling the final and first ROB slots
- Full-capacity retirement backpressure and one-free-slot partial allocation
- 97 completed-payload hold cycles under independent admission/retirement stalls,
  invalid-input poison and duplicate completion attempts
- 33 precise exception hold cycles with high-bit PC/cause/tval payloads, partial
  retirement before a fault, trap priority and reset with outstanding owners
- Thirteen negative controls per topology: PC, instruction, result data,
  retirement owner, invalid completion acceptance, specifically high-tag stale
  acceptance, source map, retirement prefix, high-tag recovery ownership, precise
  exception validity and the three inherited head/source sensitivity controls

Positive logs and complete parameter maps must match across topologies, apart
from the explicitly selected storage flag. Negative controls must return nonzero
and contain the intended independent-oracle failure anchor. Mutation controls
must also prove their mutation was applied.

## Explicit limits

Live generations start at zero. The bounded replay challenges every bit in the
64-bit authorization comparison, but cannot traverse 2^64 allocations or prove
64-bit exhaustion dynamically. Existing 8-bit exhaustion evidence is separate.
External completion producers must be reset/drained with the ledger; a stale
cross-reset producer is outside its stated contract.

The inherited focused wrapper ties completion retirement qualifiers true and
fast-head-retire false. Those integrated producer paths and real system-opcode
serialization belong to core-level checks. Instruction payloads here are opaque
non-system opcodes so that payload retention is independently testable.
This is module-level behavioral qualification, not ISA/system compliance, timing,
physical RAM mapping, synthesis, CDC or FPGA-board proof.
