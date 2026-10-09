# Current-source fetch-history / older-prefix NEMU gate

This isolated fixture consumes two explicit terminal model receipts, the already
qualified portable six-case guest manifest, and an already built pinned NEMU
cache. It does not require an unrelated historical hot-performance receipt.
No old hardware result is reused as evidence for the current source.

Frozen source: production `2288c7f008e9d6440e8a28e339da28152b54892a`,
`src/main` tree `c6e69b6b539bc36285b602a39fae32cb76ea012c`, host qualification
`7c8b7bb800ed4fa3768c23eee9f608d3192391f2` (host-only descendants allowed).

Both sides: fetch previous-packet history ON, LSU4, physical load ingress flow,
selected two-issue profile, DMA line depth4/yield0 **configured but idle**.
Only older-prefix retirement differs OFF/ON. DDR read latency32, beat gap1,
credits8, four repetitions. Cases: read/write/copy, 4096 and 8192 bytes.

The architecture checker and reference client are byte-identical to the approved
`harness/board_hot_nemu` versions. Existing instrumentation, final extra tick,
whole-retirement-edge GPR comparison, and DDR-write-drain semantics are retained.
Each retired guest instruction's PC is checked before one independent NEMU step.
All 32 GPRs are compared after the entire retirement edge, including both lanes;
no unsupported intermediate-lane register snapshot is claimed. Every byte of
`[0x80200000,0x80600040)` is compared after terminal drain, including code and gaps.
The fixed ROM effects and RAM seed are independently specified. Speculative
requests are never stepped; no mismatch repair, NOP skipping, or reference
resynchronization is added. Reference-only FENCE.I initialization is unchanged.

## Inputs and preflight

From the source root, with the existing compiler on PATH:

```sh
python3 -B simulator/gsim/fixtures/fetch_prefix_nemu_v1/test_fixture.py
python3 -B simulator/gsim/fixtures/fetch_prefix_nemu_v1/run_fixture.py \
  --off-receipt build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json \
  --on-receipt build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json \
  --guest-manifest ../Valence-cpu-retire-prefix-next/build/gsim/cpu-retire-prefix-board-r1/guests/manifest.json \
  --reference-cache ../Valence-fpga-next/build/gsim \
  --compiler ../Valence/simulator/build/cloud-env/sysroot/usr/bin/clang++-19
```

Preflight performs no compiler, model, or reference execution. It reads git
source identity, validates exact current-source/profile/full-model directory
contents using the hash-bound R7 strict validator, and checks all input hashes.
The explicit receipt and guest manifest hashes are frozen in `lineage.json`.
Guest and NEMU cache paths may be relocated; their contents must remain identical.
The second known identical guest bundle is
`../Valence-cpu-dma-integration/build/gsim/cpu-bandwidth-flow-board-integration-r1/guests/manifest.json`.
The NEMU source/config/library are bound by the existing reference cache manifest,
reference lock and library attestation. No source download/install/rebuild occurs.
No guest compiler is required for replay; the previously qualified bundle is used.

## Execution, only after receiving the serial slot

Append `--run --out build/gsim/fetch-prefix-nemu-r1` to the same preflight command.
A first bounded probe may append `--variant off --case read-4096`; that runs one
positive plus its 13 negatives and records `PARTIAL_PASS`, never full PASS. Resume
with identical inputs, the same output, and `--run --resume` to complete the pair.
All existing steps are rehashed and reparsed before reuse. No old executable or
receipt is edited. Outputs must be outside this frozen source directory.

Full scope: 12 serial ASan/UBSan harness links, 12 positive runs, 26 negatives.
Three NEMU negatives per side: PC, GPR, RAM. Ten unchanged flow negatives per
side: physical fingerprint, route, virtual enqueue, checked enqueue,
authorization, private metadata, return full-token, upper live owner, upper
full-token and capacity reserve guard. Rejection must have exact nonzero exit,
its required checker text, and no successful terminal banner.

Tools: already hash-attested Clang++19, already compiled GSIM objects, existing
pinned NEMU shared library. Estimates: 3–8 minutes total, 150–300 MB retained
outputs, 300 seconds maximum per individual link/run. No model-object compilation,
RTL elaboration, new reference build, installation, or heavy regression.
Preflight and contract tests take seconds and negligible disk.

After terminal PASS, append `--audit --out build/gsim/fetch-prefix-nemu-r1`
(instead of `--run`) for read-only rehash/reparse. Only the exact complete case,
step, negative, compiler, input, guest identity and cross-pair architectural trace
inventory yields `PASS_TERMINAL_RECEIPT_AUDIT`.

## Limits

This is bounded physical integer M-mode architectural and full-token/flow
correctness. It does not claim CSR, FPU, VM, concurrent CPU/DMA NEMU, original
unchanged firmware/ELF execution, FPGA hardware, Linux, routed timing, or a
performance improvement. Hot metrics are recorded, but no historical hot result
is required to match and no performance comparison is implied.
