# Fetch parcel permissions and precise faults

This unconditional fix checks the actual two-byte instruction parcels and
preserves the faulting parcel address separately from the instruction-start PC.
With only an executable NA4 word allowed, C.NOP at its last halfword is accepted;
a 32-bit instruction crossing into a denied parcel faults at the second parcel.

Independent real-frontend tests pass on aligned and nonaligned captured paths.
Width-one/two parcel tests pass 174,512/349,024 checks, including 6,000 randomized
PMP tables per model. ASan/UBSan, native lowering and independent negative
controls pass. Source hashes and bounded coverage are in
[the public receipt](fetch-fault-precision.json).

Two short guests also pass through retirement, public trap outputs and an
architectural CSR mailbox on the separately qualified combined ON CPU model.
The compressed instruction retires once before the following denied parcel;
the crossing 32-bit instruction never retires and records its own PC plus the
second parcel's mtval. This is not a PMP-only whole-CPU qualification.

Reusable component emitters are `ooo.FetchFaultPrecisionGsimMain OUTPUT
[--unaligned]` and `ooo.FetchParcelPmpGsimMain OUTPUT WIDTH` (WIDTH 1 and 2), with
the matching hosts in `simulator/gsim/harness`. Use the pinned GSIM toolchain,
ASan/UBSan, `PACKET_WIDTH` for parcel hosts, and the hosts' `--inject-tval` or
`--inject-parcel` negative controls. Existing build instructions remain in the
GSIM README.

The short-CPU sources are in `simulator/gsim/fetch_fault_precision_cpu`. Assemble
`guest.S` twice with `SHORT_INSTRUCTION=1` and `0`, using `guest.ld` and
RV64IMAC/Zicsr/Zifencei without relaxation. Generate `pmp_trap_symbols.h` from
each ELF's `target_pc` and `finished_ecall` symbols as uint64_t constants
`PMP_TARGET_PC` and `PMP_FINISHED_ECALL`; require both ELFs' symbol addresses to
match. Link `host.cpp` with the completed combined BoardSocGsim object files and
the unchanged `board_boot.cpp` host closure, then run `HOST IMAGE short|word`.
The environment-specific object-binding runner and raw evidence are retained
separately.

The small FetchFeedbackTimingSpec change repairs an existing preset expectation
that omitted two already-enabled fields. Its pure constructor test passed on
both original and final combined parameter signatures. It changes no hardware.
