# Executing CPU order replay with fetch history enabled

This is an isolated adaptation of the qualified CPU-order R7 fixture for the
current fetch-history and older-prefix composition. It never generates a board
model. It requires two explicit completed, source-bound model receipts, with
fetch history fixed **ON** and only older-prefix retirement changing **OFF/ON**.

## Exact lineage and scope

- Production anchor: `2288c7f008e9d6440e8a28e339da28152b54892a`.
- Qualified host anchor: `46b061977ad4189bd71d084dcb63e873a7f0c740`.
- Exact production `src/main` tree: `c6e69b6b539bc36285b602a39fae32cb76ea012c`.
- R7 receipt SHA-256:
  `ebc318ee5e79f00c886d53d0f08b5e3668a8c40a88c7d3e4052855b1060efb63`.
- Original immutable input snapshot:
  `Valence-cpu-retire-prefix-next/build/cpu-order-replay-r7-source-snapshot`.
- `cpu_order_replay.cpp`, `order_oracle.h`, `test_oracle.cpp`, assembly, linker
  script, and guest builder are byte-identical to that R7 snapshot. The snapshot
  itself is only provenance; this fixture has no run-time path dependency on it.
- `r7_lineage.json` pins the retained bytes, guest artifacts/symbols, and both
  current terminal model receipts. Explicit receipt paths can point to relocated
  copies, but their content must match these qualified receipts.

Both profiles retain LSU4, physical ingress ON, depth4/yield0 line DMA idle,
virtual precheck OFF, prechecked flow OFF, and passive probes. DDR timing remains
read latency 32, beat gap 1, eight credits. The plan must contain both the actual
`--fetch-previous-packet` parameter and typed `fetch_previous_packet: true`.

Host-only commits may advance past the host anchor. The complete committed and
working `src/main` tree, including resources and untracked files, must still
match the production anchor. Current board input inventory must equal each
receipt. All generated files must be present, declared, and hashed: the exact
header/FIR and complete matched translation-unit/object set. Unrelated files,
nested directories, symlinks, missing entries, type-confused Boolean values,
and altered bytes are rejected.

The independent executing oracle is unchanged. It covers precise load-order
recovery, selector/pending full-token identity, killed generations and no killed
retirement, two retirement lanes, ROB wrap/tag reuse, known-memory data, ordered
architectural execution, full final GPR comparison, and drained internal and
external AXI state at the terminal **pre-`ddr.sample`** boundary. The twelve
observation negatives on each side remain unchanged (24 total). None of these
are RTL mutation or NEMU coverage. This fixture adds no FPGA, timing, Linux, or
real-board claim.

## Source-only checks

From the repository root:

```sh
python3 -B simulator/gsim/fixtures/cpu_order_replay_history_v1/test_validation.py
python3 -B simulator/gsim/fixtures/cpu_order_replay_history_v1/test_lineage.py
```

These use only Python, Git, and tiny temporary files inside this fixture. They
do not compile, link, build a guest, or execute GSIM. Model/source rejection
checks use independent synthetic checkpoints and temporary Git repositories.

## Check the actual current models without executing

Use the existing qualified Clang 19 and RISC-V tools on PATH. In this checkout,
the existing tool directory is
`../Valence/simulator/build/cloud-env/sysroot/usr/bin`:

```sh
export PATH="$(realpath ../Valence/simulator/build/cloud-env/sysroot/usr/bin):$PATH"
python3 -B simulator/gsim/fixtures/cpu_order_replay_history_v1/run_fixture.py \
  --off-receipt build/gsim/fpga-next-board-cpu-fetch-history-on-r1/receipt.json \
  --on-receipt build/gsim/fpga-next-board-cpu-fetch-history-prefix-on-r1/receipt.json \
  --guest ../Valence-cpu-retire-prefix-next/build/gsim/cpu-order-replay-r4/guest-final \
  --compress-debug --validate-only
```

This checks source/profile, the full generated model files and used schema,
compiler and guest-tool identities, exact guest artifacts, and R7 lineage. It
prints `PASS_SOURCE_PROFILE_MODEL_TOOL_GUEST_BINDING_ONLY execution=0` and writes
no result directory. Tool version queries are permitted; no compiler job runs.
The guest bundle can be relocated. The byte-identical builder is also included
for deliberate fresh guest builds, whose artifacts must match R7 exactly.

## Execute only when a compile/simulation slot is authorized

Reuse the same command, omit `--validate-only`, and add a fresh output directory:

```sh
  --out build/gsim/cpu-order-replay-history-prefix-r1
```

The runner sequentially builds/runs the small host oracle, links the unchanged
executing fixture to each existing model, runs both positives, and runs all
24 unchanged observation negatives. `--compress-debug` uses the current
repository's `elf_debug_compression.py`, retains each uncompressed proof input,
and records its verified compression receipt. No old executable or receipt is
rewritten. There is no implicit model build or fallback to another profile.

Execution success is a fresh receipt with status
`PASS_EXECUTED_CPU_ORDER_REPLAY_HISTORY_ON_PREFIX_OFF_ON`.
The R7 historical pass and a source-only preflight are not evidence of this new
execution result. The runner rechecks source/model/tool/guest/output bindings
before and after each step and requires every observation negative to fire.
