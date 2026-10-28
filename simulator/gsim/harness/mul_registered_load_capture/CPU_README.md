# Portable candidate CPU capture audit

This directory preserves the three fixed M/Bare audited hosts for the optional,
**default-OFF** registered MUL-load capture experiment. It is not a replacement
for the original ISA/CRC/fault oracles and does not claim all eight CPU host
families or general OS verification. See `BACKEND_README.md` for the separately
owned component harness.

## What was copied

`cpu/{common,dependent,independent}.cpp` are include-path-only copies of the
qualified candidate hosts. Their memory service, guests, cycle budgets,
retirement golden model and original negative modes are unchanged. The capture
frame/types/ledger headers are byte-identical. `aliases/` names the actual
`MulLoadOperandCaptureBenchmarkGsim` wrapper, not the old prefetch model.

The following existing public sources are reused without modification:

- `../context_fetch_prefetch/shared/{benchmark_oracle,benchmark_image,matched_memory}.h`
- `../{gsim_model_storage,isa_model,muldiv_model}.h`
- `../context_fetch_prefetch/payloads/` assembly/linker/port sources and pinned inputs.

No absolute checkout path is embedded in these sources. Changing an include
path is not authority to change a service law, oracle, payload or observed phase.

## Exact model and observation binding

The original matched comparison freshly generated both fourth-profile OFF and
sole-MUL-option ON models from the same source epoch. Context-owned instruction
prefetch and load nomination were OFF; data next-line prefetch retained its
baseline true setting. This portable **candidate-only** audit does not reuse the
older prefetch-ON opportunity model as a control.

`cpu_model_binding.json` pins the qualified candidate:

- CPP SHA-256: `9087c6cc9915a6fcc44ae764f2c8128355b8949ab4121910f1085fe6b77a5578`
- Header SHA-256: `967d6156f23189ea4e498b65e27d322659e6d2246d934d79e84c5e52766dc982`
- 137 actual capture members; the historical extraction had eight additional
  lexical false positives, which are not observation taps.
- The original eight-host business qualification separately checked 105 fields.
  This three-host portable subset is not a migration of all eight aliases/tests.

Private generated members and anonymous temporaries require real semantic
qualification. Member existence and widths alone are insufficient. The frame
uses CURRENT state and settled snapshots, including the prior accepted tail's
registered multiplier reservation and full 64-bit tag. Allocation tag locals
are the low 64 bits of exposed CURRENT `ledger.tag/tag_1` expressions. Never
substitute NEXT values or the next selected instruction's owner.

`check_cpu_binding.py` is a read-only exact pin check, not a simulator or a new
ABI proof. A changed source/generator/hash must fail pending independent field,
phase, value and ownership review; do not simply update the hashes to silence it.
Fresh generation at a different path/tool epoch is not promised byte-identical.
The source flow uses the supported qualified GSIM toolchain and initialization
byte-span fix, never Verilator. Candidate emitter:
`soc.core.ooo.MulLoadOperandCaptureBenchmarkGsimMain`; top:
`MulLoadOperandCaptureBenchmarkGsim`. Compile the generated wholeobject once
and reuse it across the three hosts after qualification.

## Parameterized host-only recipe

Set `REPO`, `MODEL`, `OBJECT`, `CXX`, and a fresh `OUT` to the actual qualified
checkout, generated directory, matching compiled object, Clang and output path.
The recipe does not regenerate a DUT, recompile its object or install tools.

```sh
H="$REPO/simulator/gsim/harness/mul_registered_load_capture"
mkdir "$OUT"
python3 "$H/check_cpu_binding.py" --model-dir "$MODEL" --report "$OUT/model-pin.json" || exit
for host in common dependent independent; do
  "$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all \
    -I"$MODEL" -I"$REPO/simulator/gsim/harness" -c "$H/cpu/$host.cpp" -o "$OUT/$host.o" || exit
  "$CXX" -fsanitize=address,undefined "$OUT/$host.o" "$OBJECT" -ldl -o "$OUT/$host" || exit
done
```

The fixed CLI is `ELF SYMBOLS MODE CYCLE_BUDGET`: common uses `smoke 100000`,
`performance 3000000`, or `validation 3000000`; dependent and independent use
`dependent-load 10000` / `independent-load 10000`. Positive acceptance retains
the original business PASS plus exactly one `MUL_CPU_CAPTURE_AUDIT_PASS` summary,
exit 0, empty stderr and no sanitizer failure. Negative modes retain their
original exact failure contract, not a fabricated final audit PASS.

The audit checks actual starts, old PRF/stable registered load values, full-token
age/kill/reservation authority, original MUL/DIV winner priority, old FU credit,
next registered capture, numerical product and retirement/cancellation lifetimes.
Zero forwarding is not manufactured coverage. Availability is not completion
acceptance. It reports zero-observation corners rather than implying they passed.

Apply execution limits separately: the qualified run used 2 CPUs, 4 GiB sampled
owned RSS, at most 900 seconds and memory/disk reserves. The bare commands above
are not that guard. External ASAN symbolization was unavailable, LSAN disabled;
ASAN/UBSAN detector functionality was qualified. A path-migration short run is a
connection/byte-continuity witness, not a fresh performance sample.

## Unchanged guest provenance and reproduction limits

Use `../context_fetch_prefetch/payloads/pinned-inputs.json` for the exact five
ELF/symbol pairs. They are the same bytes used in the new matched OFF/ON runs.
For example, performance ELF SHA-256 is
`9a8e716320ec08591fd25a2dfdf4c73b7714908ab8a190b607dc8e10cd1b43ac`, symbols
`671642be3f3323baf72147820ab26dbad86bf6c3f298f8e5aa3db4e83440e67d`.

The complete existing guest build recipe is in
`../context_fetch_prefetch/CPU_README.md` under guest inputs. Set its `H` to that
existing directory; do not accidentally use this directory for its payload path.
It records RV64IM/Zicsr/LP64 flags, assembly/link scripts, port files and external
CoreMark revision `1f483d5b8316753a742cbf5590caf5bd0a4e4777` with all six upstream
source hashes. Respect the upstream license. One iteration/2000-byte data is
**not an official CoreMark score**. This migration did not rebuild any guest;
recipe availability is not a claim that an arbitrary RISC-V toolchain reproduces
the pinned ELF/symbol hashes. A mismatch needs explicit requalification.

The matched CPU result was about +0.83% equal-clock ROI throughput on each of the
two fixed CoreMark inputs, no external I/D traffic increase, and no load-stream
change. It does not establish a frequency/area/board gain or justify enabling
the option by default.
