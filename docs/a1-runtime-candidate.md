# Experimental A1 runtime adaptation

This is a cloud-validated candidate, not a replacement for the programmed
`84a498a` hardware or immutable Linux r2 artifacts. Production defaults retain
`experimentalA1Runtime = false`. No A1 production profile or old A1 device-tree
compatible silently acquires the new register windows.

## Admission boundary

`CommonMachinePlatform` admits the candidate only for `A1Boot50` with the complete
runtime clock, fixed-time, debug, network, DDR, rate-control and telemetry chain.
The dedicated `CommonA1DynamicMain` test emitter opts in explicitly. Merely
removing an I1 kind check is neither the implementation nor the validation.

`CommonA1RuntimePark` has one command/epoch owner and one retained completion.
It stops new backend allocation and pauses fetch admission, preserving buffered
unadmitted instructions and their PC/epoch. Accepted execution and retirement
continue. It does not require a paused instruction packet to become empty.

Parking requires ROB/recovery empty, no execution slot or multiply/divide owner,
no protected system/FP/memory owner, no memory/store-buffer/prefetch owner, and
idle translation/response/fetch/native adapters. Private cache flush completes
with all refill, writeback, probe and downstream obligations drained. The
exported live held proof additionally requires matching fabric completion.
A retained status offer is only a historical drain observation: a later probe
revokes live held until it drains. Common fabric and CDC owners are independently
rechecked before closing a clock domain.

A queued runtime command must be consumed even during an older architectural
FENCE.I. Refusing it while `fenceBusy` makes that queue prevent the old FENCE's
transport-empty proof, creating a real circular wait. The candidate accepts the
command, stops new dispatch, but keeps the old FENCE and retirement live.
Only after `fenceBusy` clears may it park or switch maintenance status/completion
routing to the runtime owner. Local FENCE and external runtime epoch numbers may
be equal; phase/ownership, not numeric inequality, separates their receipts.

Resume waits for the matching fabric acknowledgement and actual private drain.
Its receipt means admission reopened and two local clock edges occurred, not
that an instruction retired. Interrupt delivery and private probe service are
not artificially disabled to manufacture drain. Pending timer/MSI state survives
park. A1 WFI currently executes as an architectural hint rather than a sleep
owner; tests check that actual behavior, not a fictional WFI sleep implementation.

The park handshake is a management-only, one-outstanding operation, not a
per-instruction pipeline. Latency is variable with real owners/backpressure;
no fixed-cycle drain bound, critical-path improvement or PPA result is claimed.

## Telemetry ABI

The I1 CPU and fabric descriptors remain ABI1. An experimental A1 CPU bank uses
`0x544d002000000002`: the same 32-bit counter width, CPU ABI2. Its fabric bank is
still ABI1 (`0x544d002000000001`). Register offsets are unchanged.

- CPU event 0: CPU edges.
- CPU event 1: sum of retirement lanes 0 and 1, modulo 2^32. Each lane increments
  a separate source counter by at most one and crosses as its own Gray code.
  Addition occurs only in the always-on destination. No Gray counter jumps by 2.
- CPU event 2: accepted A1 uncached/MMIO scalar lane 0 requests. I1 ABI1 retains
  scalar lane 1; A1 lane 1 is the cache-fallback/PTW adapter, not its MMIO path.
- Remaining CPU events: data coherent A acceptance/stall, line refill
  acceptance/stall, and no retirement on either lane. Fabric events are unchanged.

Software must distinguish CPU ABI1/ABI2 and enforce a two-lane window bound
(`12 * window <= mask`, versus ABI1 CPU `6 * window`, fabric `5 * window`).
Old A1 compatibles must remain forbidden from probing the extension. A future
explicit A1 runtime-compatible driver requires separate release approval and
capability binding; no A1 write control or automatic clock increase is implied.

## Reproducible focused verification

Source `scripts/cloud/env.sh`. Use the official lock-pinned sv2v v0.0.13 with
`--exclude=SeverityTask`. The runners preserve production severity sites,
freeze source/tool/RTL/model hashes, reject stale artifacts and fresh-directory
collisions, and write receipts. They do not rewrite emitted DUT semantics.

```
python3 simulator/gsim/common/a1_runtime_native.py \
  --out build/<fresh> --sv2v <pinned-sv2v> --suite epoch
# Other suites: arithmetic, wfi, atomic, fp.
python3 simulator/gsim/common/a1_dynamic_native.py \
  --out build/<fresh-smoke> --sv2v <pinned-sv2v>
python3 simulator/gsim/common/a1_dynamic_native.py \
  --out build/<fresh-roundtrip> --sv2v <pinned-sv2v> \
  --model-from build/<passing-source-identical-smoke>
```

Coverage is deliberately short and affected, not full GSIM or a Linux boot:

- Real A1, Home/RAM/APLIC/IMSIC across three unrelated clocks; two requesters,
  matching/stale epoch controls, real queued MSI replies, dirty ReleaseAck,
  fabric/CPU completion backpressure, cancellation, timeout cleanup and reset.
- Arithmetic plus older FENCE: independent DIV/MUL retirement values, different
  epoch numbers, and equal epoch numbers with an old completion held at CPU.
  The pre-fix command refusal reproduces a cleanup fault; corrected ownership
  completes without weakening timeout or transport-idle checks.
- Actual AMO read, write, physical response and final-result backpressure:
  exactly one read/write/result, old value 7/new value 12, one runtime terminal.
  Wrong old/final-value expectations must fail. This is not LR/SC coverage.
- Actual timer and APLIC/MSI arriving during park, exact-once trap/claim/mret
  after release, no architectural execution while held.
- F/D: command accepted while the real FP unit is busy, independently expected
  binary64/binary32 division values, context preserved across park and timer/MSI;
  incorrect FP value expectation must fail. Not Linux FP context-switch testing.
- Telemetry: independently driven lane0-only, lane1-only, unrelated lane pulses,
  and real modulo wrap of the sum; replacing lane1 with lane0 must fail.
- Default-off elaboration rejects incomplete A1 enablement and has no park,
  runtimeHeld or quiesce interface. This is an interface/structure check,
  not formal equivalence or routed timing sign-off.

The full-chain model retains actual clock-control, runtime admission, debug,
network, telemetry and DDR paths. Its MMCM/PHY primitives are behavioral, not
UNISIM or an FPGA. Smoke validates real guest MMIO and DDR refill observation;
the separately bounded roundtrip checks only model transactions, never frequency
qualification. First failures and wall-cap exits remain failures, not passes.

## Open physical and deployment gates

The extra A1 lane1 Gray crossing needs an explicit strict 32-bit physical census
and the same 3 ns delay/skew budget, without altering the I1 512-bit baseline.
The extra source-reset-release bank also needs a real mapped retained-load
census. Do not guess PRE loads or grant new reset timing exceptions; fail closed
until that census is reviewed. Functional/interstage timing stays constrained.

No candidate routed timing, implementation, bitstream, physical clock change,
board DMA/network concurrency, Ethernet packet-DMA traffic, high-DDR-address access, Linux boot, Debian/glibc,
user FPU switching, SMP, or sustained network throughput is established by these
tests. Those are separate release/board acceptance gates. Do not relabel the
existing r2 hardware or firmware as supporting this candidate.

### Current bounded full-chain outcome

The source-bound full-chain telemetry smoke passed. The separately authorized
600-second four-rate-transaction run is **PERF_FAIL_INCOMPLETE**, not a rate
transition pass. Actual PHY initialization plus two debounced poll batches took
51 MDIO frames; boot opened at simulation 2,622,820 ns and the first request was
at 2,654,630 ns. The next complete PHY poll batch was still retiring when the wall
limit killed and reaped the process. Last logged simulation time was 3,100,390 ns,
CPU held and fabric business owners idle, PHY operation 36 still outstanding;
zero rate transactions had reached a terminal. No protocol timeout was shortened
and PHY admission was not bypassed. The original FAIL receipt remains immutable;
`evaluation.json` supplies this narrower wall-budget classification.

### Actual DMA/probe follow-up

A separate test-only `CommonA1DmaProbeFixture` uses the existing memory-copy DMA
and actual Home/coherent ports, not a synthetic DMA or injected probe. Guest MMIO
starts one 8-byte copy while source, destination and a neighboring guard are
CPU-dirty. The test holds the actual ProbeAckData C handshake, requests park,
and rejects any premature held/terminal. Releasing backpressure yields eight
dirty-probe beats, exactly one DMA read/write and two responses. After release,
the CPU observes the copied value and intact neighboring word; actual DMA IRQ
APLIC source 4 / IMSIC identity 14, claim and mret are each exactly once.
Wrong-data and wrong-IRQ-count controls fail. This does not establish Ethernet
packet-DMA traffic or hardware clock gating during live network transfers.

```
python3 simulator/gsim/common/a1_dma_probe_native.py \
  --out build/<fresh-dma> --sv2v <pinned-sv2v>
```

Evidence for this batch is summarized in
`build/a1-runtime-acceptance-summary.json`. The immutable individual receipts
are `a1-runtime-final-{small,epoch,wfi,arithmetic}`, `a1-runtime-acceptance-atomic-r1`,
`a1-runtime-acceptance-fp-r1`, `a1-dma-probe-r1`, and `a1-fullchain-smoke-r2` under
`build/`. All those focused/smoke scopes passed. The separate full-chain rate
roundtrip remains incomplete as described above. The historical AMO receipt
retains its original runner hash, which predates adding the FP branch; its
production, fixture, guest and bench hashes match this batch. No old receipt is
rewritten to conceal that difference.

### Selective simulator lowering, not hardware acceleration

`simulator/gsim/common/a1_selective_lowering.py` is an optional, fail-closed
simulator experiment. It requires an existing source-bound passing full-lowered
model. Standard, officially locked sv2v converts modules with assignment patterns
and explicitly named modules with recorded Icarus elaboration failures. All other
emitted RTL is compiled unchanged. The full-chain example additionally needs
`--lower-module BranchPredictor.sv --lower-module Imsic.sv` because Icarus rejects
original dynamic packed-array indices. No generated DUT patch is applied.

The runner verifies the exact RTL inventory, guest/ROM/include artifacts,
source/tool hashes, official sv2v archive and its executable, selected module
identities, all severity-task counts, and rejects interface width warnings.
The epoch suite compares its complete architectural ledger with the full-lowered
reference and repeats wrong-data/wrong-IRQ controls. The full-chain mode runs
only the bounded telemetry/DDR smoke, not rate transactions. On any unsupported
construct or mismatch, stop and use `a1_runtime_native.py` or
`a1_dynamic_native.py` in a fresh output directory for standard full lowering;
there is no silent semantics-changing workaround or automatic long-run retry.

Initial receipts `build/a1-selective-epoch-r2/receipt.json` and
`build/a1-selective-fullchain-smoke-r1/receipt.json` passed their behavioral
checks; later r3 receipts bind the additional strict closure/source-lock checks.
The initial full-chain conversion took 1.81 seconds versus 19.59 for full lowering,
while the same 75,860 ns smoke took 19.09 versus 25.37 seconds. System loads were
not controlled, so this is not an attributable speedup claim. The selective
binary was about 2.8% larger. Neither this experiment nor its short smoke closes
the separately recorded four-rate-transaction wall-budget limitation.

### LR/SC reservation and actual DMA follow-up

The reservation is owned by the common fabric `AtomicMemory`, not by a
synthetic testbench model. LR records the exact address and access size; SC
requires both to match. Ordinary writes, including the existing memory-copy DMA,
invalidate reservations on the same 64-byte line. A1 traps also send an ordered
reservation-clear event through the physical scalar adapter.

`a1_lrsc_native.py --model-dir build/<passing-dma-fixture> --out build/<fresh>`
reuses the source- and artifact-bound `CommonA1DmaProbeFixture` without changing
production RTL. Independent retired-register and memory expectations check:

- An uncontended LR reads 7, SC succeeds, and memory becomes 9.
- A real park/resume falls between another LR and SC. SC may legally fail; its
  reported result must agree with the observed memory value (9 or 11).
- A real 8-byte DMA write targets the exact reserved address. SC must fail and
  cannot overwrite the DMA value or neighboring guard. Global interrupts remain
  masked until that SC has retired, so trap clearing cannot hide missing DMA
  invalidation. Only then is MSI 14 serviced exactly once.
- Both DMA concurrent with a second park and DMA without that second park are
  checked. The latter separates DMA invalidation from any permitted park-induced
  reservation loss. Wrong uncontended-SC, DMA-SC, data and IRQ expectations are
  explicit negative controls.

CPU execution may resume before the AON consumer accepts a retained terminal.
The test checks actual resume acceptance and CPU release at SC retirement, and
checks terminal consumption exactly once at the end. Earlier r1/r2 diagnostics
retain the rejected, overly strict terminal-consumption oracle; they did not
show an incorrect SC result or a production hardware failure. This scope does
not establish OS-level LR/SC progress under scheduling, SMP, or board behavior.

Final source-bound receipt: `build/a1-lrsc-r6/receipt.json`,
`PASS_A1_LRSC_NATIVE`. Both positive cases and all four negative controls passed
their expected outcomes. SC failure accepts any known nonzero value, rejects
unknown data, and does not require failure code 1. Source, reused fixture,
generated guest/include, and compiled executable hashes are checked for drift.
