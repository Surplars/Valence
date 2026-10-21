# CMU decoder integration: local-to-cloud handoff

This stage adds the rate page to the real CommonMachinePlatform / ManagedPeripheralBank CMU path. The source-domain router preserves ordered replies across legacy and rate pages; only the upstream response handshake acknowledges the rate boundary. The existing legacy CMU instance and 0x68 gateable resource ownership are retained.

CPU rate registers are at 0x10080800, fabric at 0x10080880. Production endpoints are explicitly absent and qualification lists empty: commands return BackendAbsent, actual frequency reads zero while invalid, absent startup does not invent timeout/fatal errors. Clock outputs are not connected. Existing CPU300/fabric250 physical clocks remain unchanged; CPU50 boot is still a requirement for the next integration, not accomplished hardware behavior.

Validation: affected Scala compilation and both production-lowering fixture emissions completed; ip.ClockRateControlSpec 3/3 passed including real ManagedPeripheralBank elaboration. Native Vivado2025.2 xsim direct: 764 AON cycles,24 requests/replies; integrated legacy+rate:846 cycles,32 requests/replies. Both preserve15/15 owner completions,237 stopped-CPU cycles,8 stalled reply cycles and reject the deliberately wrong oracle. Integration covers original identity/metadata, protected CPU STOP rejection, two interleaved page owners, absent-backend startup and invalid actual-frequency reporting. Qualification flags and backend/owner models in simulation are synthetic. No full-platform emission, synthesis, implementation or board qualification was performed in this stage. Initial integrated runner macro parsing failure is retained and fixed without changing RTL.

## Resume in cloud

Fetch the recovery/common-idle-source-20261021-r1 branch (do not overwrite unrelated cloud changes). Read ClockRateControl.scala, ClockRateManagement.scala, ClockRateRegisterRouter.scala, ManagedPeripheralBank.scala and CommonMachinePlatform.scala. Next connect real owner/drain/quiesce to AON control, independent fixed AON and clock gates, official tool-generated MMCM DRP images and safe boot50/relock/reset dependencies. Fabric clock separation additionally requires correct complete AXI CDC to fixed MIG UI, fixed timebase and fixed-domain peripherals. Never replace these with tied-high ACKs. Qualification remains closed until component and whole-SoC timing evidence exist.

Affected portable check: mill --no-server IonSoC.test.testOnly ip.ClockRateControlSpec. Fixture emitters: IonSoC.test.runMain ip.ClockRateComponentMain <dir> and ip.ClockRateCmuIntegratedMain <dir>. Native Windows behavior replay: recovery/run-clock-rate-component-xsim.ps1 -VivadoBin <bin> -DutDir <emitted-dir> -Fixture <fresh-dir>, adding -Integrated for the legacy/rate fixture. No Verilator. Cloud GSIM adaptation has not been validated here.

See cmu-frequency-r2-integration.json for exact source/RTL/raw-log hashes and counts. Local raw evidence remains in out/cmu-frequency-r1 and out/cmu-frequency-r2; the JSON is portable, the raw native runs are not uploaded. Historical f87870c physical timing evidence is unchanged and does not qualify new rate hardware.

## Cleanup protection

Until cloud migration and evidence retention are confirmed, protect C:\Users\surplars\Documents\Codex\2026-10-19\task-3 in full: recovery-r1/.git, current source and recovery records, out/cmu-frequency-r1 and r2 raw native evidence, CURRENT, and .tools used by local verification. Pre-existing untracked recovery receipts and dfx_runtime.txt are retained, not included in this stage. No new local development or long-running implementation is planned after push.
