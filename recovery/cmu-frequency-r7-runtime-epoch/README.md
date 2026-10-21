# R7 opt-in I1 / Home held runtime epoch

This checkpoint is a default-off endpoint protocol, **not working runtime clock switching**. `CommonCpuTilePortParams(runtimeMaintenance=true)` enables it. No production platform or CMU backend instantiates this option; runtime frequency whitelist remains empty, A1 explicitly rejects the option. BootROM may continue directly to Linux without U-Boot. Hardware startup 50 MHz remains the integration target; independent performance implementation constraints remain CPU 300 / fabric 250 MHz.

## Protocol

1. An accepted external maintenance command owns its epoch. I1 requests a precise architectural stop while already accepted core/cache/transport work remains live.
2. After architectural stop, a single pulse flushes both private caches. Both completion bits, real private-owner quiescence and native adapters must drain before offering status. Held/probe/release/E/response owners are not replaced by FIFO empty or core stopped.
3. Fabric validates held status against its accepted external owner and epoch, then uses the existing real Home/accepted-owner drain machinery. An older ordinary FENCE.I may finish between external prepare and runtime status without losing the external owner.
4. Consuming completion does not release the Home barrier. Only explicit matching runtime resume releases it and queues the CPU resume message. Backpressure keeps that message stable; overlapping maintenance stays blocked until delivered. CPU waits for matching completion plus current private idle before accepting resume.

`runtimeHeld` is only a local-domain observation, not a complete AON clock-gating ACK. Fabric completion can precede CPU delivery over CDC; MSI and control queues require refreshed ownership/empty observations. Late accepted probes can temporarily revoke tile-local readiness. The optional resume mailbox is included in control transport emptiness. Coordinated cold reset remains the cancellation boundary; independent domain resets and clock switching are not tested here.

## Verified results

- Real fabric GSIM runtime and default runs pass. Runtime covers held completion, parked newer Acquire, backpressured CPU resume, older ordinary FENCE after external prepare, and subsequent ordinary FENCE automatic completion. Early, stale/wrong and duplicate resume are each rejected by the exact DUT assertion. Independent data corruption is rejected. Default remains 1247 cycles.
- Real full-capacity I1 tile plus private caches plus Home/fabric, delayed internal RAM, native Icarus: 4 runtime epochs, 140 held cycles, 24 stores and 24 loads, 32 dirty release beats. Independent retire/data scoreboards pass; intentionally wrong load oracle fails. No architectural work is admitted during held intervals. This is a single-clock fixture with no CDC queues, not a multi-clock system test.
- Fresh default-off production performance export has 248 SystemVerilog files. Every file is byte-identical to the corrected r6 export; no new or removed files. Therefore this stage adds no default production ready chain or default hardware behavior.
- R7 private-cache component checkpoint separately covers partial D, held E, held response, dirty ReleaseAck, late held probe C after sticky flush completion and native response, including six incorrect-owner negatives and ReadFirst collision proof.

The existing r5 real-core trap/IRQ/MRET/SRET precise-stop traces remain relevant because the core implementation is unchanged. This new combined fixture does not add a full interrupt-pending or trap-directed program; that integration coverage remains a required follow-on before system clock-gating acceptance. No AMO-specific combined trace, independent-clock epoch CDC test, physical timing or board acceptance is claimed.

## Reproduce

Source `scripts/cloud/env.sh` before each command.

- `python3 simulator/gsim/common/fabric_machine.py --cloud-tools --runtime-maintenance --out <fresh-runtime-directory>`
- `python3 simulator/gsim/common/fabric_machine.py --cloud-tools --out <fresh-default-directory>`
- `python3 simulator/gsim/common/i1_runtime_epoch_native.py --out <fresh-native-directory> --iverilog <existing-iverilog> --vvp <existing-vvp>`

Clean pinned GSIM cannot generate its retained-Vec accessor API correctly, so the cloud real-fabric fixture exposes leaf scalar test ports through direct wires around the unchanged fabric. No simulator backend or generated model logic is patched. The original explicitly qualified runner mode remains available.

## Remaining connection work

AON CMU must own an epoch and handshake prepare, combine matching CPU and fabric held observations with all actual transport/interrupt/peripheral drains, and hold that contract until matching explicit resume. Clock gate closed/open confirmations, safe reset/lock-loss handling, official generated MMCM DRP configurations, target-lock confirmation and timeouts/rollback are still absent from a real backend. No guessed DRP words or unconditional ACK may fill those gaps. Do not enable the production option or rate whitelist based on these component results.
