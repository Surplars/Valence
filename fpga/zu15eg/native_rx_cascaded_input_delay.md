# Unconnected RX delay candidate

`native_rx_cascaded_input_delay.sv` is deliberately absent from production source
lists and tops. Its unusable default requires an explicit per-stage value. It
must replace, not follow, an existing input IDELAY if eventually qualified. No
board timing constraint, PHY setting, capture clock, or production delay changes.

The dedicated topology is IDELAYE3 MASTER to ODELAYE3 SLAVE_END and back to the
master DATAOUT. Both stages share one parameter, TIME/FIXED, 500 MHz calibration,
VALENCE_RGMII group, reset and permanently asserted EN_VTC. The existing bank
IDELAYCTRL and reset/readiness qualification must be retained. Native resource
inspection must establish a compatible available ODELAY at every RX IOB first.

Reference: AMD UG571 v1.16, “Cascading Delays”, pp. 168–170:
https://docs.amd.com/api/khub/documents/kFbaUC5HGcXyGNauhgU6Gw/content
TIME cascades require equal stage settings. Dedicated cascade insertion is
additional physical delay, so total delay is not twice the parameter and zero
is not a bypass. No parameter is selected or timing improvement claimed here.

## Acceptance gates

1. Preserve all ten original RX max/min reports, existing calibrated controller
   configuration, reset/EN_VTC drivers and exact five site/BEL occupancies.
2. Prove the exact device/package supports all five same-IOB dedicated cascades
   without stealing occupied or incompatible resources. Absence of a named BEL
   is not proof of available hardware.
3. Use native corner models to choose settings. r34i2's measured uniform-delay
   window is a *necessary estimate only*: added min delay at least 122 ps and
   added max delay at most 281 ps for zero slack; 172–231 ps with 50 ps margins.
   Actual cascade insertion and clock-tree changes can invalidate this estimate.
4. Run primitive elaboration and targeted functional checks with supported tools,
   then one authorized native candidate. Require all five RX inputs, both edges,
   min/max corners and every unrelated domain to be rechecked with unchanged
   board constraints. Retain reset/readiness and tri-speed capture behavior.
5. No board-ready claim while global setup or CDC qualification remains open.

## Offline test

`python3 fpga/zu15eg/test_rx_cascaded_input_delay.py`

This checks wiring/parameter invariants and rejects twelve deliberate mutations.
It is a source-contract test, not an HDL parser, synthesis, primitive simulation,
resource/DRC check, PVT model or timing proof. A second bounded test is available after sourcing `scripts/cloud/env.sh`:
`python3 fpga/zu15eg/test_rx_cascade_interface.py`. Icarus 12 compiled the module
against interface-only black boxes transcribed from UG974 2025.2, accepted stage
0/200/550/1100 and rejected -1/1101 with the guard at time zero. These stubs have
no behavior and must never be included in production or physical source lists.
This is syntax/interface/guard coverage, not actual vendor primitive elaboration
or functional simulation. No Vivado was run.

Port references (version matched to the native tool):
- https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/IDELAYE3
- https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/ODELAYE3
