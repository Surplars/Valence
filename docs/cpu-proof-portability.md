# CPU proof portability and coverage boundaries

## Tracked actual-CPU data-PMP gate

The portable entry point is `simulator/gsim/cpu_flow_data_pmp.py`, with
`harness/cpu_flow_data_pmp.cpp` and `payloads/cpu_flow_data_pmp.S`. The C++ and
assembly are byte-for-byte promotions of the previously executed data-PMP
fixture. Only orchestration, provenance checks, and output placement changed.
The existing tracked `payloads/cpu_hot_bandwidth.ld` remains its linker script.

The fixture executes real selected-board CPU instructions. An unlocked,
high-priority 8-byte NAPOT region denies one S-mode load and one M-mode
MPRV=S load. It requires exact cause/PC/tval, no retirement or accepted physical
request for either denied instruction, three permitted reads, a controlled
S-mode ECALL, two signature stores, independent read/backing values, and drained
physical/backend ownership. OFF and ON must have the same retired count and
retired-PC trace. Each side must reject trap, data, and count corruptions with the
specific diagnostic and exit code 1. Denied stores/AMOs, exhaustive PMP, NEMU
privilege compliance, active DMA traffic, and physical-board results are outside
this gate.

From the repository root, after generating a source-matched selected-board smoke
pair with the tracked `fpga_next_board.py` builder:

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/cpu_flow_data_pmp.py \
  --out build/gsim/cpu-data-pmp-proof-1 \
  --off-model-tag cpu-flow-off-proof-1 \
  --on-model-tag cpu-flow-on-proof-1
```

Each model tag is the exact `fpga_next_board.py --tag` value; it resolves to
`build/gsim/fpga-next-board-<tag>/receipt.json`. Instead, each side may specify
`--off-model-receipt PATH` or `--on-model-receipt PATH`. No old build-case name,
workspace location, model search, archive path, or fallback is embedded in the
runner. `--out` must not already exist, even when empty; resume is unsupported.
A missing/stale/wrong-profile model is an error, never an instruction to rebuild.
The runner builds only the guest and observer executables and links all validated
model translation-unit objects.

For an integration pair explicitly built with DMA line transfers and four owners,
add `--dma-line-transfers --dma-line-entries 4`. The optional
`--dma-line-yield-cycles` must also match both models exactly. Standalone defaults
remain line transfers disabled, one owner, and zero yield cycles. These settings
configure an idle DMA implementation in this CPU fixture; they do not establish
concurrent CPU+DMA correctness. OFF and ON must differ only in the physical-load
flow flag, with every declared shared setting identical. Unrelated extra flags,
undeclared DMA settings, wrong depths, and toolchain/source differences fail.

The runner reuses `cpu_bandwidth_flow_board.validate_model` and its exact expected
profile. It validates successful receipt schema/status, complete current board
source inventory, pinned toolchain/compiler, generated header/FIR/C++/object sets,
and every receipt artifact hash. Receipt hashes are checked before and after
validation. Before every command and at completion it rechecks sources, receipts,
model artifacts, guest/host tool executable hashes, produced artifacts, and prior
logs. The new receipt additionally binds the promoted fixture, linker script,
runner/helpers, explicit shared configuration, full model provenance, symbols,
binaries, commands, logs, positive cases, and six negative results. Model receipts
are never modified. Current source drift, including an emitter change since an
old receipt, requires a genuinely new matching model pair.

### Source-only checks

```sh
python3 -B -m unittest discover -s simulator/gsim -p test_cpu_flow_data_pmp.py -v
```

These tests cover CLI selection and typo rejection, source/profile/toolchain and
artifact drift, complete object sets, receipt path escape, symbols, exact witnesses,
retirement comparison, fresh output, and fully mocked success/failure/timeout
orchestration. They invoke neither a compiler nor a simulator. Passing these tests
validates runner logic; it is not a new hardware PASS. Integration needs a fresh
execution receipt from its own exact-source model pair.

The promoted C++ SHA-256 is
`caa726fa76b9d141f318861cfe705853d53f9b139d0e52e8166ab781a40d5cb5`;
the assembly SHA-256 is
`58409a4e9b9e40cb2065d3376d369910b4095a70d73f7502c64059bded39f4e7`.

## Historical extra gates remain archive-dependent

The historical reports in [CPU flow results](cpu-bandwidth-flow-results.md) are
recorded CPU-only evidence. Their original build-local runners remain archival;
an old PASS does not qualify a changed integration checkout. A separately tracked
[portable integrated NEMU replay](cpu-integrated-hot-nemu.md) now supplies an
equivalent fresh, source-bound entry point. The representative aggregate and native
comparison recipes below remain archive-dependent. Generated outputs are ignored
by Git.

- **Board hot-guest NEMU qualification:**
  `build/gsim/cpu-flow-board-nemu-r1/run_qualification.py` and
  `verify_results.py`, plus a copied/adapted `harness/` (including
  `board_nemu_observer.h` and modified `reference.h`), exist only in the historical
  build/evidence set. The runner hardcodes the old r3 hot receipt, recovered
  guest receipt, OFF/ON r1 models, and a sibling checkout's NEMU tree/shared object
  and `reference-used.json`. The auditor also depends on the original r3 logs and
  copied-source hashes. Tracked `harness/reference.h` and reference lock/config
  files alone do not reproduce these adaptations. The archived receipt records
  twelve integer M-mode physical hot cases and six PC/GPR/memory negatives.
  Architectural PCs are checked per retired instruction; all 32 GPRs are checked
  after each entire retirement edge, with full final RAM comparison. It does not
  establish per-lane intermediate GPR state, CSR/FP/VM compliance, or the current
  integration's NEMU correctness. Use the separately tracked
  `cpu_flow_board_nemu.py` entry point and its new receipt for the current
  integration; it consumes explicit fresh hot/model/reference inputs and does
  not execute this historical orchestration.

- **Representative OFF/ON suite:**
  `build/gsim/cpu-flow-representative-r1/run_representative.py` exists only in the
  historical build/evidence set and pins specific r1 OFF/ON and r3 hot receipts.
  It depends on archived model artifacts, prior RV64GC commands/products and logs.
  Its component steady, independent-line, Sv39, fetch-permission and RV64GC
  payloads/harnesses and the normal board builder remain tracked; the aggregate
  paired runner is still archive-dependent. The historical report records ten
  positives and ten explicit negatives, plus inline backing corruption checks.
  Fetch PMP and Sv39 page faults are separate from the promoted denied-read data
  PMP gate. The suite does not claim denied data stores/AMOs or exhaustive atomics.

- **Native structural comparison:**
  `build/cpu-flow-native-r1/compare.py` exists only in the historical build/evidence
  set. It needs four exact RTL-export receipts/directories and storage-census JSON
  files for physical OFF/ON and prechecked OFF/ON. The production export entry
  point `fpga/next/export.py` and `fpga/next/native_storage_census.py` are tracked;
  the comparison script and its outputs are not a tracked fresh-source gate.
  Historical comparison found only `DataTranslationAdapter.sv` changed in each
  pair, equal literal scalar-register declarations/bits, and unchanged fixed
  storage groups. This is RTL source structure, not mapped LUT/FF/BRAM, synthesized
  logic depth, timing, routed frequency, or a board-default recommendation.

The historical data-PMP receipt SHA-256 is
`087a383103fe77482cd356c7977ffa802223b74ee7fa5f8f0ff6a57905b019cc`.
The archive-dependent NEMU, representative, and native comparison receipt hashes,
respectively, are:

- `18f907a4507fe89612a207c685d19a092344af8d04e39158156563d5ed3af547`
- `523918aa2b724a898733e4f92eee8bc5605f84e12c285a2bcfa065f2804c942e`
- `423fba9e1ea52e0f9f9ba7aeb30e9a89fc565ca92065a6405c7a24c681aa684d`

These fingerprints identify historical records. They are not allow-list overrides
for current-source validation, and a clean clone does not contain the required
archival output directories.
