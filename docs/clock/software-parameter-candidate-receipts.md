# Software-parameter diagnostic candidate receipts

This is a new functional profile, not a modification of the legacy empty-rate-table proof.
The physical profile remains `boot50-dynamic`; boot CPU/fabric are both 50 MHz.
The functional profile is `boot50-dynamic-software-parameter-diagnostic`.
Use the emitter option `--diagnostic-rates=software-parameters` together with
`--clock-profile=boot50-dynamic --vivado-memories`.
CMU ABI is 2, telemetry ABI is 1, and admission flags are 0x30 (diagnostic,
not physical/component/SoC timing qualification). The hardware has no software
frequency whitelist. Its characterized envelope is D10, M32..62, O3..128;
exact requestedHz*O = 25,000,000*M, CPU 10..300 MHz, fabric 10..250 MHz.
Firmware initially offers 21 profiles, 50..150 MHz in 5 MHz steps.

## Publisher inputs

The legacy diagnostic.py freeze command explicitly rejects this new functional profile.
Do not use it to manufacture a new review. The publisher supplies independently
reviewed manifests and then invokes normal check/stage guards.

After independent source review and a committed source freeze, add these explicit
manifest fields. Never edit the old r25 source inventory or MAC review receipt.

- configuration.functional_profile: the new functional profile above.
- configuration.performance_telemetry: true.
- source_commit and production_source_baseline: the actual new reviewed commit.
- roles.source_inventory: delivery/software-parameters/source-inputs.json.
- roles.software_parameter_review: a new reviewed feature receipt, included by
  digest in inputs, separate from fpga/common/dynamic/mac_diagnostic_review.json.

The source inventory schema is common-software-parameter-source-inventory-v1.
It includes source_commit, status REVIEWED_STRUCTURAL_ONLY,
physical_qualified false, board_qualified false, and files_sha256. Its closure is
all supplied files under manifest.ROOTS, all board_inputs.PUBLIC_INPUTS and
BOARD_RTL, and all supplied fpga/firmware files. Each entry must match the frozen
manifest and actual bytes. This branch permits no old-baseline overlay bypass.

The feature receipt schema is common-software-parameter-feature-review-v1.
It has the same commit/status/qualification fields, features exactly equal to
the dictionary checked by board_inputs.software_parameter_review,
sources_sha256 covering the complete emitter Scala closure plus required board,
backend, firmware-control and telemetry-constraint sources, artifacts_sha256
covering every emitted artifact, firmware_sha256 binding the manifest ROM binary,
ROM COE, firmware contract and referenced build contract, and instances with complete emitted parent-instance
SHA256 values. Required instances are gmac and crossing in ManagedPeripheralBank,
and peripherals and monitor in CommonMachinePlatform. The build contract must explicitly enable the menu and clock console, CMU ABI2,
monitor ABI1, the initial21 software profiles, and no automatic clock change.
Configuration and emitted functional-profile selectors must agree both ways.
Existing fixed-MAC clock,
reset and pad control equality checks still run. Missing modules, parameter ports,
feature flags, firmware or inventory entries fail closed.

The gate does not manufacture a review or claim that a self-authored receipt is
independent approval. The publisher freezes it only after reviewer approval.
Structural admission does not establish primitive legality, routed timing,
recovery/hold closure, board operation or qualified operating frequencies.

## Bounded evidence

Keep software-parameter normal-MMIO/CDC tests, actual native backend primitive
checks, edge/event-meter RTL checks, representative full-I1 normal-MMIO/DDR guest,
firmware build/host tests, and routed timing as separate receipt scopes. A
behavioral MMCM model pass cannot substitute for vendor primitive or board proof.
Configured Hz and measured edge-window frequency are distinct values.
