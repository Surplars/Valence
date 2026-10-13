# Retirement-only intent qualification

`retirementIntent` defaults to false. The supported tested entry is the original default52 option vector in `fpga/next/timing-batch-owner-row-profile.json`, with only `--retirement-intent` appended. `FpgaNextConfig`, `BoardSocConfig` and the dedicated GSIM entry forward the field to the actual backend. The Python board exporter and generic `board_final.py` CLI do not yet expose this switch. Existing board manifests are unchanged.

The candidate carries a raw completion offer into retirement qualification before execution cancellation. A separate control-flow classifier uses the same held producer before cancellation. Lane0 arbitration and deq.ready remain exact; earlier branch or fault offers still suppress a later duplicate token. The ROB retains full-token live/done/duplicate/fault checks and the final recovery-cycle veto. Actual completion acceptance, PRF writes/wakes, exceptions, redirects, LSU actions and deallocation continue to use the original accepted completion path. No queue, token truncation or register was added for this intent.

Construction requires the registered-execution topology, parallel payloads/recovery admission, registered retirement, separate branch fault qualification, two lanes and 64-bit tags. This structural guard does not dynamically qualify every constructible parameter set.

## Reproduce the short configuration checks

From the repository root, run `mill -i -j 1 IonSoC.test.testOnly ooo.RetirementIntentBoardConfigSpec`. The five checks cover ordinary defaults, the sole-flag product difference, production constructor forwarding and ordered-option validation. They passed on the exact published-source candidate.

For a fresh GSIM FIR emission, load `native_options` from the unchanged owner-row manifest and invoke `mill -i -j 1 IonSoC.test.runMain ooo.RetirementIntentFullCpuMain <new-output-directory> <all-52-options-in-order> --retirement-intent`. The entry compares the complete default52 product with the preserved cf8 snapshot, projecting only the named false `retirementIntent` additions, and audits the actual constructed backend. Core/profile field counts are 161/74; actual raw-offer and ledger-intent widths are two bits each. Head-drain state is absent in this profile.

## Measured scope

The cf8-based integration used one fresh 36-unit ON model and the strictly revalidated original default52 model. Sv39 took 191618 cycles and Bare 194153, both delta zero. All original 105 functional fields, all result sections, accepted-cycle duty, full stdout, full supply trace and full AXI trace matched. Terminal byte comparison is literal; CRLF and invalid-UTF8 counterexamples reject misleading decoded-text equality. Original read/memory/trap negative controls rejected their injected errors.

A host-only NEMU link reused the same 36 objects. Hot1847 and compressed958 matched the original complete results/stdout; PC/GPR/memory controls rejected their injected errors. No DUT regeneration, reference rebuild or state resynchronization occurred.

An earlier separate e1-based backend/ROB paired gate and native audit qualified the unchanged retirement logic, including full-tag and duplicate cases; those records retain their original source identity. That native audit found zero added register bits and bounded expression/cone equivalence, not whole-design formal equivalence. The cf8 integration's executable evidence is the exact default52 plus retirement flag profile above. Future-home, LRU and head-drain combinations remain dynamically untested here. This work makes no synthesis, routed timing, Fmax, Linux, board or general parameter-matrix claim.

Source hashes and compact result receipt identities are in `retirement-intent-source-hashes.json`. Large raw traces, compiled models and tool inventories remain in the separate evidence/recovery artifacts.

The final compatibility bridge also runs the existing head-drain configuration and classification checks: all11 combined Scala checks and four Python CLI checks pass. Old160-field snapshots are compared after removing only the explicitly false retirementIntent field. The legacy paired entry emits successfully with all160 original parameter values equal. Its full FIR matches after validating and substituting two module-local direct aliases and the two exact assertion diagnostic line changes; assertion conditions remain unchanged. A fresh retirement-ON whole-CPU emission is raw-byte-identical to the executed model, with identical actual metadata. These are source/IR compatibility checks, with no new model compilation or CPU runtime.
