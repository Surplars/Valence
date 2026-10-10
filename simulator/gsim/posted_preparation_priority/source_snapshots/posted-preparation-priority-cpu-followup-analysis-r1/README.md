# Strict warm followup terminal-pair analysis

This namespace prepares read-only verification of real postedPreparationPriority
OFF/ON CPU cases 0, 6 and 18. It does not execute a CPU, compile a host/model,
replay any raw parser, modify original evidence, or qualify missing warm runs.
The parent owns fresh CPU execution. Only complete real receipt pairs can create
`PASS_FULL_WARM_FOLLOWUP_FUNCTIONAL_PAIR` outputs.

## Frozen scope

- Runner: `posted-preparation-priority-cpu-host-r2`.
- Exact complete pair pins: `1451bdfbebe133f1c2fdec34aeae90c831113f7c2a3d300308b776e68dfb19fd`.
- Full case19 gate: `posted-preparation-priority-cpu-recovery-r1/case19-pair-r1.json`,
  SHA `9979624bf42c2829bf89c5007170e6b343066e3f7e756f92734cc1b8f6fa1cdb`.
- Actual focused-v3 aggregate-r4: SHA
  `48ee330f128ec12aebeafb43d521a3f8ae307a055e3896ff3f2c8332f3670baa`.
- Fixed 140-core/32-profile/11-cache-field profile; only
  `postedPreparationPriority` differs. LRU and memory frontier stay ON.
  Fetch-chain remains absent/disabled as bound by the original contract.
- Boundary join remains `UNKNOWN_NOT_RECONSTRUCTED`.

`CONTRACT.json` is hardcoded by digest into `close_pair.py`. `FREEZE.json`
binds the analyzer, contract, tiny controls, their output and this guide.
Use the separately delivered exact freeze SHA as `FREEZE_SHA`; checking the
manifest against a newly computed untrusted digest alone is not an anchor.
The frozen files are read-only. No source adjustment is needed before execution.

## Actual verification chain

The analyzer checks host source hashes before import, then calls unchanged
`run.check` on the exact complete pins and `followup_bridge.verify` on the actual
full case19 gain gate. The bridge calls the original `pair.verify`, including
case19 OFF lossless raw storage, ON actual raw artifacts, actual invocations,
full result digests, source/model/profile/guest pins, independent primary
reparse, focused gate and both ROI and total gain. It cannot accept a primary
only result or a previous variant's gain.

For each warm side, the analyzer calls original `pair.identity`, `pair.artifacts`
and `pair.measurement`. It verifies the complete actual executable/log/resource
and positive/negative raw inventory, hashes every file, independently reparses
the primary log, checks each actual native argv/exit/guard/cwd/environment,
checks native stage stdin/argv/digests/resources, and requires the exact negative
error. The entire original parser result is tied to the actual measurement's
result digest and parser source digest inventory. ON must verify the exact
focused aggregate through original `run.focus`; OFF retains `focused: null`.

The analyzer deliberately does not call `pair.one` on warm OFF because its
COPY-only `original_lru_on_reproduction` field does not exist on warm runs.
Instead it applies all relevant original checks explicitly. Every warm raw must
still exist; this analyzer does not accept archived warm inputs because the
frozen raw-storage helper only supports reproduced OFF COPY cases.

Functional acceptance requires the full original independent CPU oracles and
actual negative. A translation proof witness is reported, not demanded. Actual
zero-witness warm traces remain eligible. No speedup is required for controls.
ROI, flush-tail and total changes are reported separately. Combined timing is
`GAIN` if ROI and total are both non-regressing and one improves, `REGRESSION`
if neither improves and one worsens, `EQUAL` if both equal, or `MIXED` if one
improves and the other regresses. `strict_roi_and_total_gain` means both improve.
A functional PASS can therefore honestly carry `EQUAL`, `REGRESSION` or `MIXED`.

No cryptographic signature of original execution is invented. This is immutable
terminal inheritance with captured actual invocation and result digest, not a
second execution of raw validation. Trusted receipt/freeze/source hashes remain
part of the evidence contract. Inputs must remain quiescent during verification.

## Commands

Run from the recovery root, source the existing toolchain once, and use `python`
(not `python3`): the frozen actual stage argv binds the original interpreter
spelling. Do not replace interpreter paths to bypass that identity check.

```sh
cd /workspace/scratch/41e4a649bb60/recovery-20261010-0816
source toolchain/activate.sh
ANALYSIS="$PWD/posted-preparation-priority-cpu-followup-analysis-r1"
HOST="$PWD/posted-preparation-priority-cpu-host-r2"
GATE="$PWD/posted-preparation-priority-cpu-recovery-r1/case19-pair-r1.json"
GATE_SHA=9979624bf42c2829bf89c5007170e6b343066e3f7e756f92734cc1b8f6fa1cdb
# Set FREEZE_SHA to the separately delivered immutable freeze hash.
python -B "$ANALYSIS/close_pair.py" check-contract --freeze-sha "$FREEZE_SHA"
```

`check-contract` only verifies the frozen analysis files and prepared pin hashes.
It does not claim runtime qualification. The following optional integration
check revalidates the actual complete case19 parent gate and source/model/host
bindings, without executing a DUT or warm parser:

```sh
python -B "$ANALYSIS/close_pair.py" check-gate --freeze-sha "$FREEZE_SHA" \
  --out "$ANALYSIS/gate-binding-r2.json"
```

It reports `PASS_FULL_CASE19_GATE_ONLY_WARM_PAIRS_PENDING` and explicitly records
zero qualified warm pairs. It may read/decompress substantial original evidence.

After the parent produces real complete OFF and ON warm receipts, pass their
independently recorded exact hashes. Example for case 6:

```sh
python -B "$ANALYSIS/close_pair.py" close --case 6 \
  --off "$HOST/case6-off-r1/receipt.json" --off-sha "$OFF_SHA" \
  --on "$HOST/case6-on-r1/receipt.json" --on-sha "$ON_SHA" \
  --gate "$GATE" --gate-sha "$GATE_SHA" --freeze-sha "$FREEZE_SHA" \
  --out "$ANALYSIS/case6-pair-r1.json"
```

Use the corresponding case 0 or 18 paths and hashes for those controls. The
output path must be fresh under this analysis namespace; existing output files
are never replaced. No warm output templates marked PASS are provided.

Reverify a saved actual pair with its emitted exact hash:

```sh
python -B "$ANALYSIS/close_pair.py" verify \
  --receipt "$ANALYSIS/case6-pair-r1.json" --sha256 "$PAIR_SHA" \
  --freeze-sha "$FREEZE_SHA"
```

This rebuilds every comparison from the actual pinned inputs and requires exact
JSON equality, so tampering with timing summaries, evidence or followup records
cannot survive verification.

## Optional original LRU-ON reference equality

Add `--compare-original-lru-on` to a `close` command for an additional baseline
comparison. The contract pins prior LRU-ON receipts separately for 0/6/18. This
compares the complete OFF primary and all ten positive raw logical SHA values
against actual prior bytes and the pinned prior receipt inventory. It inherits
no historical PASS. If old raw files have been archived, supply
`--reference-raw-root /path/to/an/explicitly/restored/directory` containing the
ten actual streams. The analyzer performs no restore and accepts no old labels
or compressed manifest alone. This optional check fails if bytes are absent or
not identical, while default warm functional analysis does not depend on it.

## Tiny controls and preparation status

`test_controls.py` only tests helper-level synthetic fixtures. It exercises
identity, complete raw/executable inventory, actual parser result/stdin/source
binding, actual negative command/error, timing equality/gain/regression/mixed
outcomes, followup contract tampering and zero-witness/UNKNOWN applicability.
The unchanged followup predicate is tested with a clearly marked synthetic
upstream seam, never as real case19 verification. These controls create no
saved DUT receipt or functional pair PASS, and never call top-level `build` or
`verify`. `controls-result.json` explicitly marks zero warm pairs qualified.

Re-run controls without overwriting frozen output:

```sh
python -B "$ANALYSIS/test_controls.py" > "$ANALYSIS/controls-recheck-r1.json"
cmp "$ANALYSIS/controls-result.json" "$ANALYSIS/controls-recheck-r1.json"
```

Final delivery includes exact analyzer/contract/freeze/control hashes and any
real gate-binding-only result hash. No actual warm pair has been qualified by
preparation alone.
