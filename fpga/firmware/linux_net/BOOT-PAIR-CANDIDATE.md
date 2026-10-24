# I1 boot-only CPU125 / fabric125 candidate

This follow-on source candidate does not replace the delivered CPU125/fabric50
Debian image or any older r2 artifact. Linux workload/IRQ/DMA board testing is
still pending. No new A1 or arbitrary-frequency qualification is implied.

## Exact scope

An explicitly selected, closed I1 image starts at CPU50/fabric50. After all
fallible clock-provider/sysfs registrations, the sole clockmon MMIO owner makes
one CPU125 transaction, then only after its verified success makes one fabric125
transaction. Both use D10/M40/O8 (`0x08280a`); boot50 is D10/M40/O20 (`0x14280a`).
Supported stable pairs are 50/50, 125/50 and 125/125. CPU50/fabric125 is prohibited:
every manual CPU request first checks the fabric actual rate, errors, state,
completion nonce and this owner's retained tuple. CPU50 is rejected while fabric
is125. There is no implicit fabric-down transaction.

Additional DT properties are `openion,fabric-boot-hz = <125000000>` and
`openion,i1-boot-pair-125`. These require the existing I1 CPU-control opt-in,
CPU boot125, fixed250MHz TIME, the closed configuration/consumer checks, and the
real UART DT node disabled (the matched image uses SBI console). Absent properties
retain CPU-only/default-read-only policy. A1 remains rejected before extension
MMIO mapping. The builder must bind this DT to the exact reviewed I1 hardware;
this property is not a generic assertion that arbitrary hardware is safe.

No CMUv1 clock index is changed: index2 is TIME250, not fabric. Fabric has its
own read-only clockmon provider index1. No fabric CCF consumers are admitted by
this closed-image control contract. Future consumers/notifiers, overlays,
module unload, cpufreq, SMP and raw devmem are outside the contract.

## Actual hardware admission relied upon

Rate register0x40 value0x30 proves only software-parameter diagnostic admission;
it does not encode externalIrqsAbsent or authenticate the FPGA bitstream.
The DT pair marker is an explicit deployment contract, not a hardware proof.
This candidate is restricted to the previously reviewed R39 bit:
SHA256 `6ef3931799c7a746dd14e71162456d9759a264f548e7a13fb209b85db83ecf73`,
28,700,884 bytes, source84a498a, RX450 and TX_LOCAL_PAD_RESET_RELEASE=1,
cold50/50. Supporting evidence is retained with the private engineering
delivery; this public repository does not contain those attachments. The
bindings are the bit package ZIP SHA256
`7ebfdff757a622a5ec393f1a64949f9dd48fe000f84190b652176a5d947e3797`,
the 125/50+125/125 STA/native report SHA256
`c5f12bbf503e805e22bb21b1f4cd6115689f8838cfd4c8b69bb8977685ed14c3`,
and the prior bare-metal roundtrip log.
Those prior hardware/bare-metal results do not prove this Linux startup pair.
The driver cannot read back or authenticate a bitstream SHA; deployment must
verify the receipt externally and must not attach this opt-in to another image.

The frozen dynamic I1 emitter sets `externalIrqsAbsent=true`, and the common
board shell ties the external31-source vector to zero. This does NOT mean all
interrupts are absent. Internal GMAC pending events, UART pending/FIFO state,
CMU pending/faults and timer comparison are retained level sources in fixed
clock domains. Fixed TIME continues at250MHz; UART reference and MAC clocks are
not changed. The CPU is parked during the shared epoch, preventing software
from clearing retained sources while fabric is stopped.

A rate request still traverses the real network producer-stop/drain sequencer,
fixed-MAC command/receipt/park proof, CPU/private drain, fabric transport and
Home ownership, DDR and fixed-timebase idle qualifiers, UART/CMU/rate-register
owner idle checks and final CPU/fabric close proofs. Gate acknowledgement waits
for the fixed-domain safety arm receipt. BootROM's successful network quiet path
already drains descriptor/frame/TX/RX owners, but module absence or BootROM
history is NOT substituted for this hardware admission. Failed drain cancels;
the driver does not manufacture acknowledgements or bypass admission.

The matched Dinit image explicitly blacklists all six platform modules from
alias autoload and loads clockmon before CMU/AIA/DMA/GMAC. Its actual service set
has no udev daemon. This boot-stage policy does not accelerate netboot or kernel
decompression. SBI/TIME and independent serial recovery remain available unless
a hardware failure stops CPU progress or makes MMIO nonresponsive; a software
100ms timeout cannot rescue a stalled bus or permanently stopped CPU.

## Ownership, results and failures

CPU and fabric use one mutex and the same bounded transaction implementation,
with separate state and exact maximum-rate contracts (CPU300M/fabric250M). The
fabric adapter permits only target/page0x80 and parameters/page0xb0 writes, only
while probe startup is active and its irrevocable once flag is set. No fabric
writable sysfs attribute exists. Runtime CPU writes remain separately root-only
and armed, and may not enter the unqualified50/125 pair.

`fabric_boot_control` is read-only: enabled, attempted, poisoned, last_result,
last_confirmed_hz, boot_target_hz, shared_fault and qualification. Existing
`cpu_control` gains shared_fault. A failed CPU request leaves fabric unattempted;
its current50 result is read and checked rather than inferred. Fabric errors,
including confirmed fallback50, permanently latch the shared write-owner fault.
An unknown outcome reports0 and blocks all further CPU/fabric writes. There is
no error clearing, retry or software rollback. Read-only monitoring remains.

Dinit must check BOTH results, not modprobe exit status or CPU success alone.
Each successful result must match its requested target. A failed request may
continue only with a separately confirmed actual50 result and an explicit
fallback message. Any unknown/missing/mismatched domain blocks dependent device
startup while preserving the independent SBI rescue service. Never claim that
CPU125/fabric50 fallback achieved the requested pair.

## Validation boundary

`test_clockmon_boot_pair.py` compiles the actual production config, probe,
CPU/fabric transaction and sysfs store bodies with kernel/DT/MMIO mocks. It checks
CPU-before-fabric order, one-shot behavior, zero writes on registration/config
failure, independent caps/completion validation, CPU failure with no fabric
write, confirmed fallback, timeout, global poison, and rejected CPU50/fabric125.
The existing transaction/probe/ABI suites remain separate regression checks.
Host tests and a real kernel W=1 build are not Linux-load or physical signoff.
