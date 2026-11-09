# MUL capture + efficiency4 + W11/W14 local Vivado candidate

Exact target: xczu15eg-ffvb1156-2-i. Top: CombinedA1FabricTimingTop.
Mode: efficiency4-mul-candidate. This is experimental OOC RTL, not a board image.

This candidate enables registeredMulLoadOperandCapture on the previously delivered
**efficiency4-candidate**, retaining compact issue immediates, indirect16 banked
storage and the same Probe-Acquire fabric, real depth16 CDC and external DDR AXI.
It does not compare against efficiency4-baseline, which also differs in W11/W14.

## Local run

Requires Python 3.10+ and Vivado with the exact device installed.
Use a Vivado command prompt on Windows or source Vivado settings on Linux.

```text
python run_local.py --verify-only
python run_local.py --out ../mul-candidate-run-01
```

If Vivado is not on PATH, add `--vivado "C:/Xilinx/2025.2/Vivado/bin/vivado.bat"`
(or your installed path). Output must be a fresh directory. The example version
is not a required or tested Vivado version.

Run the old package's rtl/efficiency4-candidate/run_local.py separately with the
same Vivado version, machine settings, CPU and fabric periods. Defaults are 10ns
CPU and 4ns fabric. Optional --cpu-period NS and --fabric-period NS record the
requested targets in invocation.json and the generated XDC.

Only IntegerBackend.sv differs from the freshly re-emitted control. That control's
292 SV files are byte-identical to the earlier delivered efficiency4-candidate.
No Scala/Mill/firtool, repository checkout or external ROM image is needed to run
the already emitted RTL. The compile binding retains the actual cloud build paths
as provenance, not dependencies or a claim that local sources were recompiled.

## Qualification and boundary

This delivery has no Vivado results and claims no timing closure or area gain.
The historical +0.83% CoreMark ROI throughput / +0.60% LUT tradeoff was measured in
an earlier isolated experiment, not this new W11/W14/CPU/fabric combination.
The included current backend directed tests are not a full CPU/fabric workload.

The script performs synthesis, optimization, placement, physical optimization and
routing once; it saves synth/placed/routed DCPs and timing/utilization/DRC reports,
clock interaction, check_timing, final route status and CDC. No bitstream or
strategy search is performed. COMPLETED means commands ended, not timing passed.
Read setup, hold, unconstrained paths, route completeness, DRC and CDC reports.

The CPU/fabric clocks are real inputs. Setup/hold uncertainty is 0.100/0.080ns.
There are no false paths or asynchronous clock-group cuts. Thus crossing paths
are conservatively timed as related clocks; an OOC crossing violation alone is
not whole-board Fmax or a synchronizer correctness diagnosis. External port
input/output delays, pin constraints and board timing are not specified.
Physical CDC pointer max-delay/bus-skew and reset recovery/removal need review.

Real CommonA1CpuTile, CommonCpuClockBoundary and CommonMachineFabric are connected.
The fabric includes actual Home, DDR AXI manager, MemoryCopyDma and packet DMA;
external service/DDR interfaces remain exposed, not fed fake responses. CPU is
RV64GC, rename/issue2, ROB16, PRF48, LSU4 with the named exact MUL experiment memory
policy and bounded safe fetch range [0x80200000,0x80220000).

MIG, DDR electrical interfaces, managed peripheral bank, clock generators, PHY
and board shell/pin constraints are omitted. This is not an accepted board-flow
input or an H/V/I1 integration. Existing strict board identity guards remain.
