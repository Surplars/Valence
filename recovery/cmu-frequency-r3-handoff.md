# R3 static low-clock prerequisites (not runtime rate support)

This candidate leaves the default production profiles unchanged and adds the explicit
`boot50-static` profile: CPU50/fabric50, DDR UI/timebase/debug250, AON/UART50 MHz.
The full CPU/cache/Home/MAC geometry is retained. This is a candidate for native
functional and physical validation, not a qualified bitstream or board boot.

Production integration now has opt-in complete five-channel AXI DDR CDC, a fixed
clock timer with complete register CDC/atomic time snapshots/synchronized IRQ,
and complete DMI request/response CDC. DDR-ready is synchronized into fabric.
A low-clock profile cannot silently instantiate without its required boundaries.
Independent AW/W storage permits W before AW; all AXI payload fields are preserved.
The AXI empty outputs are deliberately **transport-only**, never owner-drain ACKs.

The rate-register backend remains absent and the runtime whitelist remains empty.
No real CPU/fabric owner-drain, clock gating feedback, official DRP programming,
relock recovery, or live frequency switching is claimed. Static Clocking Wizard
configuration must be freshly generated through the board producer. Do not reuse
old CPU300 clock artifacts or the old hard-coded recovery constraint mapper.

## Cloud evidence

- Exact local handoff commit 276e3ec migrated and `ClockRateControlSpec` passed 3/3.
- Final combined focused Scala suites pass 26/26, including full I1 and A1
  low-clock platform elaboration and unchanged default platform elaboration.
- Actual I1 production-Vivado RTL emitted to `out/cmu-frequency-r3/boot50-i1`,
  with source/class/artifact-bound `emission-profile.json`. This is emission only.
- Native AXI fixture RTL emitted to `out/cmu-frequency-r3/axi-final-rtl`.
  Timer and debug fixture RTL emitted to `build/native-fixed/timer` and `debug`.
- Native behavioral fixtures are PREPARED_NOT_RUN in cloud. Vivado/xsim is absent.
- Pinned GSIM fails independent-clock edge/reset capability. Even tied-clock
  actual AXI boundary hits undeclared reset-alias C++ generator errors. Neither
  attempt is a functional PASS. See `cmu-frequency-r3-gsim-limitations.json`.
  Production reset semantics were not changed to accommodate the simulator.
- Original r2 physical evidence and the separate exact reset diagnosis at
  `reset-signoff-r2` remain preserved and do not qualify this new candidate.

The first combined test attempt had a repository-root path failure in a firmware
source inspection; rerunning unchanged tests with `-Dchisel.project.root` fixed
that environment issue. A preliminary accessor typo was fixed before final tests.
The initial same-clock fixture scalar port mismatch was also fixed before the
separate GSIM reset-generation blocker was established. No failing test was weakened.

## Reproduce and native handoff

Source `scripts/cloud/env.sh` in every cloud shell session. For tests requiring
repository files, append `-Dchisel.project.root=$PWD` to JAVA_TOOL_OPTIONS.
Run:

```
mill --no-server IonSoC.test.testOnly ip.ClockRateControlSpec ip.Axi4ClockDomainBoundarySpec platform.FixedTimeDebugBoundarySpec platform.CommonPlatformAbiSpec platform.CommonCpuTilesSpec
mill --no-server IonSoC.test.runMain ip.Axi4CdcFixtureMain <fresh-axi-rtl>
mill --no-server IonSoC.test.runMain platform.FixedTimebaseNativeMain <native-rtl>/timer
mill --no-server IonSoC.test.runMain platform.DebugDmiBoundaryNativeMain <native-rtl>/debug
```

On the existing local native Vivado installation, run the AXI fixture with
`recovery/run-axi-cdc-channels-xsim.ps1 -VivadoBin <bin> -DutDir <axi-rtl> -Fixture <fresh-evidence>`.
It checks unrelated/reversed clock ratios, stopped fabric, per-channel stalls,
W-before-AW, common-reset epochs and an injected-corruption negative oracle.
It is synthetic channel conservation, not a real memory/transaction-owner model.
Run timer/debug with `python simulator/cdc/run_fixed_time_debug_xsim.py
--rtl-root <native-rtl> --output <fresh-evidence> --tool-dir <bin> --run`.
The timer/debug helper alone does not qualify retained JtagRamLoader RAM owners.

Only after real native results should the official `fpga/common` producer freeze
an honest package with matching boot50 firmware, fresh official IP, complete
new-profile CDC constraints and actual affected-functional receipts. Native
synthesis/implementation must still resolve DCI/reset issues, retain exact new
clock/endpoint coverage, verify no_clock/CDC/RDC and meet setup/hold before a bit
or board acceptance claim. No blanket falsepaths or tied-high owner ACKs are added.
