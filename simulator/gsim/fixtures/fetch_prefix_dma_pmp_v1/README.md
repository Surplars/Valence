# Fetch-history + older-prefix: executed copy-DMA and data-PMP gates

This isolated wrapper reuses the byte-identical existing independent inputs:

- `fixtures/cpu_dma_execute/cpu_dma_execute.{S,ld,cpp}`: CPU-executed copy-DMA
  descriptors, two dirty source/destination generations, scratch loads **and**
  stores while DMA is busy, actual denied AXI R response, error/drain/restart,
  complete-token ownership and independent load/store/final backing oracles.
- `payloads/cpu_flow_data_pmp.S`, `payloads/cpu_hot_bandwidth.ld`, and
  `harness/cpu_flow_data_pmp.cpp`: denied S-mode and M-mode MPRV=S data reads,
  exact trap PC/cause/tval, no forbidden physical requests, retirement trace,
  full backing and owner drain.

No guest, harness, expected data, runtime CPU request injection, production
source, old helper, old fixture or old receipt is modified. The old flow helper
cannot represent the fetch-history plan, so this runner directly calls the
frozen `cpu_order_replay_history_v1/strict_validation.py`. It does not delete
unknown fields, normalize a history receipt into a different profile, or patch
an imported validator. Historical commands/logs are checked by the frozen
`fetch_context_qualification_v1/binding.py`. Both dependencies and all retained
oracles are hash-bound before import and guarded throughout execution.

## Exact admitted pair

Production: `2288c7f008e9d6440e8a28e339da28152b54892a`.
`src/main` tree: `c6e69b6b539bc36285b602a39fae32cb76ea012c`.
Qualified test host ancestor: `722a629fae1200074b363d84f431b77cda4e2560`.

Supply the completed receipts explicitly:

- OFF: `build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json`
- ON: `build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json`

Both fix fetch previous-packet ON, physical ingress ON, LSU4, selected board,
coherent copy-DMA line4/yield0, smoke-only/passive probes and RV64GC provenance.
Only older-prefix retirement differs. Complete source inventories, receipt
hashes, all generated files/objects/artifacts, historical recipes, every log,
status, exit codes and positive/negative anchors must match. Current production
source content and inventory must still match the production tree.

## Source-only preparation

From the repository root, use the existing pinned tools; no installation:

    TOOLROOT=/workspace/scratch/41e4a649bb60/Valence/simulator/build/cloud-env
    export PATH="$TOOLROOT/bin:$TOOLROOT/sysroot/usr/bin:$TOOLROOT/sysroot/usr/lib/llvm-19/bin:$PATH"
    export CPATH="$TOOLROOT/sysroot/usr/include"
    F=simulator/gsim/fixtures/fetch_prefix_dma_pmp_v1
    PYTHONDONTWRITEBYTECODE=1 python3 -B "$F/test_validation.py"
    PYTHONDONTWRITEBYTECODE=1 python3 -B "$F/run_fixture.py" --prepare \
      --off-receipt build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json \
      --on-receipt build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json \
      --out "$F/evidence/prepare-r2"

Preparation checks sources, all model artifacts, history, tool executable hashes
and versions, generated-header schema and exact profiles. It does not assemble
a guest, link a harness or execute a model. It records
`PREPARED_NOT_EXECUTED`, never a functional pass.

Source-only synthetic tests reuse the frozen model/history suite while moving
all test files into this new fixture directory. Additional tests reject unknown
profile fields, wrong prefix side, running receipts, symlinks, missing/changed
model artifacts, recipes/logs/status/exit mutations, source/oracle drift, every
guest artifact/command mutation, malformed/duplicate result fields, missing DMA
witnesses, changed PMP retirement traces, sanitizer reports, false-success
negative logs, and extra include-shadow files. Synthetic acceptance tests are
not hardware qualification.

## Ready command, only after heavy-slot admission

Using the environment above and a fresh output:

    PYTHONDONTWRITEBYTECODE=1 python3 -B "$F/run_fixture.py" --execute \
      --off-receipt build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json \
      --on-receipt build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json \
      --out "$F/evidence/execute-r1"

This builds the two unchanged guests once with pinned existing GCC, assembler,
linker, preprocessor, objcopy and nm, then sequentially links four unchanged
ASan+UBSan harnesses against existing model objects. No model jobs or reference
build are launched. Two 300,000-cycle-ceiling DMA positives and two
100,000-cycle-ceiling PMP positives are followed by **all 14 existing negatives**:

- DMA, each model: destination generation, route, complete return token,
  unrelated read region.
- PMP, each model: trap provenance, independent data, final request/count.

Expect roughly 2–6 minutes and under 250 MiB additional disk; these are planning
estimates, not measured runtime/performance results. The two reused checkpoints
are about 84 MiB each. One comparable retained uncompressed harness link was
about 14 MiB. Peak resource use is limited by sequential linking/execution.
No optional debug compression is applied; sanitizer instrumentation is preserved.

The fresh `build_guests.py` retains source copies and a portable bundle with
relative build commands, source hashes, pinned tool records, all artifact and
log hashes, symbol evidence and strict file inventories. It uses the original
assembly flags and linker scripts. The existing DMA builder's profile/symbol
rendering and PMP helper's exact symbol/result/negative contracts are reused.
A separately built bundle can be supplied using `--guests /path/to/bundle`.
Manifests are evidence only; their commands are never executed. Every actual
command is reconstructed from source-defined contracts.

Audit the completed run without recompiling or simulating, using the same
arguments and replacing `--execute` with `--audit`. Use `--guests` consistently
if it was used for execution. A run is terminal only after fresh links, all four
positives, all 14 negatives, strict output audit, byte-identical A/B guest checks
and exact PMP retired-PC/count equivalence. DMA polling/cycles/retirement can
vary; its independent semantic oracle must pass on each side and is not replaced
by a cross-run cycle or count comparison. Logs and products are guarded before
and after every step and again at completion.

## Limits

These are directed functional checks, not NEMU/full-ISA, exhaustive privilege or
PMP, denied store/AMO, packet-DMA, MAC/CDC, Linux, FPGA timing/resource, physical
board or performance qualification. Data-PMP runs have the configured DMA idle;
only the separate executed copy-DMA positives exercise DMA concurrency. Existing
RV64GC checkpoint smoke supplies provenance, not a newly executed RV64GC gate.
No production changes, model generation/compilation, installs, pushes, synthesis,
Vivado or full regression are involved.
