# R37 reset recovery: distribution fix and separately scoped RDC entry proof

The R36 routed checkpoint is `b12abdc52c30c038b3a2a69fe89934c9c654d05255d8a5c2583ad059a1ed5cff`.
The focused native report ZIP is `951bfb4537e5b145ec9cbbe0c7e67755bbc71d3b7dd65a38f94fc17541882dc3`.
This change does not relax CPU300/fabric250, qualify an operating frequency, or
establish new routed timing. Actual 50/100 modes need their own routed STA.

## Different reset failures must not be conflated

* `fabric_clock/aon_reset_pipe_reg[2]/C` to
  `fabric_clock/gate/raw_reset_pipe_reg[0]/PRE`: recovery -1.590 ns,
  skew -4.387 ns. This is an asynchronous reset **synchronizer entrance**.
  The complete three-stage local release chain, not a timed AON-to-raw
  deassertion, makes this crossing meaningful. Normal DRP reset does not
  drive this cold-reset entrance.
* `u_soc/cpuRelease/release_0_reg[2]/C` to
  `u_soc/cpu/tile/dt/fastPage_reg[13]/CLR`: recovery -1.564 ns, 1,184
  failing endpoints, 4.780 ns data of which 4.700 ns is routing. This is a
  **functional reset distribution failure**, not an entrance exception.
* `ui_reset_pipe_reg[2]/C` to
  `u_soc/monitor/domain0/sourceRelease/release_0_reg[0]/PRE`:
  recovery -1.556 ns. The source RTL is a reset synchronizer, but the new
  gate-only helper does not cover it. Mapped proof/constraint coverage remains
  separate and unqualified; no broad `CdcResetRelease*` waiver is added.
* `delay_reset_guard_reg[63]/C` to
  `u_rgmii/delay_control_REPLICATED_0/RST`: recovery -0.066 ns. This is a
  functional IDELAYCTRL reset, not a three-stage reset synchronizer entrance.
  It remains timed and is a separate RX/physical implementation concern.

Recovery is the release-before-active-clock requirement; removal is its
after-edge counterpart. A reset-input false path suppresses both, not merely
asynchronous assertion. Do not describe the new exception as “assertion only.”

## Real dynamic-I1 distribution change

`CommonMachinePlatform` now inserts `ResetDistributionDriver` only when
`runtimeRateControl && profile.kind == "i1"`. The original `CdcResetRelease`
three-FF chain and its ASYNC_REG attributes are unchanged. Its final output
feeds one further CPU-clocked FF, asynchronously asserted by the same
`startupReset`. Only the I1 tile's functional reset uses this extra stage.
The boundary keeps its existing reset; the CPU now starts one edge later,
never earlier. Default-off and A1 branches retain their original connection;
this source-level statement is not a byte-identical full RTL comparison.

The new FF deliberately has no ASYNC_REG, DONT_TOUCH, or MAX_FANOUT attribute.
It is a legal physical replication candidate without cloning a metastability
resolution chain. Placement/physical optimization must actually show whether
replicas and local routing improve recovery. This is not a promised timing fix.
Both the final synchronizer-to-driver path and driver-to-functional CLR paths
remain normally timed. No new reset exception is applied to the driver.

`startupReset` remains cold/startup-only. Normal DFS merely pauses/restarts
CPU clocks and cannot clear architectural or accepted owner state through this
driver. Cold reset still asserts immediately with a stopped clock; cold release
requires three synchronizer edges plus one distribution edge.

The methodology is AMD's recommendation to place an ordinary replicable FF
after, rather than duplicate or unprotect, an ASYNC_REG synchronizer:
[UG949, Replicate High Fanout Net Drivers](https://docs.amd.com/r/en-US/ug949-vivado-design-methodology/Replicate-High-Fanout-Net-Drivers).
The asynchronous-assert/synchronous-release contract is described in
[UG974 2025.2, XPM_CDC_ASYNC_RST](https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/XPM_CDC_ASYNC_RST).
Our inferred chain is not an XPM instantiation and does not inherit XPM constraints.

## Exact four gate chains, not general reset coverage

The R36 focused native evidence proves CPU and fabric `raw_reset_pipe` and
`managed_reset_pipe`, three FDPEs each, INIT=1, ASYNC_REG=1, D0=GND, and
exclusive Q0-to-D1 / Q1-to-D2 fanout. Every raw PRE is directly driven by its
lane's `aon_reset_pipe[2]/Q`; every managed PRE by `gate/evidence_clear/Q`.
The final raw Q drives exactly 13 functional CLR pins; final managed Q exactly
four `managed_edges` CLR pins. Managed evidence reset is also used on ordinary
gate close/open, but resets only witness state, never retained architectural state.

Existing downstream worst max/min slacks, ns:

| Chain | Recovery max | Removal min |
|---|---:|---:|
| CPU raw | +0.405 | +0.332 |
| CPU managed | +2.849 | +0.119 |
| Fabric raw | +1.052 | +0.162 |
| Fabric managed | +3.193 | +0.274 |

`fpga/common/dynamic/reset_entry_constraints.tcl` is an explicit, initially
unwired hook. It reuses the existing native object lookup and pin helpers.
It proves all four chains, clock buffer identities/polarities, exact consumers,
and normal finite max/min paths before writing any exception. It then writes
only the twelve exact PRE endpoints and rechecks every interstage and functional
path. There are 84 path queries before and 84 after, with exact endpoint, clock,
requirement, exception and slack comparisons. Falling-edge raw consumers retain
their half-cycle recovery/removal requirements. Negative slack is reported as
negative, not silently qualified. No full-chip CDC collection is invoked.

After independent review, a native manifest may explicitly load the existing
`dynamic_clock_constraints.tcl`, then this helper, and call
`native_dynamic_reset::apply` after the unchanged target clocks exist.
Source/manifest hashes must bind both files. Native revalidation is still required;
the new helper is not automatically enabled by sourcing it or by this commit.

## Short affected checks

* Combined Scala compilation and `platform.CommonResetDistributionMain` emission
  passed. Real emitted three-stage chain plus new driver passed Icarus:
  12 phase/stopped-clock rounds, 360 checks, asynchronous cold assertion,
  exact four-edge release, and retained-owner preservation across 50/100-like
  pauses/restarts. This fixture has one real owner FF, not the whole CPU.
* Two ordinary oracle negatives alter observed early-release / lost-owner values;
  both are rejected by the same checks, not by a synthetic unconditional fatal.
* `tclsh fpga/common/test_dynamic_reset_entry.tcl` passes two diagnostic positives
  (including negative slack retained) and 25 structural/timing negatives.
  The reused existing LOCKED/UI tests also pass. Tcl mocks are not native proof.

Reproduce with the cloud environment and the coordinated Mill owner:

```
source scripts/cloud/env.sh
mill -i IonSoC.test.runMain platform.CommonResetDistributionMain out/r37-reset-distribution/rtl
python3 simulator/cdc/test_reset_distribution.py --rtl out/r37-reset-distribution/rtl --out out/r37-reset-distribution/check
tclsh fpga/common/test_dynamic_reset_entry.tcl
```

No bitstream, board execution, new full-system simulation, or native timing
acceptance is claimed by these focused tests.
