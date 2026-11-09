# Combined A1 + fabric local Vivado package

**Primary delivered pair: efficiency4-candidate / efficiency4-baseline.**

**Experimental out-of-context (OOC) timing candidate, not a complete board image.**
Exact target: **xczu15eg-ffvb1156-2-i**. Vivado has NOT been run for this delivery.
No bitstream is generated. No routed timing or timing closure is claimed.

## Run on your computer

Requires Python 3.10+ and Vivado with this exact Zynq UltraScale+ device installed.
Use a Vivado command prompt on Windows, or source Vivado settings on Linux.
Extract the package to any local directory, including one containing spaces.

```text
python run_local.py --verify-only
python run_local.py --out ../candidate-run-01
```

If Vivado is not on PATH:

```text
python run_local.py --vivado "C:/Xilinx/2025.2/Vivado/bin/vivado.bat" --out ../candidate-run-01
```

The output directory must not exist. Each mode is a standalone package. Run the
matched baseline using its own package and a separate output directory. Keep the
same Vivado version and machine settings when comparing modes. SHA-256 verification
is done before launching Vivado; do not edit RTL or regenerate the manifest to
ignore a mismatch. Hashes detect changes, not authorship or functional correctness.
The archived compile binding records original build paths as provenance; these
paths are not consumed by local Vivado and are not rewritten to claim recompilation.

The flow performs synthesis, optimization, placement, physical optimization and
routing once, and retains synth/placed/routed DCPs, setup/hold paths, utilization,
clock interaction, check_timing and DRC reports, plus final route status and CDC.
A COMPLETED marker means commands finished, not that timing or DRC passed. Inspect
all reports, particularly unconstrained paths, CDC and routing completeness.
No automatic rerun, implementation strategy search or bit generation occurs.

## What is actually integrated

Top: `CombinedA1FabricTimingTop`, instantiated from current production modules:

- `CommonA1CpuTile`: RV64GC, two-issue, ROB16/PRF48. Primary efficiency4 modes use
  LSU4 and the unchanged efficiency4 memory-policy validator; conservative modes
  use Selected LSU2 configuration,
  real frontend/MMU/PMP/retirement/private caches. No passive GSIM instrumentation.
- `CommonCpuClockBoundary`: actual depth16 CPU/fabric transport, separate real
  CPU/fabric input clocks, cold-start/reset release and sticky DDR-ready admission.
- `CommonMachineFabric`: actual Home, DDR AXI manager, MemoryCopyDma, packet DMA,
  timer/interrupt services and register/service boundaries. Programmable ROM has
  no initial image and remains exposed so it cannot collapse to an empty constant.
- Every fabric external service interface and CPU passive result is exposed;
  there are no fake DDR/peripheral responses and no placeholder blackboxes.

The complete flattened RTL dependency set is in `rtl-files.txt`, bound by
`package.json`. `ooc-identity.json` records actual CPU/fabric constructor parameters,
selection, clocks and compile receipt. Local Vivado needs no Scala/Mill/firtool,
external ROM image or repository paths. Emitted SystemVerilog may contain packed
arrays, which Vivado supports; the emitter does not force their unsupported
firtool expansion for RegisteredFetchPacket. Any unexpected memory/include dependency
is rejected by the packager, not silently substituted.

Modes:

- **efficiency4-candidate / efficiency4-baseline** (primary): actual
  FullR1M3EfficiencyRefactor4 CPU-private profile and exact memory policy, composed
  with the same Probe-Acquire fabric mode. Both retain the established third-fetch
  safe RAM range [0x80200000,0x80220000). Candidate adds banked indirect16 and compact
  issue immediates; baseline uses register indirect16 and expanded issue payload.
  This is a new combined qualification lineage, not inherited runtime evidence.
- **candidate**: indirect-target entries16 with banked storage and compact issue
  immediates; fabric completion flow/read overlap/Probe-Acquire overlap enabled.
- **baseline**: same indirect16 in register storage, compact issue off, same fabric
  mode. This isolates the W11/W14 CPU changes, not all prior bus changes.
- **unselected**: same CPU register/expanded representation as baseline, unselected
  fabric settings. Comparison to baseline isolates the explicit fabric selection.

All modes retain existing configuration requirements and source guards. None is a
public-qualified CPU identity or promotion of a default configuration.

## Timing boundary and exclusions

CPU clock is 10 ns (100 MHz), fabric clock 4 ns (250 MHz); setup/hold uncertainty
is 0.100/0.080 ns. These are test targets, not achieved frequencies. Optional
`--cpu-period NS --fabric-period NS` records different targets in invocation.json
and the resulting XDC without changing package RTL. Keep matched A/B periods. There are no
invented clocks, clock-group cuts, false paths or broad timing exceptions. Thus
cross-domain paths are conservatively timed as related clocks; a violation there
is not evidence of a functional synchronizer defect or board timing failure.

External port delays and board pin assignments are deliberately unspecified. All
boundary paths, including reset/service/DDR ports, must be reviewed as OOC boundary
paths, not signed-off external interfaces. Physical CDC signoff, async pointer
max-delay/bus-skew qualification and recovery/removal review remain separate work.
Do not treat the OOC summary's WNS as whole-board Fmax.

The managed peripheral bank, clock generators, PHY/GMII pads, debug vendor shell,
MIG, DDR electrical interfaces, package pin constraints and full board reset tree
are not included. The unchanged board flow remains under `fpga/common/`. Its
strict identity/interface guards reject unsupported optimized experimental exports;
this package does not bypass or weaken those guards and is not accepted as a board
input. The historical generic A1+fabric fixture's runtime result is not transferred
to this new combined candidate.

I1 is a different in-order CPU lineage and cannot be merged into A1's pipeline.
H uses the explicit experimental hypervisor tile with separate guest translation
and qualification boundaries, not this host-only A1 memory path. VPU is reserved,
not an implemented/qualified integrated vector datapath. These remain separate
sources and are not advertised by this package.

## Rebuild / packaging (maintainers only)

Keep the original repository and compile artifacts for source provenance. Produce
a real bound compile receipt using `fpga/common/scala_compile_receipt.py`; invoke
`platform.CombinedA1FabricTimingMain` through that receipt's exact runtime classpath,
with `-Dchisel.project.root` pointing at the actual checkout:

```text
platform.CombinedA1FabricTimingMain FRESH_OUTPUT efficiency4-candidate COMPILE_RECEIPT
```

Repeat with efficiency4-baseline (or supported conservative candidate/baseline/unselected) and fresh destinations. The optional fourth flag
`--emit-chirrtl-only` emits FIRRTL for reviewed external lowering; it is not RTL.
The emitter rechecks strict compile binding after emission. Never manufacture a
receipt or relax an identity check to accommodate stale classes.

Freeze already lowered output without running synthesis:

```text
python delivery/combined-20261108/package_rtl.py --emission FRESH_OUTPUT --out PORTABLE_PACKAGE
python PORTABLE_PACKAGE/run_local.py --verify-only
```

The main source dependencies are the production CPU/CDC/fabric constructors named
above, `CommonFabricDmaExperiment`, `CommonCpuProfile`, `CommonPeripheralConfig`,
`FpgaNextConfig`, `OooParams`, and their emitted transitive modules. The dedicated
emitter additionally uses `CommonFabricFlatPort` for real port reflection and
`CommonCpuMicroarchitectureIdentity` solely for serialization and compile binding.
No archived production qualification is relabeled as a current combined result.
