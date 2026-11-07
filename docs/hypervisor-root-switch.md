# Actual-core two-stage root switching

`make gsim-hypervisor-root-switch-test` is a focused GSIM check of the experimental,
uncached `HypervisorMachineCore`. It uses the existing
`HypervisorTranslatedCoreGsim` wrapper and the normal pinned-toolchain setup,
Scala elaboration, GSIM generation and sanitized native compilation. It does not
load a previously compiled model or require a recovery-directory object file.

## Coverage and independent expectations

One continuous CPU execution visits five phases:

1. A: VS root A and G root A.
2. B: VS root B and G root A.
3. C: VS root B and G root B.
4. B again.
5. A again.

Each phase uses the same guest instruction and data virtual addresses. The three
contexts map those addresses to distinct physical instruction and data pages.
Both G roots map the VS page-table GPAs to the same physical page-table storage,
so changing HGATP tests final G-stage mapping independently of page-table content.
All page tables and instruction images are initialized before execution and stay
fixed. Stores affect only the explicitly allowed data destinations.

Actual retired HS CSR writes publish the selected VSATP/HGATP roots. Global
`HFENCE.VVMA x0,x0` and `HFENCE.GVMA x0,x0` make the transition sequence explicit.
VSATP uses Sv39, HGATP uses Sv39x4, and ASID/VMID are zero. HS instruction fetch is
Bare. Five ordinary VS ECALLs enter HS. Four HS SRETs advance to the next guest
phase; the fifth handler enters the monitored terminal loop. There are no
injected guest page faults or external interrupts.

The C++ driver maintains an independent architectural retirement model and
context-to-physical-address table. It does not derive expected values from the
serving memory or observed translation results. It checks instruction words,
register writes and values, next PCs, root CSR readbacks, precise ECALL metadata,
translated instruction/data traffic and isolated physical stores. Returning to B
and A must recover each context's prior data without corruption by other phases.
Open and stalled service schedules exercise the same program, with accepted
request/response accounting and all physical request fields checked while held.
The stalled schedule requires observed held offers and response service delays
on all four ports. Response-blocked cycles are reported only when actually seen.
Periodic commit-disable cycles test the admission control, but do not prove that
a ready retirement was delayed. All retirement fields are logged; register
destination/data expectations apply only when the instruction writes a register.
The terminal loop remains monitored for twelve successful loop retirements;
reported outstanding owners are observations, not a proof of general quiescence.

Two negative controls deliberately use incorrect independent expected results:
`--wrong-fetch` and `--wrong-data`. Each must exit 1 with its own final diagnostic.
The entry rejects an unrelated crash or sanitizer failure as a negative-control
success. `test_hypervisor_root_switch_entry.py` checks that entry contract with
mocked build and subprocess calls; these Python tests are not hardware evidence.

## Existing coverage and limits

`hypervisor_fence_coherence.cpp` changes leaf PTEs under one fixed root pair.
`guest_translation.cpp` checks another HGATP root at the standalone walker level.
This target adds repeated root switching through actual retired CPU instructions,
including instruction fetch and data isolation, rather than repeating either
component case.

The current core has no TLB or instruction/data cache in this integration. Root
CSR writes already drain translation owners. A pass therefore demonstrates this
implementation's root publication and uncached two-stage execution, not tagged
TLB invalidation, shootdown, cached instruction coherence, OS compatibility, or
general speculative-fault cancellation. It does not qualify independent clocks,
multicore, production timing, or complete H/AIA compliance. Experimental H remains
default-off, `misa.H` stays clear, and production profiles are unchanged.

Architectural context is documented in `docs/guest-translation-contract.md`.
The standard entry preserves strict validation of the explicitly selected
supported GSIM bundle; it does not bypass that validation or promise arbitrary
toolchain/host portability. Execution logs are written below
`build/gsim/hypervisor-root-switch/`.
