# Consecutive VS trap metadata replacement

This test-only addendum runs five different VS-origin traps on one admitted
HypervisorPlatformGsim DUT, then repeats that entire sequence under three
single-clock service schedules. The tile, shared fabric, native memory, ROB
and trap handler are real hardware in the authenticated GSIM model.

No reset, image programming, page-table update or manual metadata clearing
occurs between traps. M-mode performs ordinary bootstrap only. The HS handler
only reads trap/status CSRs, writes the next SEPC and executes SRET. All tested
faulting instructions originate in VS, including ECALL.

## Sequence and architectural expectations

1. An SD to VA `0x40201000` faults during G translation of its implicit VS PTE.
   Cause 23, raw PTE GPA `0x10003008`, HTVAL `0x04000c02`, HTINST `0x3000`, GVA=1.
2. An LD to invalid VS leaf VA `0x401fc000` causes page fault 13. Raw GPA,
   HTVAL and HTINST must all become zero while GVA remains one.
3. A 32-bit instruction at `0x401ffffe` faults on the second parcel's implicit
   VS PTE. Cause 20, EPC `0x401ffffe`, STVAL `0x40200000`, GPA `0x10003000`,
   HTVAL `0x04000c00`, HTINST `0x3000`, GVA=1. This repopulates metadata with a
   different PTE byte offset after the previous clearing.
4. VS ECALL produces cause 10 and zero STVAL/raw GPA/HTVAL/HTINST. Its guest
   address, guest-page-fault and implicit-PTE flags must be false. HSTATUS.GVA
   must clear immediately after the preceding implicit guest-page fault.
5. An LD to VA `0x401fd000` reaches an invalid final G leaf. Cause 21, GPA
   `0x20003000`, HTVAL `0x08000c00`, HTINST=0 and GVA=1. This restores fresh
   guest-address provenance and fault metadata after ECALL.

HSTATUS at handler reads is `0x2000001c0`, except ECALL is `0x200000180`.
SPV/SPVP remain set at every VS-to-HS entry. Host SIE stays zero; each trap
copies it into SPIE, so SSTATUS reads `0x200000100` every time. SRET setting
SPIE between traps does not change that next-entry expectation. Guest CSR
0x100 after SRET would be VSSTATUS and is not used as a host-status substitute.

The `0x3000` HTINST value is this implementation's RV64 implicit PTE-read
contract under its read-only Svade walker. The test does not claim every H
implementation must return nonzero HTINST. Expectations use the pinned
official H/translation specifications listed in `guest-translation-contract.md`.

## Independent checks

The driver maintains independent instruction encodings, architectural PC,
registers, memory and fixed stage records. Every successful retirement is
checked for instruction, PC, destination/write enable, value and next PC.
Faulting instructions never retire; the original retirement frontier must
match EPC, and the split fault retains a separate second-parcel STVAL.

After each trap, the real handler retires seven CSR reads: SCAUSE, SEPC,
STVAL, HSTATUS, HTVAL, HTINST and SSTATUS. It then executes SRET to a distinct
safe continuation in the left code page. No metadata value is inferred from
the preceding DUT output to form the next expectation.

Each stage executes one permitted older store with a distinct value at
SPA `0x8020c008`, then confirms it through a load. Recovery loads check that
older value and untouched fault/younger-store sentinels at `0x8020c000` and
`0x8020c010`. The final physical store count must be five. Faulting and younger
stores are forbidden, and recovery skips the younger instructions. This does
not claim that the younger instructions actually issued speculatively.

Both native scalar lanes retain request/response owner queues, exact physical
beat checks and held-payload assertions. Five ordered reservation-clear
transactions are required in aggregate; every accepted clear must wait for
both older lanes to drain. No additional clear-to-trap timing relation is
claimed. Required PTE reads
must occur; inaccessible right-table and later physical instruction/data reads
must not. Fetch and data PTE work can legitimately interleave, so no artificial
global walk order is imposed.

Open, staggered and longer periodic-closure schedules are used. Every non-open
schedule first observes at least two real held request and response cycles per
lane before following its periodic mask. The per-sequence cycle guard is
finite, and the runner separately limits wall time and sampled process-tree RSS.

Three deliberate stale-expectation controls leave the DUT unchanged:

- `stale-htval`: expect the first trap's nonzero HTVAL at the second trap.
- `stale-htinst`: expect its nonzero HTINST at the second trap.
- `stale-gva`: expect GVA still set during the fourth trap, ECALL.

Each must fail at the named retired CSR comparison. They are oracle negative
controls, not source mutations. Traces retain actual stage-indexed trap, CSR
and SRET values, including any failed-control prefix.

## Reproduction

```sh
source cloud-tools-20261030-r2/env.sh
python3 recovery-1106-hypervisor-trap-sequence/canonical/simulator/gsim/platform_trap_sequence.py \
  --entry-binding-root recovery-1106-hypervisor-entry-binding \
  --bundle cloud-tools-20261030-r2 \
  --reuse-native-model recovery-1106-hypervisor-vs-boundaries \
  --output /tmp/new-trap-sequence-evidence
```

The output directory must be new. The explicit reuse option authenticates the
sealed boundary archive, prior execution receipt/source pins and exact native
object hash. That object was built under ASan/UBSan from the same fixed fresh
header/CPP pair. Changed or missing reuse inputs fail; there is no silent
fallback. Omit the reuse option to explicitly compile a new native object from
the authenticated emitted model instead.

Both modes verify the fixed portable-entry archive/receipt/source manifest,
model header/CPP/FIR, live hardware and helper sources. They invoke the strict
fixed-version and patched-GSIM bundle verifier before and after execution and
retain the ordinary compiler version check. Source/model/tool drift fails.
Receipts are never fabricated, rewritten or relaxed. No Scala elaboration,
GSIM regeneration, dependency download or alternate simulator is needed.

The runner records commands, exit codes, resource samples and all input/output
hashes. Native objects/executables may remain workspace-only; archived receipts
retain their identities. The new patch contains only this document, the native
driver and the runner, with no change to RTL or production defaults.

## Coverage gain and limits

The previous actual-core translated sequence already proved HTINST clearing
from implicit to explicit G fault. The new contribution is nonzero-to-zero
HTVAL and secondary metadata into ordinary VS faults, simultaneous clearing
on a non-address exception, and GVA 1→0→1 in one DUT without manual clearing.
Earlier reset-separated boundary tests do not provide that evidence.

This remains a finite VS-origin single-clock test. No restricted M-origin
review, independent clocks/CDC, external DDR, DMA, multihart/TLB coherence,
OS boot, complete compliance suite, full regression, synthesis, PPA or
publication is performed. Experimental H remains default-off and `misa.H`
clear. Sentinel completion and a drained data lane do not establish whole
fetch quiescence or runtime parking. No general arbitrary-fault-sequence or
fault/interrupt concurrency claim follows.
