# Optional tagged completed-store returns

`taggedStoreReturns` remains **false by default**. The explicit ON profile retains
the published two-issue board, four LSU entries, two cache response entries,
two read MSHRs, four DDR read transactions, two write credits, two pending proof
rows, and two early-load credits. The published comparison parent is
`d1a0d1f5406220dade7f273dcf45c188eaa5f38f`, tree
`290d170dbf1a45c4b48fbb16dbc727056219ca10`.

The bounded change lets an already completed ordinary integer store hit return
past a physically earlier accepted ordinary integer read whose result is not
available. Physical request/response-ticket age is distinct from ROB age. In the
measured profile it transports a three-bit return handle and retains each owner's
full 68-bit ROB token, payload and fault metadata. Its seven-value namespace is
four integer LSU owners, two StoreBuffer drain owners and one FP-domain owner.
Generically, H = memoryEntries + storeBufferEntries + (fpEnabled ? 1 : 0),
handleBits = max(1, ceil(log2(H))), and the lookup table has 2^handleBits rows.
A handle is neither a ROB token nor a cache-data/MSHR index. Posted requests,
SB drains, FP requests, errors and barriers do not gain the completed-store exception.
A stalled selected reply retains its selected ticket and complete payload.

Ownership comes from registered state. Cache holes and downstream owner entries
cannot be reused merely because they return on the same edge. Local store ACKs
and actual cache/store drains remain distinct. Existing precise fault, checked
PMP, CSR serialization, cancellation/drain and SEAL-to-replacement cuts remain.
The bounded READY/PMP/SEAL source/native review passed; it is not formal
equivalence or timing analysis.

## Measured results

These are about **0.5% throughput improvements**, not a major solved bottleneck.
The two service laws are separate comparisons with their own unchanged baseline.

| Case | d1 total cycles | ON ROI | ON clean tail | ON total | Total delta |
|---|---:|---:|---:|---:|---:|
| Sv39, original independent R/W law | 238151 | 228764 | 8187 | 236951 | -1200 |
| Bare, original law | 260694 | 252648 | 8046 | 260694 | 0 |
| Sv39, fixed whole-burst law | 237773 | 228386 | 8185 | 236571 | -1202 |

The original d1 Sv39 total is 229966 + 8185. The fixed-law baseline is 237773;
older 239050 measurements are not this baseline. Guest, operation, 65536-byte
payload, two repetitions and original service parameters are unchanged. The
fixed law selects the newest eligible transaction at a returned-burst boundary
and retains that ID through actual LAST fire. It does not retune latency or beat
spacing. The original law permits the original independent response scheduling.

One actual ON board model, generated as 37 official GSIM C++ translation units,
served all cases. Bare reused the original binary; the fixed-law case relinked
only the host with its existing alternative DDR header. Every case checked
49157 exact full-token/reply lifecycles and the complete original byte oracle.
Both Sv39 cases observed 1008 completed-store bypasses. They are mechanism
coverage, not 1008 independent critical-path savings. Bare exercised 24577 local
StoreBuffer ACKs and 24577 independent drain lifecycles, with zero cycle benefit.
Original read-data, final-memory and unexpected-trap controls rejected with their
specific anchors under both service laws. All 105 original result fields remain
parsed and checked. FP backend execution was not exercised by these board cases.

Six focused OFF/ON models cover chain, boundary and posted-home behavior,
including independent owner, byte, held-result, error, cancellation, posted,
fallback and MMIO/domain checks. Focused MemoryOperation authority is a synthetic
premise; it is separate from integrated CPU execution. Generic OFF has paired
focused and configuration coverage, not a new whole-board OFF RTL equality claim.

The native declaration census is scalar state +147 bits, array state -81 bits,
net retained declared state **+66 bits**, instances -10, internal port bits -213,
and top-level ports unchanged. These are not mapped FF/LUT/BRAM/DSP, area, power
or STA results. No new physical implementation, board/MIG validation or frequency
claim follows from this publication.

## Reproducible source entry points

The [focused launcher](../simulator/gsim/tagged_store_returns.py) retains the tested
model bodies and mutation controls. `--preflight-only` now returns before output
creation. The [board launcher](../simulator/gsim/tagged_store_return_board.py)
provides the explicit ON profile and has a default `plan` stage. Paths are caller
parameters, not historical workspace locations:

```sh
python3 simulator/gsim/tagged_store_return_board.py plan \
  --source-root "$PWD" --toolchain-root /path/to/pinned/toolchain \
  --activate /path/to/pinned/toolchain/activate.sh \
  --guest-root /path/to/original/guest \
  --model-root /path/to/model --output /path/to/fresh/output
```

`plan` and `--preflight-only` execute no hardware tool. The plan includes complete
source, guest, host, tool/library and command identities. The contract pins every
active Scala/build input, all constructor/fabric fields, compiler flags, original
and fixed-law baselines, and the original guest hashes. `--tool-bindings` can
supply the seven supplemental tool/library paths when executables are supplied
individually; their logical keys are listed in `tool_inputs`. `--system-llvm`
overrides the usual system library location. The optional activation script is
also hashed. `verify` additionally checks the recovered qualified model, every
one of its 37 object files, and the pinned tool identities without executing it.

For an independently authorized fresh replay, use fresh output/model paths:
`freeze`, then `constructor`, `emit`, `generate`, `compile`, `sv39`, `negatives`,
`bare`, and `fixed`. Every executing stage also requires `--execute`. The compile
stage requires `--baseline-model` pointing to the exact recovered d1 model for
its generated semantic binding. Each stage preserves failures, refuses implicit
retries, rechecks input identities, and binds each model object's dependency
closure before advancing. `host-controls` contains the supplied standalone
owner/getter/ledger/service controls. It does not run a board model.

The [host map and full contract](../simulator/gsim/tagged_store_return_board/contract.json)
assemble 17 host/control leaves, reusing 10 existing byte-identical files and
adding seven changed leaves. No dead historical runner is copied. The full
13-file tested C++ include closure is supplied. The result parser is byte-identical
to qualification; the tagged capture and fixed-law service function bodies are
identical. Fifty-four historical command records match modulo path relocation.
The new portable board launcher has **not** executed a DUT build or runtime;
its publication bridge used source/CLI/config/mutation/body-identity checks and
read-only parsing of the existing qualified results.

Nineteen older test leaves now accept exactly the added default-false field
(58 profile fields and 151 core fields). All earlier expressions are preserved;
the frontier fixture still compares its original 136 named values exactly.
One Scala/test compile and 11 affected pure ConfigSpec suites passed all 36 tests.
Seven lightweight Python bridge tests and 38 Python profile checks passed.
The rollback profile helpers require the new field to be present and strictly
false in current complete output; historical manifests remain byte-frozen.
Missing, enabled, numeric and extra fields are rejected. No GSIM or 37-TU rebuild was done
for these publication-only changes.

## Evidence and recovery

[qualification.json](../simulator/gsim/tagged_store_return_board/qualification.json)
records the original qualification receipts, production hashes, structural-review
identity and persisted recovery identity. Generated models, objects, binaries,
native RTL, raw streams and raw logs remain in the separately retained recovery
package. They are not source-publication files. The original constructor-only
CLI-whitelist failure remains preserved alongside the repaired qualified attempt.
