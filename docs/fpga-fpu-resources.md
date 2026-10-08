# FPGA floating-point resource candidate

## Scope and selection

`FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig.fpga)`
selects the candidate. `FloatingPointResourceConfig.baseline` preserves the old
implementation. Resource selection does not disable F, D, memory, conversion,
FMA, subnormal handling, exception flags, rounding modes, or NaN boxing.

`FloatingPointResourceConfig.roundOnly` preserves the separately qualified
RAM/shared-rounder topology without product sharing.

The design follows the resource-sharing principle seen in pinned NaxRiscv
`9f452d5`'s `FpuCore`: unrounded operations feed a shared format-aware rounding
boundary. This candidate retains separate binary32 and binary64 datapaths and
uses the project's pinned HardFloat primitives, rather than translating NaxRiscv
or rounding binary64 results down to binary32.

## Physical contracts

- Committed architectural state has 32 rows of 64-bit unreset payload, three
  asynchronous operand reads, and one delayed committed write. Thirty-two valid
  bits supply architectural zero after reset. This is intended for distributed
  FPGA RAM; the asynchronous port contract does not claim block-RAM inference.
- The accepted retirement write is independent of a later younger flush. The
  queued committed value forwards to all three same-cycle operand reads.
- Each precision has one shared raw-result register and one round/pack unit for
  add/subtract, multiply, fused multiply-add, divide, and square root. The raw
  one-hot selection precedes that register. No arbitration mux is inserted
  between that register and rounding.
- Multiply and FMA share the exact full significand product, one multiplier
  per precision. Both use the same registered significands, so operation selection
  adds no input mux. Multiply feeds its original raw capture directly; FMA keeps
  its full product/add register and post-multiply normalization boundary. There
  is no intermediate rounding or product-tail truncation before sticky reduction.
- Miscellaneous conversion paths retain their independently sized rounding
  units. The structural count reduction from eight to two is specifically the
  arithmetic `RoundRawFNToRecFN` instances, not every rounding-related block.
- There is still one outstanding numerical instruction. Full token, rounding
  mode, exception metadata, flags, and payload remain stable until consumed.
- Add/subtract and multiply latency are three cycles, minimum initiation
  interval four; FMA is four/five; miscellaneous instructions two/three.
  Illegal instructions complete in one cycle. Divider/square-root iteration is
  unchanged and bounded by 29 cycles for S and 58 for D, including all boundaries.
- Flush suppresses live raw/result outputs and resets divider iteration. Reset
  invalidates payload rows without resetting their contents.

## Proof workflow

Source the existing cloud environment and select the pinned GSIM source. Point
`SOFTFLOAT_ARCHIVE` to the official SoftFloat archive pinned in
`simulator/gsim/config/floating-point-dependencies.json`, then run:

```
python3 simulator/gsim/floating_point_resources.py --tag <fresh-tag> --cpu --memory
```

The runner freezes hashes for every production and test Scala source and FPU
harness. It compares baseline, round-only and shared-product candidates on the same 73,960 SoftFloat vectors,
including all rounding modes, exceptional inputs, dense subnormal/overflow
neighborhoods, and fused cancellation. It checks exact per-opcode latency,
saturated add/multiply/FMA initiation intervals, per-vector latency equality,
and negative controls for value, flags, boxing and rounding, plus deliberately
unfused and D-then-S double-rounded SoftFloat oracles that must be rejected. State tests cover
same-edge committed write/read forwarding, all three source ports, reset after
nonzero writes, and accepted older commit followed by younger flush.

The optional CPU stage runs the real machine core with complete F/D, A/C memory
geometry, dynamic rounding/CSR interactions, and architectural observation. It
is a focused CPU fixture, not a claim that a complete board workload ran.

`ooo.FloatingPointResourceRtlMain <directory> baseline|fpga` emits production
state and execute SystemVerilog without CPU debug observation. Production
memory geometry must be assessed after unused observational reads are removed.

## Timing and area limits

No LUT, distributed-RAM mapping, routed Fmax, or board success is established by
Scala, CHIRRTL, GSIM, or source instance counts. Raw-output arbitration adds
selection before the normalization register, so its physical timing must be
measured together with the reduced rounding/response duplication. The board's
100 MHz target remains a requirement. Do not promote a resource win that loses
its measured throughput/timing budget.

## Focused proof milestones

The separately frozen round-only batch checked 73,920 vectors and matched every
baseline latency trace. The shared-product batch checked 73,960 vectors on all
three topologies with identical 848,952-cycle runs. It includes 144 saturated
initiation-interval checks and exact divider/square-root latency derived from
IEEE operand classification, normalized-significand comparison and exponent
parity. Deliberately unfused and binary64-then-binary32 oracle outputs are rejected.

The original general matrix's flush total mostly describes held-result flushes;
its `stage_kill` marker is not evidence of all active divider/square-root stages.
The separate `floating_point_iterative_cancel.py` runner closes that gap while
reusing hash-verified frozen models. Per model it covers S/D divide and square
root in all five rounding modes, eight interruption boundaries, 160 flushes,
160 resets, 320 immediate new-token refires and 3,840 exact successor II checks.
It also waits beyond the interrupted operation's original completion deadline
to reject zombie outputs. Omitting cancellation intentionally fails the oracle.

For a normalized full-board export, run `floating_point_geometry.py --rtl <rtl>
--top <actual-top> --output <receipt>`. It follows the emitted module hierarchy
and checks every reachable FP state instance: three operand-bound read ports,
one delayed committed-value write, three committed-forward paths, 32 resettable
validity bits and no payload reset/initialization branch. Standalone production
RTL passes this geometry check; the selected full-board export is a separate gate.

A reuse-only mixed-stream check (`floating_point_mixed_stream.py`) shuffles the
unchanged independent vector multiset with a fixed seed. Its qualified run has
73,433 opcode/format/rounding transitions across 73,960 transactions; all three
frozen topologies produce identical numerical results and per-vector latency
traces. This checks rapid ownership/type changes; it does not replace the
separate architectural register-address matrix or CPU retirement tests.
