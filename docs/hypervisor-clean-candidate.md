# Clean H/AIA candidate: apply and reproduce

## Choose one application route

The complete candidate targets commit
`a6448d9165f9c3c95456fab5895dd66d818c66aa`. Preserve existing work and use a clean
checkout at that commit, then apply `HYPERVISOR_AIA_INTEGRATED_PATCH.diff` once.
It includes the H/AIA implementation and the later same-DUT AIA/G-stage tests.
Do not also apply the older component or dirty-baseline patches.

If the previously sealed 72-file clean candidate is already applied exactly,
use only `AIA_GSTAGE_CHAIN_PATCH.diff` instead. This addendum changes tests and
documentation, not production RTL. Do not apply both the full patch and the
addendum to the same checkout.

`SOURCE_MANIFEST.json` gives original clean-commit and final hashes.
`PATCH_ROUNDTRIPS.json` records independent reconstruction, `git apply --check`,
actual application and final hash equality for both routes. The earlier clean
archive is preserved byte-for-byte under `prior-clean-evidence/`; it contains
its original source/dependency manifests and qualification receipts.

## Maintained integration

The opt-in top `soc.core.ooo.HypervisorMachineCore` contains actual OoO
retirement, H/VS state, AIA controls, guest IMSIC files, nested translation and
C/32-bit instruction assembly. The joint fixture additionally instantiates
CommonInterruptFabric and drives actual source pins. Default production
constructors and W16 are not switched to this configuration, and misa.H stays
clear.

The clean port retains the baseline issue-payload API rather than importing
unrelated dirty compact-immediate-storage changes. Its production sources remain
unchanged by the follow-on joint tests.

## Focused runners and executed evidence

The base candidate provides `simulator/gsim/hypervisor_core.py` for actual MSU,
Bare OoO, nested OoO and HFENCE scenarios. `guest_translation.py` covers the
walker, data/fetch adapters and assembler, and the AIA component runners retain
their independent focused checks. Those standard Mill entry points were syntax
checked; cloud execution used the pinned direct Scala/Chisel/GSIM/Clang commands
recorded in the original receipts. No Verilator/ChiselSim fallback was used.

`aia_retiring_core_acceptance.py` reproduces the earlier Bare APLIC-to-retirement
chain. `aia_translated_core_acceptance.py` reproduces the subsequent same-DUT
AIA-plus-two-stage chain. Both take explicit `--core-root`, `--output`, `--gsim`
and `--cxx` arguments. They validate and freeze a completed `system-build`
compilation and its sources/dependencies before compiling only the new fixture.
This is documented class reuse, not a second claimed full-core compilation.
The translated runner's final default markers match its supplied harness.

`final-build/receipt.json`, `run.log` and `negative.log` identify the latest
executed chain. `RESULT.json` records the finite outcomes and limits.
`EVIDENCE_MANIFEST.json` pins the bundled evidence, and `final-review.md` records
the read-only review. Earlier source snapshots and receipts are kept separately;
new documentation does not rewrite old qualification history.

Read `aia-translated-core-chain.md`, `hypervisor-qualification-boundaries.md`,
`guest-translation-contract.md` and `aia-conformance-scope.md` before promotion.
No guest OS boot, complete architectural compliance, FP/atomic guest profile,
CPU APLIC-MMIO routing, production W16 integration or PPA qualification is
claimed. The blocked independent M-origin explicit/implicit guest-fault review
remains unperformed and was not retried. Positive MPRV and static-fault tests
must not be relabeled as that missing review.


## Actual shared-platform extension

The next additive candidate connects an explicit `CommonHypervisorCpuTile` to
`CommonMachineFabric`, including actual ROM/RAM, Home, CPU-configured APLIC MMIO,
real MSI request/reply traffic and epoch-matched FENCE.I completion.
`CommonMachinePlatform(experimentalHypervisor = true)` selects it; the default
remains false and the original A1/I1 implementations remain unchanged.
See [hypervisor-platform-integration.md](hypervisor-platform-integration.md) for
the four finite IRQ/cold-reset cases, three VS-origin PMA exception cases, complete
selector elaborations, source identities and hard remaining qualification gates.
No dynamic H-enabled CDC/DDR/DMA, runtime parking, board or OS qualification is
claimed, and the restricted independent M-origin fault review remains unverified.
