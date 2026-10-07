# Registered load-result issue forwarding

## Opt-in experiment

`staged-load-issue` is exactly `staged-fetch-feedback` with
`registeredLoadIssueForwarding = true`. Existing profiles and production defaults
are unchanged. The option requires `registeredIssueExecute` and excludes the
older, broad `loadCompletionBypass` option. The two-issue configuration, memory
capacities, ISA, clocks and UART configuration are not changed by the experiment.

## Throughput, latency and ownership contract

- At most one selected registered LSU completion supplies data each cycle, using
  the existing completion arbitration. It may feed both operands of both ordinary
  execution operand slots. The issue width and completion bandwidth remain two.
- A dependent ordinary instruction can capture the selected load result on the
  same edge that writes its physical register, instead of waiting for the
  registered physical-ready bit. Its ALU executes after the operand register.
- This adds no queue capacity and no completion latency or backpressure. Per-LSU
  slot metadata is one physical destination and one ordinary-load permission bit.
- Start handshake captures metadata beside that slot's operation. Completion and
  metadata use the same round-robin selection. Completion/replacement on one edge
  reads the old metadata, then installs the new owner.
- The promise excludes stores, atomics, x0 destinations, faults and previously
  cancelled operations. A current-cycle cancellation deliberately does not feed
  speculative wake/ranking. Existing final operand-enqueue kill and exception
  authorization blocks surviving consumption of a killed producer.
- The path does not feed general PRF readiness, memory operands, store preparation,
  M-unit readiness, PRF writes, retirement or any load-to-address/ALU combinational
  execution path. The forwarding data path terminates at `IssueExecuteStage`.

Full-token/physical-destination/live-owner assertions check the saved metadata
against the ROB separately from the wake cone. A matching actual capture asserts
that the producer's completion was accepted and its owner was not killed.
Simultaneous ALU/load promises for one physical destination are forbidden.
`IntegerBackend.io.loadIssueForwarded` records actual captures of used operands
whose physical-ready bit was still clear (bit 0 = left, bit 1 = right per lane).
This distinguishes exercising forwarding from merely passing an instruction test.

## Validation and performance limits

Use unchanged workloads and identical machine parameters for A/B. In addition to
existing IPC workloads, include a genuinely serial load -> ALU -> next-load
address chain. Required focused tests cover both operands and mixed ALU/load
producers, signed/unsigned widths, fault/x0/type exclusion, held execution slots,
rollback, delayed stale responses, physical-register reuse/WAW, and simultaneous
old completion/new owner replacement. Independent architectural results and actual
forwarded-enqueue witnesses are both required.

`IonSoC.test.compile` and the filtered profile/guard test passed (1/1).
Dedicated ASan/UBSan GSIM: 57 cases, 2057 retired instructions, 129 actual
forwarded-enqueue cycles; the deliberately corrupted oracle was rejected.
The dedicated wrapper has `atomicMemory=false`: a successful atomic-result
no-forward witness is NOT covered; production atomic exclusion was code-reviewed.

Final same-config A/B (2026-10-07): `staged-fetch-feedback` versus
`staged-load-issue`, two issue, RV64GC/FPU enabled on board wrapper, nominal
100 MHz, UART460800, 2 GiB DDR, two-way D-cache and instruction prefetch.
15 bare-core workloads passed independent per-retirement NEMU checks.

| Workload / window | Baseline | Candidate | Meaning |
|---|---:|---:|---|
| Serial 128-link load/ALU/address, RAM1 cycles | 900 | 772 | 14.222% fewer synthetic cycles |
| Same chain, RAM12 cycles | 2308 | 2180 | 5.546% fewer synthetic cycles |
| Mixed memory/ALU RAM1 cycles | 391 | 392 | 1-cycle regression |
| CoreMark one-iteration guest ticks | 834653 | 831768 | 0.346% fewer ticks |
| CoreMark timed retirement-window cycles | 834654 | 831769 | same 360528 retired |
| CoreMark timed IPC | 0.431949 | 0.433447 | 1.00347x same-frequency throughput |
| DDR 4KiB READ ticks | 5706 | 5705 | essentially unchanged |
| DDR WRITE+flush ticks | 8142 | 8141 | essentially unchanged |
| DDR COPY+flush ticks | 13772 | 13777 | 5-tick regression |
| DDR CHASE ticks | 3998 | 3998 | unchanged |

ALU/branch workloads are unchanged. RV64GC board context/ISA smoke passes;
this is not FPU numerical-throughput coverage. Raw reports are in
`build/gsim/performance-baseline-20261007` and
`build/gsim/load-issue-perf-candidate-20261007-r2`, dedicated evidence in
`build/gsim/load-issue-forwarding`. The delivery archive includes these short
receipts/logs and the complete 15-row cycle table.

Bare-core numbers use ideal uncompressed input and synthetic RAM and exclude
board frontend/cache/AXI/FPU. Board tests include CPU/cache/TL/AXI with sparse
2 GiB backing memory, but not DDR PHY, independently clocked Ethernet/CMU,
network/DMA contention or full EthernetSocTop. An exploratory 512 MiB model
is excluded; final baseline and candidate both use fresh explicit 2 GiB wrappers.

CoreMark is one CRC-checked iteration, NOT an official score. Its unchanged
firmware prints a historical 50 MHz reporting constant; printed seconds and
rates must not be read as 100 MHz measurements. Compare raw ticks. Ignore
spurious CoreMark-PC ROI lines in baseline DDR/FPU logs; only their whole-run
counters and test results apply. Reproduction enables ROI only for CoreMark.
Whole-run counts include UART polling and can retire different polling counts.
Stall flags overlap and cannot be summed as an exclusive CPI stack.
CoreMark baseline head-empty is about 37.5% of ROI cycles, a reason to diagnose
frontend supply next, not proof of a specific frontend cause.

This remains an opt-in experimental candidate. The tiny application gain may be
outweighed by frequency/area cost. Do not replace the current 100 MHz bitstream
by default. No routed timing, area/power, physical board or Linux qualification
was performed; no full GSIM or long Linux run was requested. GSIM host walltime
is not hardware performance evidence. Hardware adoption requires new complete
RTL synthesis/implementation and a full new bitstream, not a ROM-only ECO.

Reproduce from a prepared GSIM/NEMU/toolchain checkout:

```sh
source scripts/cloud/env.sh
make coremark-setup
python3 simulator/gsim/load_issue_forwarding.py
python3 simulator/gsim/load_issue_perf_test.py
python3 simulator/gsim/load_issue_perf.py --tag fresh-baseline --profile staged-fetch-feedback
python3 simulator/gsim/load_issue_perf.py --tag fresh-candidate --profile staged-load-issue --firmware-dir build/gsim/load-issue-perf-fresh-baseline/firmware
```

## Sanitizer-driven inactive-payload guards

Focused recovery testing exposed unspecified inactive payload indices in generated
GSIM expressions. The forwarding ownership assertions now select safe slot zero
when their promise is invalid. The pre-existing held branch-redirect cancellation
lookup likewise selects slot zero when `branchRedirectValid` is false. Enclosing
Boolean conditions alone do not prevent generated combinational expressions from
being evaluated. Neither guard changes valid-owner semantics; the redirect guard
is a separate robustness correction, not a claimed performance optimization.
