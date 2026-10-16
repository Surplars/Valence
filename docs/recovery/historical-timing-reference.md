# Historical RapidWright timing reference

This experiment uses the historical 223453b fully placed checkpoint and matched
Vivado 2025.1 `read-only-export-r2/setup_paths.rpt`. It is not the user's current
in-order RX failure and does not qualify current RTL.

## Valid numerical subset

| Same-arc comparison | RapidWright | Vivado | Observed difference |
| --- | ---: | ---: | ---: |
| CPU: 29 primitive arcs, FF C→Q plus 28 LUT arcs | 2.592 ns | 2.577 ns | +15 ps (+0.58%) |
| Reset source FF C→Q | 77 ps | 79 ps | −2 ps |
| CPU endpoint same-site B6LUT/O6→BFF/D | 50 ps | 59 ps | −9 ps |

CPU endpoints are backend/systemUnit/privilege_reg[1]/C and
backend/stagedMemoryAddress_reg[47]/D under
u_soc/board/platform/core/core/core. The reset endpoints are
u_rgmii/pad_release.pad_release_reset_reg/C and u_rgmii/previous_clock_reg/CLR.
All CPU primitive arcs had supported physical BEL/pin mappings; their individual
observed differences were −2 to +5 ps. The same-site wire entry is separate from
the primitive subtotal. These are observations on this checkpoint, not error
bounds or a general model accuracy guarantee.

The SmallDelayModel's bundled logic table is load-independent. Its generic
UltraScale+ coefficients do not reproduce every Vivado process corner,
speed-grade, transition, slew or loading context.

## Rejected raw values and missing coverage

| Diagnostic query | Raw RapidWright result | Validity |
| --- | ---: | --- |
| serializer_reset net | 5 ps | Invalid: no inter-site PIPs |
| bareOrdinaryRam2 net | 43 ps | Invalid: no inter-site PIPs |
| Reset endpoint CLK→SR check | −2 | Unsupported |

The first two raw results are incomplete model outputs, not net-delay predictions;
no numerical difference or ratio is calculated from them. The original Vivado
CPU report assigns 7.330 ns to nets and 2.577 ns to logic. Thus the unmodeled
interconnect is most of the path, and the close primitive-only comparison does
not establish full-path agreement.

The original bounded run tested 24 exact-name nets, reconstructed 381 site-pin
instances in memory, and added no PIPs. Six other report net names had no exact
physical-name match and were explicitly skipped rather than guessed. Restoring
site pins does not restore routing. A direct intra-site lookup can still be valid
without inter-site PIPs, as shown separately above.

No full-SoC timing graph was built. The installed TimingModel walks stored PIPs;
its timing manager's single period-derived requirement does not establish
agreement with the generated-clock phase, uncertainty, CPR and recovery checks
of this report. No new WNS, Fmax, hold or recovery slack is reported.

## Reproduction and evidence

The [portable runner](../../scripts/cloud/rapidwright_timing_reference/README.md)
requires explicit bundle, report, tool-root, JDK and output-root arguments. It
matches exact source/destination names, snapshots inputs/source, compiles only
the Java analysis snapshot and creates a fresh evidence directory per invocation.
Raw net results remain invalid and are never aggregated. A primitive subtotal
requires every selected arc to be supported.

Original bounded execution completed in 36.76 seconds including compilation.
All 41 bundle files were unchanged; the original checksum manifest passed 38/38.
The portable rerun completed in 42.79 seconds, reproduced all three valid
comparisons, and confirmed all 41 originals plus the three snapshots unchanged.
Its exact report-block hash also distinguishes the CPU rise/fall variants sharing
the same endpoints. Six pure fail-closed parser tests passed. Failed initial
attempts are preserved outside Git. No raw DCP, EDIF, device data,
class files or run output is included with this source-only tooling.

Pinned original DCP SHA-256:
`6b2d34c47326d130b4fde46552d9870aaad5ad7e7d608f48aca4cb686cff5928`.
The portable runner records exact input/source/model hashes in each receipt.

A meaningful inter-site/full-path comparison requires matched routed inputs or
a separately authorized routing/implementation experiment. Neither was performed.

## Primary sources

- [TimingModel API](https://www.rapidwright.io/javadoc/com/xilinx/rapidwright/timing/TimingModel.html)
- [DelayModel API](https://www.rapidwright.io/javadoc/com/xilinx/rapidwright/timing/DelayModel.html)
- [Official timing example](https://www.rapidwright.io/docs/ReportTimingExample.html), which consumes a placed-and-routed checkpoint

Online documentation can describe a newer release. This experiment used the
installed 2025.1.3 API/bytecode and pinned bundled model files as the executable
reference.
