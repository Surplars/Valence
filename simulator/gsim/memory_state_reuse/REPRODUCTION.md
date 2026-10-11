# Reproduction and historical execution boundaries

Current status: **PASS_NATIVE_FOCUSED_MODEL_GC_CPU19_CPU21**. This integration
checkout has run only the source materializer and its rejection controls, with no
build, native elaboration or DUT execution. Existing hardware evidence
belongs to the exact original source, tools, model and execution namespaces in
[the evidence index](../../../docs/experiments/memory-state-reuse-evidence.json).
Copying their source into this checkout does not transfer their execution identity.

## Portable source and independent host checks

The following commands need only this checkout, Python 3 and a C++20 compiler.
They are reproduction instructions, not a record of execution in this checkout.
Use a scratch output directory; never put executables or traces in the source tree.

```sh
python3 -B simulator/gsim/test_memory_state_reuse_cli.py
python3 -B simulator/gsim/memory_state_reuse/test_contract.py
python3 -B simulator/gsim/memory_state_reuse/test_address_lifecycle.py
python3 -B simulator/gsim/memory_state_reuse/verify_default_off_source.py
work_dir=$(mktemp -d)
inputs_dir="$work_dir/source-inputs"
python3 -B simulator/gsim/memory_state_reuse/materialize_sources.py --output "$inputs_dir"
clang++-19 -std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all \
  "$inputs_dir/simulator/gsim/memory_state_reuse/focused/test_state_oracle.cpp" \
  -o "$work_dir/test-state-oracle"
ASAN_OPTIONS=detect_leaks=0 "$work_dir/test-state-oracle"
clang++-19 -std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all \
  -DROB_ENTRIES=64 -DPHYSICAL_REGS=64 -DLSU_ENTRIES=4 \
  -DRECONSTRUCT_ISSUE_TOKEN_INDEX=1 \
  "$inputs_dir/simulator/gsim/memory_state_reuse/cpu/test_resource_index.cpp" \
  -o "$work_dir/test-resource-index"
ASAN_OPTIONS=detect_leaks=0 "$work_dir/test-resource-index"
```

The standalone index positive includes deliberate internally caught corruptions.
Also run `--bad-index`, `--stale-tag` and `--bad-class` separately. Each must exit 1
with its intended diagnostic, respectively `fixed queue index outside active
geometry`, `unissued live full-token mismatch`, and `unissued live
immutable owner changed`. A sanitizer failure or an arbitrary nonzero exit is not
an accepted negative. Preserve stdout, stderr and exit codes in a new receipt.
The historical test writes its class-control trace at
`/tmp/resource-index-class-negative.jsonl`; use an isolated temporary environment
or rebind that path in a new test revision before concurrent launches.

`focused/test_state_oracle.cpp` uses only the independent row oracle;
`cpu/test_resource_index.cpp` uses the handwritten Guard mock and the real observer
adapter. Neither needs generated model headers or a DUT object. These host checks
do not establish hardware behavior. The lifecycle algebra deliberately includes
transitions unavailable on a physical allocation edge; actual DUT coverage and
the same-row exclusion are described in `focused/QUALIFICATION.md`.

## Reuse exact baseline inputs before compiling a host

`source-inputs.json` explicitly lists 39 reused inputs and 60 retained source
inputs. It avoids adding 263,604 duplicate bytes. `materialize_sources.py` copies
all 99 into an absent or empty output directory outside the checkout, using the
repository-relative paths in the manifest. Every source is size/SHA256 checked
before writing. The output is a historical changed-file overlay, not a complete
repository. Its 89 historical changed files match qualification8d9bc67 exactly;
ten native reproduction files match their original source snapshot. The original
README is preserved as `historical-source-contract.md` solely to reconstruct the
historical overlay while this checkout's README carries current status.

Use the command above before either C++ host check, or explicitly:

```sh
python3 -B simulator/gsim/memory_state_reuse/materialize_sources.py --output /tmp/memory-reuse-fresh-inputs
python3 -B simulator/gsim/memory_state_reuse/test_materialize_sources.py
```

The materializer and four rejection scenarios (hash mismatch, source/destination
path escape, occupied output) passed source-only checks. All99 reconstructed file
bytes were compared with the original snapshots after removing the duplicate
candidate additions. No existing baseline file, tested runner, frozen artifact or
runtime semantics changed. The new adapter, wrappers, unique oracles and actual
state accessor remain source files. Reused host.cpp/headers and census helper are
restored at their original relative paths before execution; tests are not omitted.
The 39 exact source mappings are the rows with `reused_baseline_input=true` in
`source-inputs.json`. Historical input hashes remain mandatory after relocation.

## Small source fixtures versus generated models

No generated Board/focused model `.h` or `.cpp`, FIR/RTL, ELF, object, executable,
raw log, raw trace, or `out`/`build` output is added by this candidate.

The table names the reconstructed inputs; aliases and guest symbols are supplied
from exact baseline files through the materializer, without duplicate Git copies.

| Source input | Bytes | Purpose and dependent source |
|---|---:|---|
| `focused/state_abi.h` | 10,193 | Regenerable inline ABI accessor snapshot; included by `focused/memory_state_reuse.cpp`; contains no model or step implementation |
| `cpu/host/abi.hpp` | 393 | Handwritten historical field alias; included by `cpu/host/host.cpp` |
| `cpu/host/admission_getters.hpp` | 322 | Handwritten profile-bound field alias; included by `cpu/host/host.cpp` |
| `cpu/host/worksets_symbols.h` | 506 | Pinned guest-address symbols; used by `cpu/host/host.cpp` and `roi.hpp` |
| `cpu/unissued_guard_fixture.hpp` | 3,819 | Handwritten Guard mock; used by `cpu/test_resource_index.cpp` |

Historical `state_abi.h` SHA256 is
`dc7d0b17fb765006fb28866697306b0cd023a730f6bfb816e96d83a6be57b4ce`.
Its actual focused model header input SHA256 is
`d6e1fb2b6806f79c7a048611de706ff01f50f92e9311e7bd4682d2b3e1a43afc`,
and profile SHA256 is
`406837cd2a8f4bce86c7ec5330d3d2148082860fa2c842bf2a0036b9c873f88e`.
The historical header remains external evidence. A new actual model must regenerate
the accessor in the new focused execution namespace before its host is compiled:

```sh
python3 -B /new/run/focused/generate_state_abi.py /new/run/focused/model-on-on-r1
```

The model directory must contain its freshly generated
`PostedPreparationPriorityGsim.h` and bound `profile.json`. The script checks the
explicit ON/ON ROB64/tag64/LSU4 profile and exact supported field layouts, writes
`state_abi.h` plus `state-abi.json` beside itself, and rejects unknown layouts.
Copy the generator into the new namespace first. Do not run it against or overwrite
the original historical namespace, and do not reuse a snapshot on an unbound model.

## Bound native, focused and CPU workflows

`native/run_native.py`, `focused/run_step.py`, `focused/run_matrix.py`, `cpu/run.py`,
`cpu_split/run.py` and `cpu_case21_retry/run.py` are byte-preserved historical source. Their HERE/BASE paths,
immutable source HEAD checks, compiled classpath inventories, guest, baseline raw
resolvers, external parser imports and tool pins intentionally name the original
execution layout. They are not turnkey scripts to run in these new repository
subdirectories. Historical `PLAN.md` documents retain their then-pending scope;
the current evidence index supersedes their status statements, not their receipts.

To reproduce in another workspace:

1. Restore baseline tree `7cca8ba3f646732120fd29c3206bd07fb68b9359` and the original
   source/test commits or their source archives. Restore the exact toolchain,
   independent baseline guest/parser inputs and required historical evidence.
2. Create fresh external native, focused, original-CPU and split-CPU namespaces.
   Materialize the source overlay first, then copy its scripts there; explicitly rebind all SOURCE/BASE/DONOR/
   ORIGINAL/CLASSES/HISTORICAL/SMOKE paths and imported helpers. `cpu_split` uses
   the byte-identical fixture/host sources stored under `cpu`; copy those too.
   `native/fixture` is the exact source fixture, not an emitted model.
3. Record the modified runner and source identities. Generate a new plan, source
   freeze, tool inventory and runtime binding; never edit a historical receipt or
   disable a hash/geometry check to make a relocated path pass. A new integration
   source HEAD needs new source/runtime evidence even if `src/main` is identical.
4. Rebuild only within the coordinator's granted resource slot. Emit the actual
   model and regenerate/validate its profile-bound ABI. For Board split emission,
   retain official `--cpp-max-size-KB=4096`, compile all numbered TUs serially with
   the original sanitizer flags, and link every object. Recheck actual header
   deltas and every member layout. The approximate split threshold is not a hard
   TU size limit.
5. Preserve all positive and intended negative receipts, raw digests and the
   original failed join/allocation classification boundary. A repeated historical
   parser result is not a new DUT execution. CPU cases19/21 require their original
   full oracles, stdout and 18 raw sidecars; a mismatch blocks exact equivalence
   and invokes the full original parser.

The existing qualification scripts require external resource monitors and strict
CPU contracts from prior stages. Those dependencies are source/evidence inputs,
not a reason to substitute a mock CPU or a reduced oracle. Their precise paths and
hashes are in the original native runtime and split pins referenced by the evidence
index. Original source archives, native output and focused/model evidence remain
separate from the small Git publication candidate.

## Current case21 retry entry

The first case21 attempt stopped at the old 1.1 GiB output budget. Its partial
output remains archived. The fresh case21 retry passed at 345578/5565 with all
18 original raw streams, both stdout files and the complete primary result exact;
the original trap negative exited 1 as intended. Use `cpu_case21_retry/run.py`
with its exact `contract.json` copied to the fresh external retry namespace.
The source materializer reconstructs the historical99 inputs; these two new retry
files remain direct source inputs alongside it. The retry imports the original
split runner, reuses the same model/host/guest/oracles, raises only case21 cap to
1.5 GiB with 2.2 GiB admission and preserves the 700 MiB floor. The old split
runner's case21 command is historical evidence, not the current recommended entry.
See [the retry budget and binding](cpu_case21_retry/README.md). Do not recompile
or replace a tested host to accommodate this source-preparation change.

Case19 is PASS with exact original cycles, both stdout streams, all18 raw sidecars
and the original trap negative. Raw restoration uses corrected map-r2 and the full
archive `libfile_1269dafb49b48191af36f4dc99be531d` version0. The earlier40513 archive
contains unique observer evidence only. The corrected collection is
`libfile_265665fe4118819192b906205878fe5d` version0; the earlier mapping is preserved
and superseded, not rewritten.

Case21 raw restoration uses the original full archive
`libfile_4b5d31cb153c8191979eca7d1f735fde` version0, 169697280 bytes, SHA256
`856930c56ff7e71c559082ef079868038cb6a79987e8714bbf041697a19c8f13`.
The pinned case21 recovery map verifies all18 hashes and sizes: nine positive
streams are `gzip/<name>.gz`, while nine negative streams remain at
`evidence/posted-preparation-priority-cpu-host-r2/case21-on-r1/<name>`.
Preserve these storage/decoding distinctions when restoring; the retry terminal
receipt binds the uncompressed original stream identities.
