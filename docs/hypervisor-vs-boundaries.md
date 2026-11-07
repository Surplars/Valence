# VS-origin two-stage boundary and precise-trap checks

This test-only addendum exercises the existing opt-in HypervisorPlatformGsim
tile plus actual shared fabric. It does not change RTL, default profiles or
`misa.H`. The test uses one clock, hardware ROM/RAM and real native responses,
not a synthetic memory responder.

## Coverage

Five logical programs run with open gates, staggered stalls and longer periodic
closures, for 15 positive executions. In each non-open schedule, every lane
first observes at least two held request cycles and two held response cycles
before its periodic mask applies. This guarantees actual backpressure rather
than relying on a short program coinciding with a fixed closure. All faulting accesses originate in
VS. M-mode only bootstraps PMP, delegation and VS/G roots. Interrupt sources and
interrupt enables remain disabled. Each case starts from a fresh shared cold
reset and disabled-CPU image programming.

The instruction at VA `0x401ffffe` spans a 2 MiB VS page-table boundary. Its
parcels reside at noncontiguous SPAs `0x8020bffe` and `0x8020d000`. An independently
encoded ADDI produces x10=`0x357` and next PC=`0x40200002`. The physically
contiguous decoy would form a different valid instruction.

1. Both parcels translate and the complete instruction retires exactly once.
2. The second parcel encounters an invalid VS leaf: cause 12, EPC `0x401ffffe`,
   STVAL `0x40200000`, no guest-page-fault GPA and zero HTVAL/HTINST.
3. Its final G leaf is invalid: cause 20, the same EPC/STVAL, raw GPA
   `0x20001000`, HTVAL `0x08000400`, implicit=false and HTINST=0.
4. G translation of its VS PTE fails: cause 20, the same EPC/STVAL, raw GPA
   `0x10003000`, HTVAL `0x04000c00`, implicit=true and HTINST=`0x3000`.
5. A VS SD targets VA `0x40201000`; its implicit VS PTE mapping fails: cause 23,
   EPC at the SD, STVAL equal to that target, raw PTE GPA `0x10003008`, HTVAL
   `0x04000c02`, implicit=true and HTINST=`0x3000`. This distinguishes the PTE's
   byte offset from its page base and preserves the original store cause.

`0x3000` is the implemented RV64 implicit-read trap-information contract for the
read-only Svade walker. The test does not claim every conforming H implementation
must supply nonzero HTINST. Architectural references are the pinned official H
and translation specifications listed in `docs/guest-translation-contract.md`.

## Independent observable checks

The driver has its own instruction encodings, architectural register/memory
state and per-case fault records. It compares every successful retirement's PC,
instruction, destination, value, write enable and next PC. Faulting instructions
cannot retire, and incomplete split instructions cannot change x10.

The actual HS handler retires reads of SCAUSE, SEPC, STVAL, HSTATUS, HTVAL,
HTINST and SSTATUS. All VS-origin faults, including cause 12, retain
GVA/SPV/SPVP. SSTATUS.SPP is supervisor. A real SRET returns to the safe left
page; subsequent VS loads verify older-store visibility and unchanged fault
and younger-store destinations. There is no unobserved post-SRET HSTATUS claim.

The older valid store targets SPA `0x8020c008` and writes `0x55`. The forbidden
fault target at `0x8020c000` remains `0x1234`; the younger-store destination at
`0x8020c010` remains `0x9abc`. The accepted physical write count must be exactly
one. The store-fault program skips the younger store on recovery. This proves
precise external effects, not that a younger operation actually issued.

Both scalar lanes have independent accepted-owner queues, request/response
stability checks, sequential owner validation and actual full 64-bit physical
response-beat comparisons. Two-byte fetch requests retain their address and
byte mask; the driver does not replace native beats with fabricated parcels.
Exactly one ordered reservation-clear transaction occurs for each fault, after
both older scalar lanes drain. Critical fault-path PTE reads must occur;
inaccessible right-table and later target reads must not. No artificial total
PTE order is imposed across concurrent fetch/data work.

Four deliberate wrong expectations independently alter EPC, STVAL, raw GPA and
HTVAL. Each must exit 1 at its named comparison. They are oracle negative
controls, not separately compiled RTL mutants.

## Reproduction and provenance

From the restored workspace:

```sh
source cloud-tools-20261030-r2/env.sh
python3 recovery-1106-hypervisor-vs-boundaries/canonical/simulator/gsim/platform_vs_boundaries.py \
  --entry-binding-root recovery-1106-hypervisor-entry-binding \
  --bundle cloud-tools-20261030-r2 \
  --output /tmp/new-vs-boundary-evidence
```

The output directory must not already exist. Preserve failed output directories
rather than overwriting them. The runner authenticates the fixed entry-binding
archive, receipt, source record and emitted header/CPP/FIR; checks live hardware,
fixtures and helpers against the executed source record; and invokes the strict
fixed-version/patched-GSIM bundle verifier before and after execution. Missing,
changed or conflicting identities fail closed. The ordinary compiler version
contract remains enabled. No receipt is fabricated or rewritten.

The matching fresh generated header/CPP pair is compiled once with ASan/UBSan
into a new native object and linked to the new driver. No old model object or
different generated header is substituted. Scala/Mill elaboration and GSIM
generation are not repeated because RTL is unchanged and the emitted model is
authenticated. No dependency download is needed. This is a bounded reused-model
addendum, not a new universal toolchain compatibility claim.

The runner records commands, sampled process-tree RSS, per-command time,
source/model hashes, traces and tool bindings. A 3.5 GiB RSS and per-command
wall-time guard are active. Per-case `.trace` files contain prefixed records
with JSON payloads; they are not advertised as strict JSONL.

## Qualification limits

Existing component tests already cover the corresponding walker/assembler
behaviors. The new evidence advances selected cases through actual shared
fabric, ROB ownership, trap entry, retired CSR reads and safe guest recovery;
it does not replace or rebrand component results.

Completion uses an architectural sentinel with the data lane drained. An
instruction-fetch owner can remain live, so this is not whole-platform
quiescence or runtime park/resume evidence. Fresh-reset cases do not prove
stale HTVAL/HTINST clearing across successive different fault types.

No M-origin guest-fault review, independent-clock/CDC, external DDR, DMA,
multihart/TLB coherence, OS boot, architectural compliance suite, full GSIM
regression, synthesis or PPA claim follows. The H path remains uncached and
experimental, default-off, with `misa.H` clear. No code is published by this
addendum. Execution results and immutable input/output hashes are reported in
the sibling evidence receipt and package RESULT.json.
