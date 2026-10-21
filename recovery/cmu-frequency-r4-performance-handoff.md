# Independent-clock performance target (not runtime DVFS)

`performance300-static` is an I1-only CPU300/fabric250/TIME250 MHz static target.
It retains the same CPU/cache/owner geometry and DDR AXI, timer and DMI CDC topology
as `boot50-static`. DDR UI and debug stay250; AON/UART stay50. The unchanged
`production` profile has the historical direct-UI fabric topology and must not be
presented as an identical-topology comparison. Frequency-dependent constants and
metadata differ between profiles; emitted RTL is not claimed byte-identical.

The official producer creates fresh Clocking Wizard IP, including a separate
fabric output even when its frequency equals DDR UI. Do not reuse old clock
DCP/XCI, relabel a50MHz clock300MHz, change generated-clock periods independently
of physical IP, or treat boot50 timing closure as high-frequency qualification.
Runtime frequency requests remain rejected; no one-bitstream50-to300 transition
is implemented. This checkpoint does not enable a DRP backend or relax drain,
reset, CDC, native-validation or final timing gates.

## Native local sequence

Use a fresh output directory and preserve failures. Replace `FRESH` and tool
paths with actual local absolute paths. First run the existing AXI/timer/debug,
composed-loader and DCI native fixtures from this revision; earlier GSIM clocks
and reset cannot qualify independent clocks. Do not fabricate acceptance receipts.

1. Run `mill --no-server IonSoC.test.testOnly platform.CommonCpuTilesSpec platform.CommonPlatformAbiSpec`.
   Record the actual command exit as `FRESH/compile-receipt.json` with an `exit`
   integer. Set `JAVA_TOOL_OPTIONS` to include `-Dchisel.project.root=REPO`.
2. Run `mill --no-server IonSoC.test.runMain platform.CommonMachinePlatformMain FRESH/rtl i1 --vivado-memories --clock-profile=performance300-static --compile-receipt=FRESH/compile-receipt.json`.
3. Populate a NEW package following `fpga/common/README.md`; preserve actual
   source/artifact hashes, MIG XCI and full firmware. Firmware must bind
   fabric250/TIME250 and CPU300 nominal metadata (or unchanged shared-ROM CMU
   nominal-register contract). The affected functional receipt must actually
   pass and match this configuration, not the boot50 hash.
4. Freeze populated inputs with:
   `python fpga/common/freeze.py --root PACKAGE --emission rtl/emission-profile.json --rom firmware/bootrom-128k.bin --coe firmware/bootrom.coe --firmware-contract firmware/clock-contract.json --functional-receipt evidence/affected-functional.json --mig ip/ddr4_0.xci --threads 8`
5. Run native PowerShell:
   `./fpga/common/run-local.ps1 -Manifest C:\PACKAGE\manifest.json -Vivado C:\AMD\Vivado\2025.2\bin\vivado.bat -Python C:\Python\python.exe`
   This performs simulation, fresh IP synthesis, SoC synthesis and implementation,
   with fail-closed stage receipts. No `-GenerateBit` for performance exploration.

Report requested and actual generated clocks, per-domain setup/hold WNS/TNS and
critical path start/endpoints. Distinguish post-synthesis estimates from routed
results. A single critical-path reciprocal is an estimate, not a proven Fmax;
CPU, fabric and fixed domains must each satisfy their actual constraints. Keep
failed high-target reports rather than substituting a lower-frequency run.
