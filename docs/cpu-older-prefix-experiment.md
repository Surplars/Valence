# Opt-in strict older-prefix retirement experiment

This cloud experiment follows the clean four-LSU-owner functional freeze
`60d3e3454089aa9e45d24b6eec458dfcbfb9b816`. Production source is
`681ae55f14dde1c192f936b908476dc58a360e3a`; the new flag remains off by default.
No local FPGA operation, mapped resource result, timing result or board result is
claimed for this option.

## Change and safety boundary

`loadOrderOlderRetire` captures the complete checked-load token at the existing
registered load-order boundary. The ROB first validates its full generation and
live circular position, then allows only its strictly older ready prefix to
retire. The checked load and every younger instruction remain blocked. Invalid
or stale tokens fail closed. The existing load-load overlap selector, pending
replay global hold, full-token recovery, exception, system and branch controls
remain intact. The registered-replay configuration continues to exclude trusted
fast-head retirement producers.

Both experimental sides retain the current selected two-issue RV64GC profile,
four LSU owners, physical load ingress, two D-cache MSHRs and coherent copy DMA
line depth4/yield0 (idle in the hot microbenchmark). Virtual precheck and
prechecked flow are off. Only older-prefix retirement differs.

## Current evidence

- Sixteen Scala configuration checks passed, including exact OFF/ON parameter
  equality after clearing only the new option.
- Fresh ASan/UBSan real `RenameRob` component simulation passed 93,828 cycles,
  45,185 commits, 2,176 circular head/count/rank cases, all generation-bit
  challenges, exception/recovery cases and eleven observation negatives.
- Independent source review found no actionable defect. Its 444,816 abstract
  FIFO cases are reasoning evidence, separate from the emitted-RTL fixture.
- Both exact-source board models passed RV64GC smoke and its negative control.
  The initial six OFF hot cases exactly reproduced the MLP4 freeze.
- The first ON hot run failed the older one-word speculative-guard oracle. A
  separately labeled nonqualifying trace found four extra guard loads per pass,
  each canceled, fully drained, never completed to the ROB and never retired.
  The original failed receipt and all trace inputs remain preserved.
- An experiment-specific oracle fork admits only the first four aligned
  ordinary 64-bit words immediately after the source, with a total guard-read
  cap of four times the number of timed passes (not a per-pass quota). It requires full-token cancellation no later than LSU return, no ROB
  completion or retirement, complete ordered lineage and independently known
  reply data. It retains every speculative byte and cycle in raw measurements;
  useful payload is unchanged. The original shared hot oracle is untouched.
  Independent extracted-helper checks and fresh full-pair replay passed all
  twelve cases plus twenty external observation negatives. The custom 8 KiB
  read kernel drops 9,277 to 6,745 cycles (+37.54% throughput); writes remain
  unchanged and copy improves by only two cycles. This is not a scalar-monitor
  speedup prediction.
- Executing-CPU delayed-address replay/four-owner cancellation now passes both
  actual board models and twenty observation negatives. The real selector at
  cycle339 leads to full-token inclusive recovery340. A separate branch at419
  cancels four live owners, two before and two after physical acceptance; all
  drain without completion/retirement and all four ROB indices retire new
  generations. ON retires two real predecessors during the target older-load
  checking window; OFF retires none. An independent PC/GPR/memory oracle and
  all-slot/all-stage/held terminal drain pass at1238. This is a bounded directed
  fixture, not NEMU or exhaustive exception qualification.
- The unchanged archived monitor diagnostic passes the separate LSU2 ingress
  OFF/ON pair. Its scalar hot read improves only 3,215 to 3,210 ticks. See
  [the complete original-loop report](archived-monitor-bandwidth-replay.md).
  Original-ELF LSU4/older-prefix replay remains pending.
- The actual S-mode and MPRV data-PMP denial fixture passes both sides with
  identical 1,989 cycles, 108 retired instructions and exact PC trace, plus six
  trap/data/count observation negatives. This covers denied loads, not denied
  stores/AMOs or exhaustive PMP combinations.

## Literal storage and structural timing risk

Fresh selected native OFF/ON exports pass the source-bound fail-closed reachable
storage census. `BoardSocTop` scalar declarations increase 81,479 → 81,543 bits,
exactly 64 new checked-generation bits in `IntegerBackend`; reachable array
storage remains 704,967 bits. The ten separately checked fixed-storage groups
remain 297,088 logical payload bits. These categories overlap and must not be
added together. External ROM/clock primitive state is excluded with identical
wrapper hashes and instance counts.

The hardened census checks the complete current 212-file native source map and
every selected profile field, not merely equality between two potentially wrong
exports. Independent common-mode profile/source, helper, final-drift and storage
group probes pass. All 262 default-OFF module texts also match the prior frozen
LSU4 export after removing comments and normalizing whitespace while preserving
token boundaries.

Emitted `RenameRob.sv` visibly adds a dynamic selection from sixteen 64-bit ROB
tags, full-tag equality, a four-bit circular-age subtraction, live-count gating,
and per-lane age reductions ahead of retirement validity. The second lane still
passes through the existing ordered prefix. Actual LUT mapping, sharing, fanout,
placement and 100 MHz timing have not been measured. A +64-bit declaration delta
is not a complete area or timing cost estimate.

## Why the real board loop needs its own replay

The earlier ingress microbenchmark uses eight adjacent loads, four independent
sums and four timed passes. The real monitor's `read_sum` is a scalar accumulated
read with one timed pass. Its archived GCC14.2 loop is LD / ADDI / ADD / BNE;
the user's tested board binary was built with GCC13.2 and is not available in
this cloud workspace. The cold and hot source-identical compiled loops occupy
different PCs, with real UART printing between them.

The completed unchanged whole-ELF replay measures all1,024 hot load owners
shortening from six to five cycles while launches remain almost uniformly
three cycles apart. Both sides record zero timed Dcache misses and zero cycles
where a done ROB head is directly held by the load-order check. The prior
instruction-count-plus-check hypothesis is therefore not established as the
cause of this scalar loop's limit. Passive full-token issue/source-readiness/
preparation/capacity observations and the same original ELF on LSU4 are the next
test. No custom-loop speedup is presented as a prediction of the board diagnostic.

## Evidence entry points

- `simulator/gsim/older_prefix_retirement.py`: fresh focused component fixture
- `simulator/gsim/cpu_retire_prefix_board.py`: same-guest model OFF/ON hot pair
- `fpga/next/older_prefix_census.py`: exact-profile literal storage comparison
- `simulator/gsim/fixtures/cpu_order_replay/`: executing-CPU recovery gate
- `simulator/gsim/fixtures/monitor_bandwidth_replay/`: unchanged archived
  diagnostic ELF replay with explicit source/compiler scope

Raw receipts live in the experiment's external evidence tree; no generated
models or executables belong in source Git. A final clean qualification freeze
will name its full hashes after all selected gates have actually passed.
