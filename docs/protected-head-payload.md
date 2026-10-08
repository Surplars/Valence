# Protected system/FP head payload sharing

This default-off follow-on to the qualified banked issue payload removes the
separate system completion read of PC, raw instruction and expanded instruction.
The existing head read already carries those fields throughout protected system
execution. System/FP operations start only at the ROB head. The protected full
token remains there until accepted exceptional completion or actual retirement,
including multicycle numeric execution and held commit. The new flag is
`shareProtectedHeadPayload`; it requires banked storage, system mode and compressed
FP plus `fastHeadSystemRecovery` for the full head-token observation, so it cannot
silently describe an absent context consumer or optional observation port.

The candidate asserts the full-token head/queue/system relationship on every
protected cycle and the completion token on every valid presentation, including
held and exceptional results. No owner tags, validity, cancellation, precise
exception metadata, queue depth, pipeline stage, completion priority or opcode
selection changes. The read is shared directly; no late consumer-address mux is
added.

Expected memory port change per parity bank: PC64 at depth8 goes from8 reads to7,
raw instruction32 from4 to3, expanded32 from2 to1. Each remains one synchronous
writer with asynchronous reads. Logical stored bits stay fixed. A naive one-RAM
copy per asynchronous read model would save2048 replicated bits; FPGA packing,
minimum primitive depth and mapping must still be measured. This is not a LUT,
FF, BRAM or timing result.

The focused A/B wrapper uses the integrated631fd68 candidate CPU parameters,
including the FPGA floating point resources, ROB16/PRF48 and both storage flags.
Only the external fixture RAM aperture is adapted to the preserved FP oracle.
It runs independent pinned SoftFloat integer/FPR/flags checks, long divide/sqrt,
four compressed memory transfers, commit holds, plus a separate precise-memory
fixture with wrong-path flush, delayed responses, request holds and seven fault
classes. A passive full-token host check independently observes head ownership;
a corruption must fail. Existing architectural negatives remain in force.

Qualification passed in `build/gsim/fpga-next-protected-head-r5/receipt.json`.
Both variants match exactly:1,212 SoftFloat vectors,61,865 numeric commits and
84,516 cycles, including four compressed FP memory operations; the two precise
memory seeds each retire3,085 instructions with57 traps and take13,323/15,076
cycles respectively. Each seed includes75 FP loads,104 stores,664 held-completion
cycles and21 wrong-path admissions. Full-token corruption and existing
architectural-result corruptions are rejected independently for both variants.
The lowered RAM census confirms all three expected read-port reductions.

The original external-instruction harness assumed direct admission PC. Its copied
version now uses the selected split-cursor next-state address only to supply the
instruction device; every next-cycle cursor and independently expected retired
PC/raw instruction/value remains checked. Wrong-path admission uses real renamed
packet PCs. The precise-memory oracle explicitly expects RV64IMAFDC/S/U MISA.
No test probe or oracle signal enters production interfaces.

The final replay reused both source-matching generated model objects after
verifying every Scala input and retained artifact hash, then relinked/reran both
harnesses with an added total-cycle counter. Earlier fixture setup failures remain
preserved; no failed simulation is promoted. Integration into the latest combined
board and physical FPGA mapping/timing remain separate gates.

The census belongs to an observed CPU wrapper. Its architectural FPR inspection
and other test taps retain extra read paths and zeroed register declarations that
production native lowering can remove. Only the differential issue payload
PC/raw/expanded read-port reductions are established here. Do not transfer the
wrapper's total FPR port count or total queue register declarations to the native
board. The final production export must confirm the three reductions separately.

The added parameter requirement and negative configuration case passed in
`build/gsim/fpga-next-protected-head-contract-r1/receipt.json`. Fresh elaboration
of both variants is byte-for-byte identical to the qualified R5 FIR. That receipt
also binds `build.mill`, `.mill-version` and all18 HardFloat sources against the
qualified FPU dependency receipt; the older behavioral runner inventory did not
include those dependency files. Behavioral/cycle evidence is inherited only
through this exact model identity, not from an assumed configuration equivalence.
