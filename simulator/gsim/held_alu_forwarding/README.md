# Experimental held-ALU fixture

This is a source-only, default-OFF publication of a bounded historical CPU
observer fixture. The measured configuration is A68 plus held-ALU B, with young
load sealing and raw MAC disabled. Their joint ON configuration is unmeasured.
The fixture is **not fully qualified** and makes no physical timing, board, or
performance improvement claim. No new model build or CPU run was performed to
prepare this publication.

The exact original eleven scenarios pass OFF/ON (22 runs). One separately frozen
D1 correction passes OFF/ON (2 runs): two rs1 fields change to x2 and one input
seed changes. The original fixed 4,212-byte guest remains reproducible. Two
passive trace recordings are diagnostic repeats, not additional qualification
cases. Five controls reached and rejected value, owner, replacement, trap and
stale-response corruption. Mixed-priority and kill controls remain NOT_REACHED.

The corrected ON log records P0 token 14:49 to C1 token 15:50 capture at cycle
780 exactly once; OFF records zero. C1 is accepted at 781 as P0 drains. The
multiplier at 782 and LSU at 783 use the registered descendant after that drain.
C1 acceptance and descendant grants while P0 stays backpressured, simultaneous
held rollback, multiplier/divider/system competition and mixed-priority capture
remain NOT_REACHED. Functional success does not complete those missing witnesses.

## Read-only publication checks

Run from the repository root with ordinary Python 3 (assertions enabled):

```sh
python3 -B simulator/gsim/held_alu_forwarding/check_fixture.py
python3 -B simulator/gsim/held_alu_forwarding/test_fixture.py
```

The checker verifies every included source and compact result byte,
the shared 18-file host closure, deterministic guest/control regeneration against exact hashes, historical
anchor/exit records, all five reached negative expectations, and the exact 780/781 causal
boundary. Tests deliberately break log digest format, negative reach/status and OFF
capture claims in memory. These checks never build, link or execute a model.

`evidence/results.json` is an explicit portable projection of original receipts:
it retains original receipt and raw-log hashes, parsed case values, verified
anchor presence and exits. Raw logs remain in the archived evidence closure;
local argv, cwd and environment inventories are omitted. The final projection
names the original final-combined SHA
`5ab6363f6e1c0487f115a095c96a50068f6e6ce1f1a9c2e23552a7ccee3de9df`.
The unmodified causal freeze SHA is
`ae21643c1f18e6df7bce21921e52623ed3f3a97b4de4bd3d5854967108817196`.
Its historical runner hashes are archival provenance; those local runners and
generated binaries are not part of this portable source closure.

The first D4 host schema failure and two-file correction are identified by
exact archived log/diff hashes in evidence/schema-correction.json.
The correction recognizes the actual local error/page-fault flag combination
and improves a diagnostic. D1-D3 do not use that local page-fault response path;
their earlier exact passing records remain separately identified by original
receipt hashes. Included observer sources are the corrected final revision.

## Explicit external prerequisites

Replay needs externally supplied matching OFF and ON `BoardSocGsim.h`,
`BoardSocGsim.fir` and 36 `BoardSocGsim0.o` through `BoardSocGsim35.o` objects,
plus the compatible host C++ toolchain. None are shipped. The runner checks
historical header/FIR identity, exact field specification, binding provenance,
and hashes each supplied object and tool before and after an operation. It links
one observer host translation unit; it does not emit hardware or compile any
DUT model translation unit. A different model identity fails closed and requires
separate qualification rather than inheriting these results.

Set these variables to your existing prerequisites and a fresh output directory
outside the source tree. They are examples of explicit local inputs, not paths
embedded in the fixture:

```sh
FIXTURE="$PWD/simulator/gsim/held_alu_forwarding"
OFF_MODEL=/path/to/matching-off-model
ON_MODEL=/path/to/matching-on-model
ACTIVATE=/path/to/toolchain/activate.sh
CXX=/path/to/toolchain/clang++-19
OUT=/path/to/fresh-held-alu-output
mkdir -p "$OUT/bindings"
python3 -B "$FIXTURE/prepare_inputs.py" --out "$OUT/inputs"
python3 -B "$FIXTURE/binding_memory_generate.py" --model "$OFF_MODEL" --out "$OUT/bindings/binding_memory_retained_a.json" --header "$OUT/bindings/binding_memory_retained_a.h"
python3 -B "$FIXTURE/binding_memory_core_generate.py" --model "$OFF_MODEL" --out "$OUT/bindings/binding_memory_core_retained_a.json" --header "$OUT/bindings/binding_memory_core_retained_a.h" --memory-include binding_memory_retained_a.h
python3 -B "$FIXTURE/binding_memory_generate.py" --model "$ON_MODEL" --out "$OUT/bindings/binding_memory_on.json" --header "$OUT/bindings/binding_memory_on.h"
python3 -B "$FIXTURE/binding_memory_core_generate.py" --model "$ON_MODEL" --out "$OUT/bindings/binding_memory_core_on.json" --header "$OUT/bindings/binding_memory_core_on.h" --memory-include binding_memory_on.h
python3 -B "$FIXTURE/binding_memory_verify.py" --model "$OFF_MODEL" "$OUT/bindings/binding_memory_retained_a.json" "$OUT/bindings/binding_memory_core_retained_a.json"
python3 -B "$FIXTURE/binding_memory_verify.py" --model "$ON_MODEL" "$OUT/bindings/binding_memory_on.json" "$OUT/bindings/binding_memory_core_on.json"
```

Both generators require an explicit model and exit unsuccessfully for any
required unbound field. Generated readers contain compile-time completeness
assertions. Current retirement ROB data is an explicitly optional unavailable
member; the independent ledger uses a previously checked accepted completion
value while observing the actual retirement token/instruction/PC/destination.
Physical request ownership comes from the retained tagged handle ledger.

## Host links and bounded runs

The following Bash array supplies all runtime dependencies explicitly. Every run
uses a fresh case directory and preserves logs/receipts on failure; it does not
retry or sweep phases. The bounds are 30,000 cycles and 120 seconds per process.

```sh
COMMON=(--off-model "$OFF_MODEL" --on-model "$ON_MODEL" --toolchain "$ACTIVATE" --cxx "$CXX" --bindings "$OUT/bindings" --out "$OUT/runs")
python3 -B "$FIXTURE/run_fixture.py" link --mode off "${COMMON[@]}"
python3 -B "$FIXTURE/run_fixture.py" link --mode on "${COMMON[@]}"
python3 -B "$FIXTURE/run_fixture.py" link --mode on --trace "${COMMON[@]}"
for CASE in D1-bare-p0 D2-bare-p0 D3behind-bare-p0 D3head-bare-p0 D4-sv39-p0 D5load-bare-p0 D5store-bare-p0 D6mul-bare-p0 D6div-bare-p0 D6csr-bare-p0 D6serial-bare; do
  for MODE in off on; do
    python3 -B "$FIXTURE/run_fixture.py" run --mode "$MODE" --case "$CASE" --inputs "$OUT/inputs" "${COMMON[@]}" || break 2
  done
done
python3 -B "$FIXTURE/run_fixture.py" run --mode off --case D1-bare-p0-x2-gated --inputs "$OUT/inputs" "${COMMON[@]}"
python3 -B "$FIXTURE/run_fixture.py" run --mode on --trace --case D1-bare-p0-x2-gated --inputs "$OUT/inputs" "${COMMON[@]}"
for CONTROL in value owner; do
  python3 -B "$FIXTURE/run_fixture.py" run --mode on --trace --case D1-bare-p0-x2-gated --control "$CONTROL" --inputs "$OUT/inputs" "${COMMON[@]}" || break
done
python3 -B "$FIXTURE/run_fixture.py" run --mode on --case D1-bare-p0 --control replacement --inputs "$OUT/inputs" "${COMMON[@]}"
python3 -B "$FIXTURE/run_fixture.py" run --mode on --case D3head-bare-p0 --control trap --inputs "$OUT/inputs" "${COMMON[@]}"
python3 -B "$FIXTURE/run_fixture.py" run --mode on --case D2-bare-p0 --control stale_response --inputs "$OUT/inputs" "${COMMON[@]}"
```

Optional exact passive repeats use the ON trace host with `--case D1-bare-p0`
and `--case D6div-bare-p0`. No other phase/guest matrix is implied. The original
generator retains its full scenario definition for source provenance; publication
contains exact hashes for the selected twelve inputs. All seed and control
bytes are regenerated only in memory for checks or into the external output
directory for replay; no generated snapshots are shipped.

The equivalent raw ON host link (substitute OFF_MODEL and B1_ENABLED=0 for OFF):

```sh
source "$ACTIVATE"
mapfile -t FLAGS < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["flags"]))' "$FIXTURE/build-contract.json")
OBJECTS=()
for INDEX in {0..35}; do OBJECTS+=("$ON_MODEL/BoardSocGsim$INDEX.o"); done
SHARED="$FIXTURE/../young_load_seal/posted_join_observation"
"$CXX" "${FLAGS[@]}" -DB1_ENABLED=1 -I"$ON_MODEL" -I"$OUT/bindings" -I"$FIXTURE" -I"$SHARED" -I"$SHARED/host" -I"$SHARED/host/harness" "$FIXTURE/directed_host.cpp" "${OBJECTS[@]}" -o "$OUT/raw-on-host"
```

Use directed_trace_host.cpp for the passive trace variant. The guarded runner
records the same full argv plus runtime dependency hashes in each external
link receipt. The unchanged shared host
sources are resolved by include paths instead of being copied again.

## Retained gates

The bounded architecture evaluator is not a replacement for independent NEMU,
precise PMP, original 105-field capture, tagged transport/store ownership or
fabric service gates. `evidence/retained-gates.json` identifies the original
same-object check and exact final audit. That gate reused all 36 ON objects,
preserved hot/compressed NEMU counters and retirement grouping, reached the
pc/gpr/memory negatives, and kept short/word precise-PMP assertions unchanged.
Those independent source/oracle entry points remain in the repository; this
fixture does not duplicate or modify them.
