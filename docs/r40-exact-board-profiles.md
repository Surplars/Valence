# R40 exact board-target clock profiles

This changes tests only, not the frozen DRP/domain/gate hardware. Native validation
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
