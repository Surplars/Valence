# Whole archived diagnostic, LSU4 older-prefix v2

This is a new, source-bound observer/runner. The qualified `monitor_bandwidth_replay`
fixture, its `static-r1` payload and its completed results remain immutable. This
version reuses that exact prepared manifest and guest, without rebuilding the
monitor diagnostic or CoreMark. The standalone 64-byte launcher is unchanged.

The cached OFF/ON models both use LSU4, physical ingress ON, DMA line depth4/yield0
(idle DMA). They share source `681ae55f14dde1c192f936b908476dc58a360e3a`; only
`--load-order-older-retire` differs. `v2-pins.json` binds both model receipts, the
original fixture, prepared manifest and LSU2 ON reference receipt. The latter uses
source `66c06d786275dc28c099301162cd09e70497f6eb`: LSU2-to-LSU4 is explicitly a
cross-checkpoint observation, not a same-source oneflag A/B. The production
anchor remains `681ae55f...` even if later observer/documentation commits advance
HEAD. Both runner and comparator require its exact committed `src/main` tree,
no working-tree diff against that anchor, and an identical physical source/resource
file set, followed by the complete source/model artifact inventory. The actual
observer HEAD is recorded separately.

## Passive scalar timeline

`positive-hot-stage.tsv` covers all original hot-loop LD/ADDI/ADD/BNE owners at
`0xfff787d0..0xfff787dc`, with complete 64-bit generation and ROB index:

* exact accepted rename allocation cycle, then next-cycle registered ROB binding;
* both source-ready bit visibility, pending-clear visibility, matching staged
  full token/address, LSU start, physical request acceptance, registered done
  visibility, actual retirement/cancellation;
* source physical-register producer full tokens, producer PC, registered done
  visibility and retirement, including each LD's preceding pointer ADDI (initial
  pointer SLLI at `0xfff787c8`);
* independent rows for external setup producers, source/destination physical IDs,
  and per-owner state counts;
* allocation-gap histograms for all four instruction PCs, plus load stage delays.

Registered `done` and pending-clear are optional observations. Ordinary ALUs can
retire on accepted completion without ever exposing registered done while live
(`RenameRob.scala` 232–248, `IntegerBackend.scala` 1288). Such rows retain
`done_visible=-1` and set `retired_without_done=1`; retirement is not copied into
the done column. Each hot LD must join a predecessor with either observed done
or explicitly observed retirement-without-done before its launch. Both witness
counts are reported separately. The exact dynamic LD/pointer-ADDI, sum recurrence,
ADD-from-LD and BNE-from-pointer/limit chains are checked, including the initial
pointer SLLI and loop-limit SLLI rows.

Allocation is the source-bound accepted prefix: `RenameRob.scala` 353–361,
414–437, 476–479 supplies `(nextTag+lane,(tail+lane)&15)` for `perfRename` lanes.
`BoardSocGsimMain.scala` 468,495 defines that count from `ledger.io.renamed.valid`.
Each full token must appear in the next registered ROB view, with matching queue
and ROB tag and banked PC. The unbanked queue PC is intentionally zero in this
selected profile and is never used as the instruction PC.

`OwnerOperandReady.scala` supplies the registered source-ready mirrors. The
staged address joins use `IntegerBackend.scala` 563–674; launch is at 768–829.
The capacity state uses the existing exact, otherwise-launchable *younger-load*
capacity predicate (`BoardSocGsimMain.scala` 303–344), not `liveCount==4`. Other
start gating is left unclassified, including head cases outside that predicate.
Completion overlap can make a full-looking LSU available. Pending-clear and
ROB-done visibility are not claims about precise ALU issue/completion handshakes.
`perfSupply` counts frontend fetched offers, not eligible LSU candidates. State
counts are owner-cycles and may overlap global cycle counters; neither is a causal
partition of retirement stalls. No order-check, dependency or frontend dominance
is assumed before reading the actual trace.

`positive-frontend.tsv` adds the hot fetch cursor/readBase, all three registered
window packet keys/present bits, read/snapshot contexts, invalidation gate, actual
instruction0/1 validity, fetched offer count and accepted rename count. Full keys
are reconstructed from the source-defined regions/offsets/regionIds in
`RegisteredFetchWindow.scala` 48–81. The generated instruction0/1 fields feed
`perfSupply`; every sample verifies their sum against that accessor. The trace
counts consecutive cursor transitions from `0xfff787d8` to `0xfff787d0`, missing
current packets and instruction0-invalid cases. These are passive observations
of the proposed backward-window miss, not a causal assertion. The comparator
reconstructs these classifications and checks hot allocations against the same
cycle's accepted rename prefix, including full `nextTag+lane`/`tail+lane` keys.

The frontend interval is continuous and exactly bounded by
`min(hot-start rdtime retirement, earliest hot allocation)` through hot-end
rdtime retirement, inclusive. One previous sample captures either trigger's
allocation/marker cycle. Both observer and comparator require every recorded hot
owner, including cancelled owners, to allocate inside this interval and join
exactly one accepted-prefix event; a later speculative allocation fails
qualification rather than being omitted. The end marker is architecturally after
the loop's exit branch in the unchanged guest. Missing, duplicate, reordered or
out-of-range cycles cannot pass; zero unjoined hot owners is mandatory.

## Acceptance and scope

The current four-owner ledger tracks every slot from reset, preserves complete
owners through cancellation, and checks held request/reply payloads. Terminal
acceptance explicitly requires all slot-owner live flags, raw request/reply valid,
backend held request, data held request/reply, all independent token queues and
DDR pending/held channels to be empty after original return. Independent CPU and
physical memory shadows still verify every accepted RAM reply and all legal
writes/masks, the original pattern, full UART output and 18 actual `rdtime`
records. Inclusive timing windows and complete raw physical traffic retain all
original UART/flush/cache effects, speculation and overhead.

The four-owner map permits up to four aligned read-only words immediately after
B for possible speculative final verification LDs. Every observed such owner must
be the original final-B verification instruction, cancel without result/retire,
and drain through both physical and CPU replies. All stores there are forbidden;
the next word remains unmapped. This does not modify any guest byte.

Four checker-side negatives corrupt data, full-token ownership, rdtime marker,
or staged hot-owner identity. Negative traces retain only their header, avoiding
long duplicate traffic. Two positive traces are complete. The strict comparator
requires the exact complete step/product set, expected exit/anchor/sanitizer
status, immutable model/source/tool/guest bindings and compile/execute commands.
It reparses positive logs, checks UART against actual rdtime, reconstructs raw
request/reply conservation, all 13 emitted stage histograms and the per-owner
state sums. It requires complete unique distribution and cycle-bucket records,
checks their histogram/IPC conservation, and rejects receipt results that disagree
with logs. The only signed stage histogram is explicitly named
`load_predecessor_retirement_to_start_signed`; other negative latencies fail.

The guest is archived GCC14.2. The actual board GCC13.2 object is unavailable;
this is not exact board reproduction. The host DDR model is not physical DDR/MIG
or routed FPGA timing. Preceding interactive-monitor cache history is not
reproduced; all history inside the original diagnostic is preserved, including
its distinct cold/hot loop PCs and original flush behavior.

## Source-only checks and future execution

From the repository root, use the existing cloud environment. No installations,
model rebuilds, deletes, FPGA/Vivado, local board or full Linux work are needed.
Omit `--run` for strict preflight only. Heavy execution requires the parent's
explicit CPU-slot release. Fresh output directories are mandatory.

```sh
source ../Valence/scripts/cloud/env.sh
F=simulator/gsim/fixtures/monitor_bandwidth_replay_lsu4_v2
P=simulator/gsim/fixtures/monitor_bandwidth_replay/static-r1
for flag in 0 1; do
  side=off; test "$flag" = 0 || side=on
  python3 "$F/run_replay.py" --model-repo "$PWD" \
    --model-receipt "build/gsim/fpga-next-board-cpu-retire-prefix-$side-r1/receipt.json" \
    --prepared "$P" --older-prefix "$flag" \
    --out "build/gsim/monitor-whole-lsu4-prefix-$side-v2-r1" --run
done
python3 "$F/compare.py" \
  build/gsim/monitor-whole-lsu4-prefix-off-v2-r1/receipt.json \
  build/gsim/monitor-whole-lsu4-prefix-on-v2-r1/receipt.json \
  --lsu2-on build/gsim/monitor-whole-on-r1/receipt.json \
  --out build/gsim/monitor-whole-lsu4-prefix-comparison-v2-r1.json
```

The prior whole pair occupies about90MiB. Allow100–130MiB for these two relinks,
complete positive traffic and scalar timelines; checker negatives add only small
logs. No prior evidence is deleted. Host tests are `test_stage.cpp`,
`test_oracle.cpp`, and `test_compare.py`; the latter explicitly uses a synthetic
v2 text corpus and is not execution evidence.

## Corrective source-only qualification r2

The initial independent review and all r1 preflights/receipts are preserved.
Changed r1 source bytes are retained under `static-r2/source-before-strictness`.
The revised Python host suite calls the exact production TSV parser with a valid
in-memory corpus, then mutates missing/duplicate/reordered frontend cycles,
accepted tokens/events, external and scalar producers, optional phase timestamps,
state sums, every emitted stage-histogram reconstruction, summaries and evidence
inventories. Its synthetic corpus includes a legally absent registered done
observation; it is not a model-execution result. The small C++ host case also
executes that retirement-without-done path. Full relink/replay remains unexecuted.

The final parser checks also require all eight per-owner lifetime distributions to
cover every retired load (retirement-ending distributions match that count
exactly). An observed registered ready mirror cannot precede its matching
producer's registered done, or retirement+1 when done was unobserved. Missing
mirror samples remain legal for forwarding; missing done remains explicit.
Per-owner states must match reconstructable start/done/pending/operand-wait
phases. The aggregate split between matching-address capacity gating and other
start gating is bounded by the possible staged interval; its exact internal
partition still comes from the source-bound passive probe.

## Optional new-output debug compression

The default remains the original uncompressed host link and identical step/product
inventory. Add `--compress-debug` to opt in. This links a new
`replay.uncompressed`, invokes the source-bound `compress_debug.py` wrapper as a
separate recorded `debug-compression` step, writes new `replay` and
`debug-compression.json`, and runs only the compressed executable. Both newly
created binaries are retained; no prior binary, guest or evidence is rewritten.

The shared `simulator/gsim/elf_debug_compression.py` helper is explicitly included
in external fixture source bindings. Its installed objcopy/nm/addr2line executable
hashes and versions are pinned at preflight and checked between steps. The helper
proves equal program headers, loaded bytes (apart from loader-unused e_shoff),
nondebug sections, symbols and decompressed DWARF, and checks `addr2line(main)`.
The comparator requires the exact extra step, command, output products and proof
schema, reparses both ELF files, and reruns the helper's strict tool/symbolization
proof. Compression mode must match on the compared sides. The host compression
contract tests use tiny synthetic files and a clearly marked success stub; they
also verify the real shared validator rejects malformed ELF inputs. They do not
claim a new model execution or real compression result.
