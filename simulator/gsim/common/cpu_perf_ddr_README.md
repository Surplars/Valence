# Exact-body DDR-resident common CPU observation

This additive fixture measures the **same original 360-byte binary** from
`cpu_perf.S` after a real CPU ROM loader copies it to cacheable DDR. It changes no
Scala, production RTL, common-platform defaults, existing fixture, or host service
law. The four retired-PC windows still contain 768/608/1280/1 instructions,
256/256/512/0 loads and 0/0/512/0 stores. This is bounded native digital evidence,
not GSIM, physical timing, metastability, board, Linux, or steady-state bandwidth
qualification.

## Placement and execution contract

- ROM loader begins at `0x80000000`; its trap handler stays in ROM.
- The original machine bytes are included without relinking at ROM `0x80001000`.
  Expected body SHA-256:
  `31193326af006e2ca93f160d4f4b5d1f07137486301eee84f1b5f6f96fd782e8`.
- The CPU executes 45 `ld`/`sd` pairs to copy those bytes to `0x80200000`, then
  executes a genuine `FENCE.I`, then jumps to that DDR base. The destination is
  initially zero in the external memory; no testbench injects executable bytes
  into DDR, caches, registers, or CPU internals.
- The original body uses PC-relative local addresses and branches. Adding
  `0x200000` to all its original PCs preserves every instruction byte and moves
  its own `mtvec` setup, failure/done loops, and retired markers correctly.
- Data addresses remain `0x80210000` (pointer chain), `0x80220000` (source), and
  `0x80230000` (destination). Their initial external-memory data is unchanged.
- At loader-fence retirement, require six code-line AW transactions and six real
  B handshakes, zero data traffic, and byte-exact DDR code contents. Repeat the
  independent 45-word code check at DDR entry and final completion. Every retired
  DDR instruction is checked against the original ROM instruction word.
- First cacheable execution starts after instruction invalidation. There is no
  additional I-cache warm-up or second measurement iteration. The pointer-data
  warming loop remains inside the unmodified body and outside the four windows;
  code lines first encountered by later windows can still fill cold.

## Unchanged platform and service law

The runner verifies the original emitted source/class/artifact chain and the
boot/performance references, then compiles unchanged native RTL with a different
observer and ROM image. Existing A1 sv2v output is reused, with `$fatal` and
`$error` counts checked against the original RTL; no conversion is rerun.

The original generated testbench is reconstructed and compared byte-for-byte to
its recorded baseline. Only its monitor fragment is replaced. DDR initial data,
geometry, queues, independent clocks, phase, backpressure masks, ticket-dependent
read eligibility, held R bursts, byte strobes, delayed B completion, and all
original host assertions remain identical.

The same service **rule** does not imply identical per-request response delays:
loader allocations, code writebacks and instruction fetches consume AR/AW tickets
and advance the global fabric-edge phase. No counters or ticket states are reset
at ROI boundaries to manufacture a latency match. This is an execution-placement
comparison under the same deterministic service model, not a cycle-aligned replay.

## Measurement and independent oracles

- Markers, CPU/fabric edge conventions, post-handshake ownership samples, and
  useful retired counts match the original experiment.
- A separate public AXI-ID scoreboard classifies AR, accepted R beats/RLAST, AW,
  and accepted B handshakes by address. Code uses translated `[0,0x10000)`;
  data uses the three original 4 KiB windows. Unknown ranges, missing owners,
  and premature ID reuse are fatal.
- Before DDR execution, code AR/R includes the loader's write-allocate reads.
  After loader maintenance, executable-phase code AR/R is instruction-path
  traffic. Data counts never include I-cache fills. All-code plus all-data
  counts must reconcile with the unchanged host's totals.
- Warm-data windows require zero data AR/AW, while allowing code fill AR/R.
  Final completion requires exactly 192 **data** reads (64 pointer lines plus
  64 source and 64 write-allocate destination lines), 64 data B completions, six
  code B completions, all read RLASTs, true home/AXI quiescence, and the original
  independent 512-word source/destination oracle.
- Loader-fence retirement, first DDR retirement, final-fence retirement, and
  final quiescence have separate cumulative checkpoints. The final drain window
  includes refetch of the resumed marker, with fence-retirement-to-marker time
  and code AR/R reported separately. Post-marker speculative code traffic, if
  present, is accounted for before final quiescence rather than forced away.
- The negative control changes only expected destination word 31 after real
  completion. Its required failure is the exact final pattern oracle; any other
  failure or a positive PASS token fails the negative-control runner.
- No internal fetch/LSU wait shares are inferred. Cache fill traffic and edge
  occupancy are measured, but they do not constitute mutually exclusive stalls.

## Reproduction

Use the frozen corrected source tree and its already emitted evidence. No tools
are installed, no emission or Scala compilation is needed. Run I1 and A1 positive
observations sequentially, then one negative using the completed A1 model:

```sh
python simulator/gsim/common/cpu_perf_ddr.py EVIDENCE/common-reset-i1-perf-ddr-r1 \
  --source-root FROZEN_SOURCE \
  --reference-run EVIDENCE/common-reset-i1-perf-r1 \
  --boot-receipt EVIDENCE/common-reset-i1-native-boot-r1/receipt.json \
  --guest-dir EVIDENCE/common-perf-guest-r2
# Repeat with the corresponding a1 reference and boot receipt, fresh output.
python simulator/gsim/common/cpu_perf_ddr.py EVIDENCE/common-reset-a1-perf-ddr-negative-r1 \
  --negative-from EVIDENCE/common-reset-a1-perf-ddr-r1
```

Each invocation enforces a total 600-second command budget and the inherited
4 GiB disk floor. Use a sparse common-directory worktree to keep both new native
models, logs, receipts, and source additions below the agreed 100 MiB budget.
Failed attempts remain separate evidence. Receipts bind the new fixture, loader,
original body, original evidence, clocks, host law, production source/classes/RTL,
and tool hashes. Old PASS statuses do not become new DDR results.

## Interpretation guardrails

The I1 private-cache aperture starts at DDR (`CommonCpuProfile.scala:24`), so the
original `0x80000000` ROM instructions bypass its cacheable path. Warm **data**
therefore did not mean warm instruction delivery. This relocation experiment can
expose that confound without changing the CPU or LSU.

Do not generalize that cache behavior to A1. Its common tile instantiates
`SynchronousFetch` (`CommonA1CpuTile.scala:50`), whose packet cache records returned
instruction packets and invalidates on the explicit frontend invalidation signal
(`core/ooo/platform/memory/InstructionRom.scala:100,477–515`). Equal nominal private
cache geometry does not mean the two frontends treat ROM instruction reuse
identically. Attribution beyond the public-interface placement comparison remains
an inference, not a measured exclusive stall breakdown.

A1's loader-fence checkpoint observes seven code-region ARs, versus I1's six,
with both requiring exactly six code AW/B completions. The monitor cannot split
the extra pre-entry code request into private-cache allocation versus speculative
instruction fetch from address classification alone. It reports all code-region
traffic rather than silently assigning an unobserved source.
