# R40 exact board-target clock profiles

R1 changed tests only. R2 additionally connects15 unused primitive outputs to
no-load local wires; all functional hardware is unchanged. Native validation
is pending until a matching `run_board_profiles.py` receipt says PASS. Profile
legality, primitive simulation, routed STA and board qualification are separate.

## Exact software ABI and independent images

Input250 MHz, D10, PFD25 MHz, integer feedback/output, phase0, duty50%, LOW:

| Request | M | O | Packed O/M/D | VCO MHz | output/UI ratio |
|---|---:|---:|---|---:|---|
| CPU195 | 39 | 5 | `0x05270a` | 975 | 39/50 |
| fabric155 | 62 | 10 | `0x0a3e0a` | 1550 | 31/50 |
| cold/return50 | 40 | 20 | `0x14280a` | 1000 | 1/5 |

The firmware worker confirmed these exact canonical tuples. No interchangeable
profile may silently replace them in firmware, primitive tests or mode STA.
The prior 204-check native suite covered the initial21 profiles and limits, but
not these exact195/155 tuples. Its timeout, reject and fallback evidence remains
its original scope; this focused normal loop does not inject hardware faults.

The new `+board195155` branch uses literal counter/LOW lock/filter images, not a
DUT function. M39 counter=04d4/edge0080; M62=07df/edge0000; M40=0514/edge0000.
D10 counter=0145; O5=0083/edge0080; O10=0145; O20=028a. All three LOW lock words
are00fa/7c01/7fe9. Filter1 is9800 forM39/M40 and9900 forM62; Filter2 is0890.
These values match the original pinned AMD driver function output recorded in
`software-parameters.json`, not JSON generated from the DUT:
https://github.com/Xilinx/embeddedsw/blob/acf980174aada76637ac02c1e01088f3cc7b04dd/XilinxProcessorIPLib/drivers/vphy/src/xvphy_mmcme4.c
Original SHA256: c6a22352a0a47052fb4c3563cb9a5a2044532df67782fb16cf8f886152d3f048.

The focused loop is50/50 →195/50 →195/155 →195/50 →50/50. Every command uses
normal software programming (including return50), exact token/result identity,
real close/open/resume edge feedback, lock wait, frequency/independence count and
runt/closed-edge oracle. All44 words/132 read-write-readback commands are checked
against preserved bits plus independent literals. Existing finite ready/result/
lock/resume and overall simulation deadlines remain. Two negatives corrupt an
expected register bit or frequency count and must fail the ordinary oracle.

## Native command

From the package root, with a fresh output directory:

    python fpga/common/dynamic/run_board_profiles.py native-result --vivado-bin E:/Xilinx/2025.2/Vivado/bin

The runner compiles only unchanged hardware, the testbench and official glbl,
links official unisims_ver, and never includes behavioral_primitives.sv. Explicit
xelab timescale is1ns/1ps. Compile, elaborate and positive runtime reject all
warnings/errors; negatives require their exact fatal oracle and no warning.
Each command has120s wall limit; timeout is FAIL, not a partial PASS. No synth,
bitstream, board operation or production-qualification update occurs here.

## Same-route actual-mode STA addendum

Keep the original routed DCP and CPU300/fabric250 performance reports unchanged.
Use fresh analysis copies for the three unique stable pairs visited above. The
already validated50/50 modeling method is extended by changing **both M and O**:

    # Example195/155 only, on a fresh analysis copy, never the bitstream source.
    set_property CLKFBOUT_MULT_F 39.000 [get_cells cpu_clock/mmcm]
    set_property DIVCLK_DIVIDE 10 [get_cells cpu_clock/mmcm]
    set_property CLKOUT0_DIVIDE_F 5.000 [get_cells cpu_clock/mmcm]
    set_property CLKFBOUT_MULT_F 62.000 [get_cells fabric_clock/mmcm]
    set_property DIVCLK_DIVIDE 10 [get_cells fabric_clock/mmcm]
    set_property CLKOUT0_DIVIDE_F 10.000 [get_cells fabric_clock/mmcm]
    create_generated_clock -name cpu_target300 -source [get_pins u_ddr/c0_ddr4_ui_clk] -multiply_by 39 -divide_by 50 [get_pins cpu_clock/mmcm/CLKOUT0]
    create_generated_clock -name fabric_target250 -source [get_pins u_ddr/c0_ddr4_ui_clk] -multiply_by 31 -divide_by 50 [get_pins fabric_clock/mmcm/CLKOUT0]
    update_timing -full

For a50 lane, restore M40/D10/O20 and ratio1/5. Read back primitive properties and
unique generated-clock/master ancestry at MMCM, observer and managed outputs.
Expected periods are200/39ns and200/31ns, and20ns at50. Keep LOW, phase0, duty0.5,
feedback compensation and actual input jitter unchanged. Read the real feedback
clocks rather than assuming they run atVCO: the existing design reports external
feedback40ns/PFD25MHz withD10. Verify this on the new native graph.

The VCO changes to975/1550 must be visible to the native jitter/phase-error model;
output-period-only substitution is insufficient. Native post-route property
update semantics must be checked, not assumed. A model warning or missing clock
ancestry blocks this scenario. Do not introduce primary clocks, false paths,
case-analysis, zero uncertainty, or new phase-alignment assumptions.

Preserve all non-clock constraints and endpoint coverage, scoped reset/CDC
exceptions and budgets. Verify unchanged UI250, AON50, MAC125, PAD250, delay500,
RX450 configuration and board I/O timing. Reuse structural proof only for this
same unchanged graph; do not rerun whole CDC collect per mode. Both corners must
cover setup/recovery and hold/removal, CE, pulse width, functional resets and
unconstrained/no-clock coverage. The original performance model remains a
separate result even if an operating mode passes.

Static property edits model steady state, not actual DRP analog transition,
relock/gate behavior, PVT or on-board success. Native UNISIM also does not prove
those physical properties. A future bitstream must use the original cold
M40/D10/O20 LOW routed design, never these analysis copies. Mixed pair coverage
cannot be replaced by per-lane flags; no claim qualifies all59 mathematical
frequencies or all software-admitted requests.

Official command/model references:
- https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/create_generated_clock
- https://docs.amd.com/r/2025.2-English/ug906-vivado-design-analysis/Timing-Path-Summary
- https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/config_timing_corners

## R2 native elaboration correction

R1 native elaboration failed before all simulations on VRFC10-3645: CDDCDONE
was omitted from the production primitive instance. No profile passed in R1.
R2 explicitly connects all15 unused MMCME4_ADV outputs to separate no-load wire
bits. No input, active output, primitive parameter or functional logic changes.
The Icarus-only model gains these unused output declarations, never native use.
A focused source test removes exactly these declarations/connections and requires
byte-identical original domain SHA e9bc1466fdfc3cceefb5af66fb1873a88c267643b7650a74c8f81a5bba64c5c4.
This is a documented source delta from the routed/bitstream source, not a claim
that new hashes equal old ones. It changes no used logical connection and does
not require rewriting the existing bit for this native elaboration correction.
All warning gates remain strict. Official output directions/names:
https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/MMCME4_ADV

## Exact125/125 follow-on (native pending)

The prior204 native suite's125 point is **D10/M50/O10**, packed0x0a320a,
VCO1250MHz (`switch_rate`: O10 then M=125*10/25=50). It does not establish
D10/M40/O8, even though output frequency is also125MHz. The new bounded mode
matches the current actual-mode STA and explicit diagnostic firmware override:
**D10/M40/O8, packed0x08280a, LOW, PFD25MHz, VCO1000MHz, ratio1/2**.
The global canonical firmware solver and bootROM are not changed by this test.

    python fpga/common/dynamic/run_board_profiles.py native-result-125 --vivado-bin E:/Xilinx/2025.2/Vivado/bin --profile 125125

This uses the same native runner, exact44-word/132-command audit, finite waits,
zero-warning policy and two ordinary-oracle negatives. Sequence50/50→125/50→
125/125→125/50→50/50 returns fabric first. The only new literal image is O8:
high4/low4, counter0104, edge0000. M40 and all LOW lock/filter settings equal
boot50. Hardware files are unchanged from the no-load-output R2 correction.
The previous195/155 branch is retained as default; its native R2 result was
reported PASS9checks44words132commands plus2negatives, zero warnings,20.153s.
That primitive pass does not overturn its independently failing routed STA.

For125 operating STA, keep M40/D10 and change O8 with generated ratio1/2;
50 usesO20 and ratio1/5. Preserve all native-model/constraint/reset/CDC checks
above and original performance300/250 reports. A125 mode may not borrow the
M50/O10 characterization or be represented only by editing its clock period.
