# Archived whole monitor bandwidth replay

This fixture executes the unchanged archived `monitor-diagnostic.elf`/`.bin`
from the formal-monitor release, compiled with GCC 14.2.0. It does not rebuild,
patch, shorten or replace the diagnostic or official CoreMark. The exact board
GCC 13.2 object is unavailable; this is **not exact board reproduction**. The
reported board hot-read gain (+1.5%) and the handwritten eight-LD/four-sum gain
(+19.6%) are comparison context, not results of this fixture.

Only this fixture directory is owned here. Production freeze is
`66c06d786275dc28c099301162cd09e70497f6eb`. The two permitted models are the
immutable integration checkout's `fpga-next-board-cpu-flow-{off,on}-integration-r1`
receipts. Both use LSU2, DMA line depth4/yield0; only physical-load ingress differs.
No elaboration, model compilation, tool installation, local board access,
Vivado, Verilator or Linux run is part of this flow.

## Binding and mapping

`pins.json` fixes the archived ELF, binary, contract, release receipt and eight
archived objects, plus both exact model receipts. `prepare.py` verifies all126
archived source hashes and the contract's pinned official CoreMark source hashes.
It independently parses ELF64 sections, symbols and LOAD mappings, and requires
byte-for-byte equality between the allocated file image and binary.

- Original entry: `0xfff78000`; binary26,952 bytes; LOAD memory29,016 bytes.
- Original text ends`0xfff7daa0`; data starts`0xfff7e940`; BSS ends`0xfff7f158`.
- Original16KiB stack: `0xfff94000..0xfff98000`.
- A: `0xfff98000..0xfffb8000`; B: `0xfffb8000..0xfffd8000`.
- Original mailbox: `0xffff7f00`, seeded to`'b'` before release.
- Whole reserved range: `0xfff78000..0xffff8000`.

The separately assembled64-byte ROM launcher configures UART FIFO in the same
way as the existing board fixtures, calls the original `_start`, checks return
status, and performs a final fence/flush only after the whole diagnostic returns.
Its ELF, bytes, disassembly and source are separately hashed. The host sparse DDR
map contains only initialized words, not a multi-gigabyte zero image. Unseeded
bytes in explicitly allowed BSS/stack/buffer scratch regions are defined zero.
Original code/rodata, mailbox, and launcher are excluded from legal stores.

The original initial monitor cache history is not recreated. Within the
diagnostic, the original initialization, distinct cold and hot loops, all UART
reporting, checks, fences and verification passes execute uninterrupted. In
particular, the cold pass does not warm the exact hot-loop instructions, and
FENCE.I's actual dirty/clean cache behavior is left to the unmodified model.

## Oracles and observations

Two independent byte-lane memory shadows start from known image/ROM/mailbox
bytes. One checks every accepted physical memory reply; the other checks every
accepted LSU RAM/ROM load reply, including local forwarded reads. Every accepted
request must have a legal region, class, alignment, size and byte mask. Every
buffer store is additionally checked by ordinal, address and the independent
formula`0x935b76124aedc087 XOR (i * 0x102040810204081)`, with unsigned64-bit wrap.
The complete original pattern/contrast/copy sequence requires52,224 A stores and
34,816 B stores. Final flushed DDR must match the independent shadow, and both
buffers must match the closed-form pattern across128KiB each.

Frozen full-generation backend and flow ledgers check routing, all transfers,
response provenance, cancellation and ownership. Bit18 is the explicit uncached
attribute; the frozen M-mode LSU/identity path preserves zero even for UART,
whose address selects its device route. Final success requires the
original return, launcher return, complete guest PASS/UART output, all CPU queues,
both LSU slots, all physical/AXI owners and held responses drained. It never
accepts just the first UART PASS substring as completion.

Fixed loop PCs are cold`0xfff783f0..0xfff783fc` and hot`0xfff787d0..0xfff787dc`.
PC-to-owner joins use the selected banked issue payload's two PC banks, because
the unbanked queue PC is intentionally zeroed. Mandatory retired joins are1024
cold8KiB,1024 hot8KiB and16,384 cold128KiB. Full tokens retain FIFO/physical/
reply/LSU reply/result/retire/cancel times; histograms show their lifetimes and
launch gaps. Raw counters retain speculative traffic, including one-past guards.

Actual rdtime values are observed at the registered system result and joined to
retirement by full token. All18 values must follow the original PC sequence and
match the seven original UART read/write/copy reports, including flush tails and
printed rate arithmetic. Host retirement-inclusive windows are reported
separately. Shared marker cycles appear in both adjacent inclusive windows; do
not add them as disjoint totals. No overhead or traffic is subtracted.

Each window reports LSU/queue occupancy, frontend supply, raw instruction-cache
events, D-cache misses, AXI transfers and full-token cycle classifications.
`done_head_zero_commit_with_order_hold` is a conjunction witness, not an assertion
that orderCheck was the sole cause. Every accepted physical request/reply is
retained in each positive raw TSV, with full token, cycle, address, data and
metadata. Negative runs retain the failure log and only a TSV header; their
observations stop near startup or the first hot marker and do not duplicate a
full positive trace. Expected two-run footprint is approximately250–350MiB.

Three executed negative runs corrupt only checker observations: RAM reply data,
return token, and the hot-start rdtime marker. All must fail for the expected
reason. The fast host oracle also rejects illegal regions, immutable stores,
bad masks, wrong intermediate values/addresses and final corruption.

## Commands

Use the already installed tools (no setup/install):

```sh
source ../Valence/scripts/cloud/env.sh
F=simulator/gsim/fixtures/monitor_bandwidth_replay
I=../Valence-cpu-dma-integration
B=../Valence-bootrom-tui
python3 "$F/prepare.py" --archive "$B/build/tui-formal-monitor-release" \
  --source "$B" --out "$F/prepared-new"
clang++-19 -std=c++20 -O1 -fsanitize=address,undefined "$F/test_oracle.cpp" -o "$F/prepared-new/test-oracle"
ASAN_OPTIONS=detect_leaks=0 "$F/prepared-new/test-oracle"
```

`run_replay.py` defaults to source/schema/artifact preflight and performs no heavy
link or simulation. To execute, explicitly add`--run`, only when the parent has
released a heavy-job slot. OFF and ON must run serially. Each invocation links
the existing unchanged model object once, runs the complete positive, then the
three bounded negatives. The hard simulation bound is12million cycles; positive
wall timeout1800s; each negative/link timeout600s. Do not run this concurrently
with the parent's two already allocated heavy jobs.

```sh
python3 "$F/run_replay.py" --model-repo "$I" \
  --model-receipt "$I/build/gsim/fpga-next-board-cpu-flow-off-integration-r1/receipt.json" \
  --prepared "$F/prepared-new" --physical-flow 0 --out build/gsim/monitor-whole-off-r1 --run
python3 "$F/run_replay.py" --model-repo "$I" \
  --model-receipt "$I/build/gsim/fpga-next-board-cpu-flow-on-integration-r1/receipt.json" \
  --prepared "$F/prepared-new" --physical-flow 1 --out build/gsim/monitor-whole-on-r1 --run
python3 "$F/compare.py" build/gsim/monitor-whole-off-r1/receipt.json \
  build/gsim/monitor-whole-on-r1/receipt.json --out build/gsim/monitor-whole-comparison-r1.json
```

Current preparation performed only static/archive verification, small launcher
assembly, host oracle checks and model-header syntax checks. Hardware replay
results must be taken from fresh successful run receipts, never inferred from
these preparation checks.
