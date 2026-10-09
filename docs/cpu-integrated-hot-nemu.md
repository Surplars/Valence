# Integrated CPU hot-guest NEMU replay

This runner qualifies the six fresh 4/8 KiB read/write/copy guests on both existing
selected-board CPU physical-ingress OFF/ON models. Both models must configure DMA
line transfers, four owners and zero yield. DMA is **CONFIGURED BUT IDLE** for
these guests. This is not concurrent CPU/DMA NEMU coverage.

The runner never generates a model, compiles a model translation unit, builds or
installs NEMU, modifies RTL, or recovers historical guest images. It compiles only
the observer harness, links the model's existing object files, and executes the
short guest cases serially. Preflight is read-only and is the default; `--run` is
required to enable links and simulations. Obtain the assigned compute slot first.

## Explicit inputs

Required inputs are:

- `--flow-receipt`: a completed `valence-cpu-physical-flow-board-v2` receipt,
  produced with fresh source guests and explicit same-source model reuse.
- `--reference-cache`: the existing pinned NEMU cache directory containing
  `reference-used.json` and `nemu-src`. There is no implicit cache fallback.
- `--root`: the current source tree, inferred from the installed runner by default.
- `--out`: a new output directory, required only with `--run`.

For the integrated run, the flow receipt is normally
`build/gsim/cpu-bandwidth-flow-board-integration-r1/receipt.json`. The runner follows
its explicit fresh guest manifest and model receipt paths; no archived r3 or
recovered guest path is consulted. It rejects unfinished model or hot receipts.

Example, from the current repository, after setting `REFERENCE_CACHE` to the
verified existing cache:

```sh
python3 -B simulator/gsim/cpu_flow_board_nemu.py \
  --flow-receipt build/gsim/cpu-bandwidth-flow-board-integration-r1/receipt.json \
  --reference-cache "$REFERENCE_CACHE"

# Only after the serial compute slot is assigned:
python3 -B simulator/gsim/cpu_flow_board_nemu.py \
  --flow-receipt build/gsim/cpu-bandwidth-flow-board-integration-r1/receipt.json \
  --reference-cache "$REFERENCE_CACHE" \
  --out build/gsim/cpu-flow-board-nemu-integration-r1 --run

python3 -B simulator/gsim/verify_cpu_flow_board_nemu.py \
  --receipt build/gsim/cpu-flow-board-nemu-integration-r1/receipt.json \
  --summary build/gsim/cpu-flow-board-nemu-integration-r1/summary.json
```

An optional first bounded run can use `--variant off --case read-4096`; this runs
that positive and its three checker corruption negatives. The receipt is
`PARTIAL_PASS`, never full qualification. Continue with the same inputs/output,
`--run --resume`, without the case/variant filters. A complete runner pass invokes
the read-only final audit before returning success. A separate summary never
overwrites an existing file or the run receipt.

To relocate the full source and evidence tree, use `--root NEW_ROOT` and
`--recorded-root OLD_ROOT`. Only paths contained in the recorded source-root
prefix are remapped. A relocated compiler requires `--compiler /path/to/clang++`;
its resolved executable must have exactly the original attested SHA-256. Keep the
C++ driver spelling for invocation: replacing a `clang++` symlink with its real
`clang` target changes C++ linking semantics. The driver target is rechecked before
every step. The reference cache location is always explicit.

## Fail-closed evidence binding

Preflight and resume validate:

1. Exact current hot and board source inventories and all recorded source hashes.
2. The fresh guest builder, payload source copies, six configurations, symbols,
   objects/ELFs/binaries/headers, and all 24 build-log hashes.
3. Both complete model receipts, matching source inventories, selected settings,
   DMA depth4/yield0, correct CPU OFF/ON flag, compiler/toolchain, exact generated
   C++/object set, model/header/FIR/object and other artifact hashes, and step logs.
4. All original hot binary, guest, log and result bindings. Link flags are
   compared against a constructed fixed command; recorded commands are never
   executed. The fixed 100 MHz conversion and DDR timing parameters stay intact.
5. The copied checker sources and corresponding current production origins.
6. The existing NEMU library, reference-used attestation, lock, requested/resolved
   config, resources, and exact 671-file source/config/runtime-library manifest.
   Of those hashes, 455 were already bound in the prior audited NEMU receipt;
   216 supplementary source/config/tree files were pinned at preparation. Unused
   intermediate files beneath the cache's build directory are not execution
   inputs. There is no download or rebuild fallback.

Every replay step records command, exit code, elapsed time, log SHA-256 and output
binary SHA-256. Source/reference inventory changes and byte drift reject replay.
Timeouts and failures remain in the receipt and are preserved on retry. Strict
resume validates logs, commands and artifacts instead of trusting completion
markers. Full audit requires exactly 12 positive and six negative cases, validates
every command/result binding, and compares each HOT_RESULT exactly with the fresh
flow run. The qualified paired PC trace and final memory extent must agree OFF/ON.
A historical commit ID is descriptive only; content hashes determine matching.

## Architectural observation boundary

The NEMU observer and shared reference client are byte-identical to the previously
verified observer/client. The only current harness adaptation is the production
HOT_RESULT split into total physical reads minus architectural loads and source
reads minus architectural loads. Historical files and receipts are preserved.

- Every actual guest retirement lane compares its PC with NEMU before exactly one
  independent reference instruction step. No request acceptance or speculative
  load steps NEMU; there is no mismatch repair or resynchronization.
- The callback observes retirement candidates before their edge applies. All 32
  GPRs are compared at the following callback, after the complete retirement edge.
  On a dual-retire edge this is the state after both instructions; there is no
  claim of an intermediate per-lane GPR snapshot.
- Fixed ROM PCs and integer effects are independently specified. UART setup is
  not executed in NEMU. The reference starts the guest with x1=0x80000014,
  x5=0x80200000, x6=0x10000000, x7=7 and all other GPRs zero, plus the audited
  machine reset state. No DUT state seeds the reference.
- Final RAM comparison covers every byte in [0x80200000, 0x80600040), including
  code, initialized data, signatures and zero gaps, after guest fences/flushes and
  DDR write drain. Observed DDR writes outside the aperture reject the case.
- One final observation cycle applies/checks the done-marker retirement edge and
  any other instruction retiring on that same edge. It does not extend the hot
  kernel, drain or flush measurement windows; later retirement candidates do not
  enter NEMU.
- Existing request/permission/full-token/data and speculative guard observers stay
  enabled. Each model runs observer-side PC, GPR and memory corruptions on the
  read-4KiB guest. Each must exit 1 with its specific mismatch message and must not
  emit NEMU_PASS.

These checks cover integer physical M-mode guest execution. They do not establish
CSR/FP/VM execution, concurrent CPU/DMA NEMU, Linux, real-board behavior, physical
FPGA timing/resources, routed frequency, or a full regression.

## Source-only tests

```sh
python3 -B simulator/gsim/test_cpu_flow_board_nemu.py
python3 -O -B simulator/gsim/test_cpu_flow_board_nemu.py
```

Tests build tiny synthetic receipt/file fixtures and replace subprocess execution.
They do not compile or simulate hardware, execute NEMU, or qualify the integrated
model. The default read-only preflight is likewise not an execution pass.

The extra C++ sources and headers are contained under
`simulator/gsim/harness/board_hot_nemu/`. None is added to the harness top-level
`*.h` set, so applying these source additions does not alter the existing model
or hot-flow source inventories.
