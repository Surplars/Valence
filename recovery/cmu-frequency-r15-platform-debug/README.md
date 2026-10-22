# r15: ordered debug admission in the real runtime platform

This opt-in stage composes the real DMI admission barrier with the I1/fabric/AON
runtime epoch protocol. It does **not** enable frequency changes, physical clock
gating, a hart debug module, or a complete-system drain acknowledgement.

`CommonMachinePlatform(runtimeDebugAdmission = true)` requires I1 and the fixed
independent debug clock. It selects runtime-enabled tile/crossing/fabric ports,
instantiates the three-clock epoch boundary and the debug sequencer, and exposes
an explicit AON isolation endpoint. The legacy maintenance input is backpressured
in this mode so a second owner cannot bypass sequencing. The ordinary default
configuration remains disabled. CMU rate endpoints remain absent and their
runtime whitelist is not opened. A1 runtime isolation is rejected.

## Ordering and actual owners

1. AON allocates one epoch. The fabric-side prepare remains an unaccepted stable
   offer while its matching debug prepare crosses to the fixed debug clock.
2. New DMI requests are backpressured. Accepted DMI requests/replies and loader
   offered/awaiting RAM owners drain through the actual arbiter, AtomicDataMemory,
   coherent Home and memory path. Only matching debug-held proof permits the
   real CPU/fabric prepare. Existing I1 probes remain serviced; this ordering is
   not a claim that the old integration exhibited an inevitable probe deadlock.
3. CPU-control MMIO replies are separate genuine owners. The loader exposes its
   retained control response only in the opt-in configuration; final fabric
   obligations include both loader DMI/RAM and CPU-control idle. Scalar and
   crossing ledgers retain control replies after leaving the loader.
4. Timeout/cancel never clears accepted work. The existing AON watchdog can
   select cancellation while debug preparation is blocked; the ordered prepare
   still completes before actual CPU/fabric cancel cleanup. Debug cancellation
   is deliberately deferred until the real fabric terminal reports CPU resume.
5. Matching debug and fabric terminal copies are joined. AON consumption releases
   the debug terminal copy; its source-side consumption receipt permits the real
   debug terminal to fire with a reserved retirement receipt. Only that receipt
   permits the real fabric terminal and final AON retirement. A new epoch cannot
   overtake either owner. No fixed delay stands in for a remote edge or receipt.

## Fault and liveness contract

A short debug-link loss is captured asynchronously in both relevant domains.
During an owned epoch it produces an observable sticky fault, revokes observed
held/resume qualification, and blocks actual retirement until common cold reset.
Already accepted RAM work is not reset by the link transition. A previously
published terminal copy remains stable and may be consumed, but is **not** proof
that either owner retired; busy/fault and the retirement handshake remain
necessary. If the fault is observed before release selection, cancellation wins.
A fault after a selected release cannot rewrite its historical canceled bit.

Permanent RAM/CPU-control nonresponse, a paused required clock, or link loss can
therefore safely block forever. There is no bounded forced revival. Only a common
reset covering every owner and mailbox establishes a new epoch namespace.

## Evidence scope

The dedicated native fixture uses real I1 caches, CPU transport, CommonMachineFabric,
Home, 1 MiB internal RAM, APLIC/IMSIC and the actual loader. CPU-control accesses
come from retired guest instructions. Backpressure suppresses both sides of real
handshakes and never invents response payloads. Four independent running clocks
exercise debug plus CPU/fabric/AON. This is not external-DDR, network, fixed-timer,
physical CDC, gate, DRP, clock-startup or board signoff. The full production-size
opt-in platform is separately emitted, not natively qualified as an entire SoC.

Network admission, other peripheral/DDR crossing owners, stopped-fabric short IRQ
capture, real gate closed/open witnesses and official clock programming remain
separate prerequisites. A source-held IRQ contract or fixed-domain capture is
needed; a synchronizer in a stopped fabric does not capture arbitrary pulses.
The default 50 MHz startup goal and independent 300/250 MHz timing target are
unchanged. BootROM may boot Linux directly; U-Boot is not required by this stage.

The first native attempt passed the first clock ratio and reached the final
reset recovery in the reversed ratio, then failed the unchanged fixture's
startup-reset assertion because the testbench lowered boot enable on a coincident
active reset edge. Its exact failure receipt, logs and testbench are retained;
the corrected test asserts common reset on a fabric falling edge before lowering
boot enable. This is not counted as a passing run.

See summary.json and the exact receipts/logs for measured results. This directory
contains no vendor IP, generated netlist, or private physical-probe report.

## Reproduction

With the prepared cloud environment and an exclusive Mill slot, the runner can
freshly emit its own source-bound fixture and execute the bounded native cases:

```
source scripts/cloud/env.sh
python3 simulator/gsim/common/i1_runtime_debug_native.py \
  --emit --out out/cmu-frequency-r15/reproduction \
  --iverilog /workspace/scratch/41e4a649bb60/native-tools/bin/iverilog \
  --vvp /workspace/scratch/41e4a649bb60/native-tools/root/usr/bin/vvp
```

The output directory must not already exist. The full optional platform exporter
is `platform.CommonRuntimeDebugPlatformMain`; it is an elaboration entry point,
not a supported FPGA board configuration or a complete-system simulation claim.
The ordinary `CommonMachinePlatformMain` default export remains unchanged.
