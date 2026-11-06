# I1 native Spinor binding

Current checkpoint (2026-11-06): the independent-clock H/V SoC includes fabric, PLIC, CMU and the PS DDR handoff. Both H and V are advertised; `misa=0x80000000003411ad` was read on the board. The clean RPU-to-RV DDR selftest passed after the auxiliary reset fix. CPU300 setup timing is still -0.323 ns; VPU300 is +0.071 ns. See `docs/i1-ps-rpu-board-20261105.md` and `fpga/inorder/board-checkpoint-20261106.json`. The pinned upstream Spinor tree stays unchanged; four local hardware overrides are compiled from this integration directory. The sections below preserve the earlier dated bring-up progression.

CPU development and GSIM stay in `/home/openion/Valence-InOrder`; Windows export and Vivado stay in `E:/VM/Share/Valence-rtl/Valence-InOrder`.

The user-provided [Spinor](https://github.com/Surplars/Spinor) source is locked at `e151f80e1da3a566d1a6ff5157052757fac0ddcb`. `SpinorI1` compiles its unmodified source with Valence's pinned HardFloat; `SpinorHost` is an optional module and scalar builds do not depend on it. The current bring-up config is RV64IMAFDC, fpga8, 32KiB I/D caches, BTB128, physical RAM, Spinor standard/host-FCSR, VLEN128/ELEN64 and one lane.

The system architecture keeps CPU and VPU clock domains independent; VPU has its own 300 MHz target. The temporary `I1SpinorSameClockBringup` is in test sources only and checks instruction semantics. `I1SpinorDualClockCore` and its six-mailbox transaction boundary are now implemented and compile/export successfully. Independent-clock functional acceptance and physical CDC qualification remain pending. SoC interconnect and CMU are absent. CPU-facing ports and the temporary memory service are CPU-clock local; Spinor native ports remain VPU-clock local. The boundary transfers complete command/FCSR, preview, grant, done and TL A/D packets; all fields remain local to their receiving domain. A CPU serial WB owner offers one instruction, grants the immutable preview, and waits for done. A WB preparation edge captures done payload; done.fire then coincides with scalar/FPR/FCSR/trap commit. CPU owns FCSR, Spinor owns VRF/vector CSRs, and all 80 token bits survive the boundary. Interrupts wait for this instruction boundary. The single-owner memory bridge retains source/size, preserves TL byte lanes, and traverses the CPU's existing atomic/D-cache path, including ordinary-store reservation invalidation.

`FiveStageConfig.spinor` defaults to false. Its optional control fields and ports disappear when disabled. H and V remain unadvertised in misa: H CSR/two-stage MMU, vector virtual memory, full ISA compliance and CPU+VPU physical timing are unfinished. The same-clock fixture and registered observations are test-only; they do not qualify independent clock operation.

```sh
source /home/openion/Valence-InOrder/.local-dev/env.sh
python3 scripts/fetch_spinor.py --verify-only
mill -i SpinorHost.test.compile
mill -i SpinorHost.test.runClasspath
python3 simulator/gsim/inorder/spinor_cpu_assessment.py --output build/FRESH_SPINOR_CPU
```

Use `scripts/fetch_spinor.py` without `--verify-only` only for the explicit initial fetch. All output directories must be fresh. The assessment records immutable source copies, raw/GSIM FIR, model/tool hashes, commands, positive logs and independent negative checks. GSIM's reserved `old` identifier is alpha-renamed only in generated FIR; memory read-under-write attributes are preserved. The source clone is unchanged.

The real CPU program checks vsetvli, integer/FP vector arithmetic, loads/stores through shared caches, LR/SC invalidation, vector CSRs, f0 source/destination, host RUP/NX, VS=Off CPU rejection and native illegal CSR recovery. Both L1/L12 memory laws pass; this directed program is not a vector performance benchmark. See `docs/i1-hv-integration-20261104.md` for exact evidence and limits.

## Independent-clock RTL and tool-capability gate

`I1SpinorDualClockCore` has separate `cpuClock` and `vpuClock` inputs and a common cold-reset epoch, with local synchronized reset release. The VPU target is 300 MHz. CPU/VPU module interfaces retain synchronous reset. Six instances of the existing `CdcMailbox` preserve payload/ownership under backpressure. FCSR is sampled atomically with each command; no raw multi-bit FCSR crosses the domains. The CPU keeps its WB owner through final done acceptance. Local transport-idle outputs cover mailbox/command ownership; they are not whole-system CMU drain permission.

```sh
source /home/openion/Valence-InOrder/.local-dev/env.sh
mill -i SpinorHost.test.compile
mill -i SpinorHost.test.runClasspath
python3 simulator/gsim/inorder/spinor_dual_clock_assessment.py --output build/FRESH_DUAL_CLOCK --rtl-output /mnt/e/VM/Share/Valence-rtl/Valence-InOrder/FRESH_DUAL_CLOCK/rtl
```

The current GSIM executable fails all seven independent-edge cases and post-activity AsyncReset in the existing independent oracle. The runner records `ELABORATED_DUAL_CLOCK_RTL_GSIM_INDEPENDENT_CLOCK_RESET_UNSUPPORTED`; it does not run the full dual-clock CPU as a functional acceptance test. Same-clock vector-program receipts remain instruction-semantic evidence only. No alternate simulator, simulator-source mutation, synthetic clock gating, new timing exceptions or physical implementation was used. See `docs/i1-spinor-dual-clock-20261104.md` for the exact scope.

## r2: opt-in explicit-edge GSIM qualification

`simulator/gsim/tool_fixes/explicit-clock-edges.patch` now supplies a separately built and qualified explicit-edge profile. The original default tool stays frozen. The qualified real CPU+VPU program passes both 10:6 and 6:10 period ratios at L1/L12 memory latency, including clock pauses and two independent negative controls. Each case retires 62 instructions with 17 vector commands and two precise traps. The earlier unsupported result applies to the default tool; it is not overwritten. See `docs/i1-spinor-dual-clock-20261104-r2.md` for limits and the build/qualification/program commands. Physical CDC and CPU+VPU implementation remain unqualified.

## 2026-11-05 local timing batch

`SpinorI1` now replaces four pinned Scala files with the explicit implementations in `overrides/`; `VectorTiming.scala` is a local combinational helper. The upstream clone stays pristine. Actual compiled source hashes, paired GSIM results and routed timing are in `docs/i1-spinor-opt-20261105.md`. CPU and VPU remain independent clocks. Both internal setup margins improved, but 300 MHz is not yet fully closed. All active in-order Vivado flows use a maximum of 8 threads.
