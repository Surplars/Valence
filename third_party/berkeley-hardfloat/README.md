# Pinned HardFloat F/D arithmetic

Source: https://github.com/ucb-bar/berkeley-hardfloat
Revision: `c1105e6ac6a0dd90fc80893efc4830ab609005d3`.
License: source notices plus `../licenses/berkeley-hardfloat.LICENSE`.
The manifest in `simulator/gsim/config/floating-point-dependencies.json` records
original and local source hashes. Eighteen sources implement binary32/binary64
add/subtract, multiply, FMA, iterative divide/sqrt, comparison, classification and
conversions. This does not import upstream testbenches or simulator backends.

The subset compiles under the existing Scala 2.13.17 / Chisel 7.3.0 dependencies.
The upstream build requests Scala 2.13.10 / Chisel 3.5.6; no project downgrade is
needed. All arithmetic uses the independent SoftFloat reference described by
`simulator/gsim/floating_point_full.py`, not upstream HardFloat self-checks.
The ten newly imported files differ from the pinned archive only by omission of
the final blank line; original and local hashes explicitly record this difference.

One local change is recorded in `patches/0001-unsigned-alignment-distance.patch`.
Pinned GSIM `93b8cd23edd3228807c4f2a08c19c3936a463cb2` lowered the sliced signed
Mux/subtraction without clearing the upper bits: for recoded exponents 107/129,
the five-bit alignment distance 22 appeared as 246 in generated C++, causing
`0x00000001 + 0x007fffff` to return `0x007fffff` instead of `0x00800000`.
The patch takes unsigned modular differences before selecting their low bits.
The original full-width signed comparison still selects the direction.
An exhaustive software bit-vector check covered all 1,048,576 ten-bit input
pairs. The full arithmetic GSIM differential independently checks numerical
behavior. Neither the pinned GSIM checkout nor generated sources were patched.
The failing generated model is retained under
`build/gsim/floating-point-add-m2-signed-slice-failure`.

The official Verilog Release 1 is a viable arithmetic implementation with
binary32/binary64, rounding and exception flags:
https://www.jhauser.us/arithmetic/HardFloat-1/doc/HardFloat-Verilog.html
This project currently feeds FIRRTL into GSIM; a Verilog blackbox simulation
bridge has not been validated. The Chisel subset already follows that supported
flow and is the selected first integration route. This comparison does not
establish incompatibility of the Verilog implementation.

The original M1/M2/M3/M4 milestone imported addition only. The current complete
RV64 F/D candidate uses `FloatingPointArithmetic`, `FloatingPointDivSqrt` and
`FloatingPointMisc`; our own decoder/state/ROB/LSU integration is not an independent
floating-point numerical implementation. The independent oracle is pinned SoftFloat
`a0c6494cdc11865811dec815d5c0049fba9d82a8`, with explicit RISC-V NaN/flag/integer
clipping adaptation and known-answer anchors.

Current candidate acceptance passed under
`build/gsim/floating-point-full-20261004-nan-cut-r1`, status `PASS_FUNCTIONAL_CANDIDATE`:
27,840 independent numerical vectors with 21 known-answer anchors, 1,212 real-CPU
cases, exhaustive compressed FP decode, precise-memory and integer regressions.
The batch binds 134 source hashes and 36 model/binary hashes. Earlier receipts
remain immutable. The numerical wrappers subsequently remove redundant late NaN
classification without changing HardFloat, producer latency or CPU test cycles.
The receipt's old limits footer predates explicit ISA profiles; the runner only
corrects that qualification text, and `fpga/audit-rv64gc-evidence.py` audits this
exact delta against the saved, hash-matching source. No tests are edited to fit it.
F/D defaults off; explicit complete F or F+D profiles now consistently advertise
misa/device-tree ISA. Pruned subsets cannot advertise full extensions.
The real BoardSoC Sv39 nonidentity-mapped context smoke passed under
`build/gsim/rv64gc-board-20261004-sv39-context-r1`; this is not Linux scheduling.
All 13 FPU modules meet internal 10 ns setup/hold in Native Vivado, with zero-delay
I/O hold and reset boundaries still unqualified. The actual two-issue MachineCore
also meets internal 10 ns after route (WNS +0.090 ns, internal hold +0.023 ns),
but zero-budget boundary hold is -0.046 ns. Final source/model/RTL/report audit is
`build/fpga/fpu-rv64gc-20261004/audit-final.json`; this is not whole-board timing.
OS FP-context acceptance, independent RTL-backend
cross-check and complete-F/D FPGA board qualification remain.

The earlier 2026-10-03 addition-subset timing adapter registers `AddRawFN`'s raw result
before `RoundRawFNToRecFN`; this changes no vendored arithmetic source. The
producer has capacity one, two-cycle latency and minimum II=3 (previously
one-cycle/II=2). Fresh GSIM checks all 34,840 independently computed SoftFloat
vectors, stalled results, raw-stage flush/reset and state/CPU integration.
Module timing evidence is separate from functional receipts under
`build/fpga/fd-100mhz-20261003`. Neither that OOC measurement nor the existing
integer-only board bit qualifies a full-F/D FPGA or Linux FP-capable system.
