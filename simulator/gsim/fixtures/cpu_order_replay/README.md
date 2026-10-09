# Bounded executing-CPU replay and cancellation gate

This is an independent, passive qualification fixture for production commit
`681ae55f14dde1c192f936b908476dc58a360e3a`. It changes no production RTL, existing
harness header or parent runner. The guest executes real DIVU/DIVUW, LD, branch,
fence and signature-store instructions. No request, replay event, cancellation
or delayed response is injected into the DUT.

## Required witnesses

- A real startup known-RAM LD and FENCE wait for the board’s DDR calibration
  response before either scenario. This does not alter external response timing.
- DIVU computes the older LD address from `0x180c00000 / 3`. The independent
  younger overlapping LD must already have issued, read and completed. The
  actual replay selector's registered-next token, next-cycle pending token and
  accepted local recovery must match that younger full `(generation,index)`.
- The checked older load identity and byte interval are checked against the
  guest's fixed address. Checked/younger retirement before the ordering check
  is forbidden; pending replay must retain the global retirement hold. The ON
  run must retire at least one actual predecessor during the delayed older
  load’s checking window; OFF must retire none during any checking window.
- DIVUW, a forward taken branch and four cold younger LDs share one 64-byte
  instruction line. At accepted branch recovery all four specified full-token
  LSU owners must be live, with none yet replied, completed or retired.
- Both cancellation-before-physical-acceptance and
  physical-acceptance-before-cancellation are required. Every canceled load
  must drain physical reply and LSU reply, with its accepted kill pulse and
  registered sticky cancellation observed separately. No canceled generation
  may subsequently complete to ROB or retire. All four killed ROB indices must
  later retire new generations.
- A separate FIFO records full-token allocations from monotonic allocation
  generation changes and existing immutable PC banks, prior to observing
  commit/recovery. The selected design zeros the raw queue PC payload, so that
  array is deliberately not used. Recovery removes a
  FIFO suffix by exact token, without importing the DUT's circular-age formula.
  The final FENCE.I protected-head recovery is observed separately and retains
  exactly the independent FIFO head while discarding its younger suffix.
  Inclusive replay is proved by discarding the replay owner and requiring its
  newly allocated generation to retire. Commits must match the FIFO front.
- The architecture oracle starts from frozen guest bytes and zero registers.
  It executes only the explicitly supported RV64 instructions, computes every
  next PC/register result independently, and compares the committed register
  map on the next actual edge. Every physical request is bound to its guest PC
  and fixed RAM address; every accepted read response matches independent known
  memory. The sole store has an exact address/value/count and is flushed by
  the final FENCE.I.
- Terminal drain checks all four physical slots and shadow owners, all nine
  raw data-path occupancy counters, every backend/flow owner queue, held
  requests/replies, pending physical replies, external AXI queues and held
  R/B offers. Every observed retirement clears the final-register-comparison
  flag. Completion requires a later comparison sample with no new retirement,
  so no observed architectural register edge remains pending.

The external memory model is the unchanged `board_ddr_benchmark.h`, with read
latency 32, beat gap 1, credits 8. The fixture must not assume that a future
reply has already arrived or change the DDR schedule to manufacture a witness.
A missing witness is a failed qualification, including a missed four-owner
branch window.

## Portable execution

Use the repository's already installed cloud tools; never install replacements.
For this cloud workspace, source the existing `Valence/scripts/cloud/env.sh`.
Use fresh output directories:

```sh
python3 simulator/gsim/fixtures/cpu_order_replay/build_guest.py \
  --out build/gsim/cpu-order-replay-guest-r1

python3 simulator/gsim/fixtures/cpu_order_replay/run_fixture.py \
  --off-receipt build/gsim/fpga-next-board-cpu-retire-prefix-off-r1/receipt.json \
  --on-receipt build/gsim/fpga-next-board-cpu-retire-prefix-on-r1/receipt.json \
  --guest build/gsim/cpu-order-replay-guest-r1 --validate-only

# Coordinate the execution slot with the parent first. This only compiles the
# fixture and links the explicit existing model objects; it never rebuilds RTL.
python3 simulator/gsim/fixtures/cpu_order_replay/run_fixture.py \
  --off-receipt build/gsim/fpga-next-board-cpu-retire-prefix-off-r1/receipt.json \
  --on-receipt build/gsim/fpga-next-board-cpu-retire-prefix-on-r1/receipt.json \
  --guest build/gsim/cpu-order-replay-guest-r1 \
  --out build/gsim/cpu-order-replay-r1
```

Both models must carry completed board-smoke receipts, exact current source
inventory, pinned GSIM/compiler identities, and artifact hashes. Their profile
is selected LSU4, two D-cache MSHRs, physical ingress ON, virtual prechecks OFF,
DMA line transfers/depth4/yield0 (idle). Their sole A/B parameter difference is
older-prefix retirement. The runner checks actual generated field widths and
array sizes, every guest input/output/tool/log hash, and repeats guards around
each step. C++ driver spelling is retained for linking even if its resolved
executable is the clang binary.

The runner first executes nine pure-host oracle sensitivity checks, then each
model's positive and ten observation negatives: missing selector, missing
pending, high-bit generation corruption, missing accepted recovery, omitted
kill pulse, canceled retirement, read data, architectural data, PC sequence,
and premature drain. Every negative must exit 1, print `fired=1`, and fail at
its designated check. These are observation/checker sensitivity controls, not
production RTL mutations. A host-only pass or header/schema pass makes no claim
about executing CPU replay.

The current source additionally routes the canceled-retirement mutation through
the ordinary valid-commit observation path by replacing that observed full token.
The archived r4 source used a direct killed-set assertion instead. Independent r4
review also found that a terminal-sample JAL x0 could leave its next-edge register
comparison pending; that instruction is register-neutral in this fixed guest.
The source-only tightening above is not yet a fresh executed result. Preserve r4
and its restricted review scope until the new source passes a separate run.

## Evidence boundary

As initially prepared, guest assembly, the 81-instruction host oracle with nine
negatives, OFF/ON syntax checks, and strict binding validation passed. Executing
model results belong only to the runner's resulting receipt; this document does
not substitute for a positive OFF/ON receipt. No NEMU, complete ISA compliance,
physical board, FPGA routing, synthesis, Linux or throughput claim is made.

## Executed terminal-edge follow-up

The retained `cpu-order-replay-r5` run rejected the OFF positive: waiting for a
zero-retirement sample never ended the terminal self-JAL and reached the independent
1024-instruction bound. This was a fixture stopping-condition failure, not evidence
of an RTL data mismatch.

`cpu-order-replay-r6` passed both positives and 22 observation negatives, including
corruption of the final GPR comparison. Both sides execute 81 retirements in 1238
cycles. The final callback compares the register edge applied from the preceding
sample, validates the current CPU/data-path state, and stops before admitting the
newly computed self-JAL offer; the next model step is never called. The ordinary
commit-path canceled-generation negative remains enabled. External AXI emptiness
in r6 is checked after the host `ddr.sample()` callback; it is not yet an exact
pre-callback AXI-empty witness. The complete source snapshot and independent narrow
boundary review are preserved beside the new receipts.

Optional `--compress-debug` only compresses a newly linked executable into a
separate new output. Both files are retained, executable bytes/program headers,
non-debug sections/symbols and decompressed DWARF are checked, and `addr2line(main)`
must remain identical. ASan/UBSan compilation and runtime tests are unchanged.
No earlier executable is rewritten.
