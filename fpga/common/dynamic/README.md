# Experimental independent native dynamic clocks

**Opt-in only: `boot50-dynamic`. Not board-qualified; no admitted software points;
no bitstream. Existing static profiles are unchanged.** This is a synthesizable
MMCME4_ADV/BUFGCE backend, not a change to a simulator-only clock-rate field.
The Cloud Icarus tests validate the transaction/state/evidence protocol against
an explicitly approximate model. They do not validate vendor primitives,
physical clock quality, CDC/RDC, routed timing, or an integrated SoC.

## Hardware and reset contract

* Stable clk_wiz_common owns AON50 only. Separate CPU and fabric MMCME4_ADV
  instances use DDR UI250. Network, UART50, timer250, DDR250 and debug250 remain
  fixed. `cpu_locked`/`fabric_locked` do not drive common cold reset.
* Each domain boots with D=10, M=40, O=20 (50 MHz). Cold reset explicitly writes
  O20 again because primitive RST does not restore the DRP registers.
* Program/reset affects only that domain's MMCM. It never resets architectural,
  FIFO, drain, epoch, timer or transaction-owner state. Top-level genuine cold
  reset still has its existing system semantics.
* Two lanes map to `rateBackend_0_*` (CPU) and `rateBackend_1_*` (fabric).
  The backend consumes `clockEnable`, `isolate`, program(valid/hz/token/fallback),
  result.ready. It produces present, gateClosed, gateOpen, locked, resumed,
  fatal, program.ready and result(valid/hz/token/error). `quiesce` is owned by
  platform drain logic, not a primitive reset signal. Four real drain ACKs stay
  within the platform, not manufactured by this backend.
* DRP accepts only while isolated and proven closed, with external enable low.
  Its successful result means registers were written and read back, **not**
  that lock/resume or epoch retirement is complete. The controller must await
  stable lock plus real managed-clock edges before releasing owners/admission.
* Gate closure uses a fresh close token and four settled negative **raw-clock**
  edges after CE went low, returned through AON synchronizers. This evidence is
  conditional on the documented, timed BUFGCE `CE_TYPE=SYNC` contract. There is
  no fictional native output-closed port. No raw edges means no fresh closure
  ACK. Reopen requires two real managed rising edges; resumed requires four.
  Both witnesses clear even for a short disable while the target is stopped.
* DRP has one outstanding access. Timeout reports an error but keeps MMCM reset
  and quarantines late DRDY; a four-AON-cycle quiet gap precedes explicit50
  fallback. Permanently missing DRDY becomes sticky fatal. Outstanding transport
  ownership survives common cold reset; a cold reset cannot turn a stale reply
  into a new boot transaction. If the primitive never responds, full device
  recovery is needed, not repeated controller reset pretending to recover.
* Unexpected lock loss before proven gate closure is fatal even after a disable
  request. Fatal closes the gate path and prohibits new programming. The
  controller must preserve isolation and unresolved owner state. It must not
  translate fatal into an automatic common cold reset or successful retirement.

## Deliberately narrow register program

Only 50 and100 MHz are encoded. These are implementation/test candidates, **not
production-supported rates**. Other points, including55 MHz, return an error
without DRP. The 31 CPU/21 fabric candidates in the earlier parameter-feasibility
receipt are not a register-program whitelist or board qualification.

Input250 / D10 = PFD25 MHz, M40 gives VCO1000 MHz. Fixed M/D means dependent
lock/filter configuration stays unchanged. Each operation is read/modify/write/
readback at power0x27, CLKOUT0 Reg1=0x08, Reg2=0x09:

| Address | Preserve mask | New bits | Meaning |
| --- | --- | --- | --- |
| 0x27 | 0x0000 | 0xffff | UltraScale/UltraScale+ power bits |
| 0x08 | 0x1000 | 0x028a (50) / 0x0145 (100) | high/low counts10/10 or5/5; phase0 |
| 0x09 | 0x8000 | 0x0000 | no fractional/phase/odd-divide fields |

The independent test monitor rejects any other address (including the incorrect
7-series power0x28), validates all outgoing fields and reserved masks, and
therefore protects unchanged M/D/filter/lock words. The model's frequency comes
from register0x08 rather than the requested frequency. It does **not** accurately
model MMCM analog behavior, power fields, fractional timing or BUFGCE silicon.

Official references:
* [AMD XAPP888 v1.8](https://docs.amd.com/api/khub/documents/ZY272QvKAP3T95qOg6QhDg/content), tables1/2/14/15 and reset/reconfiguration flow.
* [UG572 BUFGCE](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/BUFGCE-Clock-Buffers), synchronous glitch-free gating contract.
* [UG572 LOCKED](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/LOCKED), reset after unexpected loss.
* [UG974 MMCME4_ADV](https://docs.amd.com/r/en-US/ug974-vivado-ultrascale-libraries/MMCME4_ADV) and [BUFGCE](https://docs.amd.com/r/en-US/ug974-vivado-ultrascale-libraries/BUFGCE), primitive ports/attributes.

## Reproducible cloud checks, no Verilator

```sh
source scripts/cloud/env.sh
python3 fpga/common/dynamic/run_behavioral.py \
  --iverilog /absolute/verified/iverilog --vvp /absolute/verified/vvp \
  --out /fresh/output/dynamic-clock-behavioral
```

Covers independent50→100→50, continuous AON/other domain, retained counters,
actual-edge witnesses, supported/unsupported requests, backpressure, readback
failure, delayed/permanent DRDY, no lock, unexpected loss including close-tail,
boot50 after cold reset from100, reset during an old DRP operation, and five
precise reset/transport boundary cases. Stretched/stuck DRDY tests ensure no
fresh DEN is issued until the previous response is low; permanent high fails
closed after a bounded quiet-time deadline. Negative controls force fake closure,
fake resume and a wrong output rate and must fail on the corresponding oracle.
The vendor testbench is additionally syntax/oracle-smoked under the model with
an explicitly non-vendor pass marker. This is not UNISIM evidence.

## Prepared local native commands, NOT run in cloud

After explicit permission for the user's local machine, from a frozen combined
checkout with native Vivado2025.2, set `VALENCE_VIVADO_HOME` to its install root:

```powershell
& "$env:VALENCE_VIVADO_HOME\bin\vivado.bat" -mode batch -source fpga/common/dynamic/validate_native.tcl -tclargs (Get-Location).Path E:/fresh/dynamic-unisim simulation
& "$env:VALENCE_VIVADO_HOME\bin\vivado.bat" -mode batch -source fpga/common/dynamic/validate_native.tcl -tclargs (Get-Location).Path E:/fresh/dynamic-component-synth synthesis
```

The first compiles **only production RTL plus the vendor testbench and glbl**,
links unisims_ver, and must emit DYNAMIC_CLOCK_UNISIM_PASS with no error/timing
violation. It measures both actual vendor primitive outputs at50/100, pulse
width, close/reopen, independence, and reboot50. No behavioral primitive may be
present. This does not exercise model-only injected faults or the entire SoC.
The second uses exact xczu15eg-ffvb1156-2-i, checks actual50 MHz generated clock
and required primitives, saves an explicitly unqualified component checkpoint,
CDC/coverage/CE timing/DRC reports. It does not qualify the board I/O or timing.

Next required combined-board steps are generated Scala port/contract audit,
fresh native export, synth/opt with `dynamic_clock_constraints.tcl`, scoped CDC
and RDC review, then actual place/route and timing. `synthesis_targets.xdc`
is loaded automatically BEFORE synth_design, setting only the CPU300/fabric250
requirements on the two actual managed-domain source pins. The checker in
`performance_targets.tcl` rejects missing/relaxed constraints instead of adding
them after synthesis. It also verifies unchanged UI/DDR250, AON/UART50,
network125/250/500, debug/timebase250 and their UI-rooted master relationships;
it runs again after optimization. `dynamic-boot-parameters.txt` separately
records the actual initial MMCM D10/M40/O20 configuration corresponding to50
MHz. The constrained300/250 clock report is **not** actual runtime-frequency
proof and does not replace native measurement. Additional operating-point
scenarios remain necessary for CDC/hold/phase and physical qualification.
CPU300/fabric250 are unchanged requirements, not claims that the fixed-M
register sequence generates those rates. Never use boot50 timing as their
replacement. Do not false-path CE, owner resets, payload or all inter-domain
paths to make reports pass. Validate fixed peripheral clocks remain unchanged,
DRP/DCLK limits, all CE setup/hold and pulse widths, lock/reset recovery and
source/destination owner CDC/RDC at every admitted operating point. Until those
proofs and integrated fault/epoch tests pass, board manifest/signoff rejects
boot50-dynamic and all software point lists remain empty.
