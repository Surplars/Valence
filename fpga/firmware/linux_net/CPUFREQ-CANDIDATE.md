# CPU-only Linux control candidate (not cpufreq)

This follow-on source is separate from immutable Linux r2. It implements a
restricted manual/boot CPU control path in the existing clockmon resource owner;
it does not register cpufreq, a governor, fast_switch, a fabric controller or a
raw MDO/DRP interface. It is an engineering candidate, not Linux-load-qualified.

## Explicit configuration and startup

Without `openion,cpu-rate-control`, the driver remains read-only and performs no
clock writes. I1 candidate DT may opt in using these clockmon properties:

    openion,cpu-rate-control;
    openion,cpu-clock-observer-only;
    openion,cpu-boot-hz = <125000000>;

Only50MHz and125MHz are accepted. Omit cpu-boot-hz or set50000000 for no automatic
change. Keep a separate rescue50 DT with control entirely absent. Old A1 static
DT must keep the whole monitor node disabled: it has no ABI2/perf hardware.
New A1 hardware/telemetry support is separate work, not assumed by this driver.

For the initial Debian candidate, load clockmon first in the early Dinit
platform service, then CMU/AIA/DMA/GMAC. This makes the optional single125
request before DMA/GMAC activation. It does not accelerate netboot, kernel
transfer, decompression or earlier kernel initialization. Real built-in driver
integration is not supplied by an out-of-tree obj-y toggle.

Every fallible allocation/provider/sysfs registration finishes before the boot
request. A starting gate rejects competing manual writes. Explicit boot125
arms internally for exactly one transaction and disarms afterwards; subsequent
manual changes require a separate root arm. A failed boot request never causes
software retries or blind fallback writes. Hardware owns autonomous fallback.
Confirmed50 can be reported as50; unknown remains unknown/poisoned, not “safe50”.

## Root-only manual interface

The existing rate_status/snapshot remain read-only. Added attributes on the
same platform device:

- `cpu_control` (read-only): enabled, armed, poisoned, last_result,
  disabled_reason, requested_hz, last_confirmed_hz, status, errors, boot_target_hz, explicit
  fabric_control=disabled and Linux-load-unverified qualification.
- `cpu_arm` (root-write-only plus CAP_SYS_ADMIN): write1 to arm. This never
  submits a request; disabled configuration or poison rejects it.
- `cpu_target_hz` (root-write-only plus CAP_SYS_ADMIN): write50000000 or125000000.
  Unarmed, disabled, starting, malformed or unsupported targets are rejected.

There is no clear-poison, reset, raw write, arbitrary-frequency or error-W1C
endpoint. Reboot with rescue50 is the recovery route. The mutex covers staging,
request and completion, as well as existing rate/snapshot reads. Live CCF reads
are bounded and return0 for busy/invalid or a poisoned unknown outcome;0 means
unknown, not a zero-Hz clock measurement. Stable configured Hz and independent
meter Hz remain distinct.

## Exact transaction and tuple provenance

Only D10/M40/O20 (50MHz,0x14280a) and D10/M40/O8 (125MHz,0x08280a) are allowed.
Same Hz with old canonical M50/O10 is NOT reused. Initialization requires a
cold idle valid50 controller, completion0, reset requested/target50 and staged
boot tuple, exact diagnostic ABI2/capability/admission0x30 and clock limits.
Prior pre-Linux transactions disable write admission, even if they finish at50.
A failed control contract leaves the read-only monitor/CCF provider registered
with enabled0, disabled_reason and poison, so CMU does not defer forever. It
does not invent a qualified tuple or boot50. Unsupported/missing hardware ABI
still rejects the full driver; legacy A1 is rejected before extension MMIO.

The portable core retains the last verified completion and known active tuple.
Each subsequent call checks this chain before accepting a same-rate no-op.
Parameters and target are written once, in order, with staging readback. Success
requires exactly completion+1 modulo32, idle, success flag, actual/requested/
target match and no errors. No fabric offsets are touched.

Poison latches before the first write. Failed staging, wrong completion,
autonomous fallback, malformed result or timeout leaves writes permanently
blocked. Errors while hardware is recovering do not falsely finish recovery.
A 100ms deadline uses kernel monotonic time, which derives from fixed CSR_TIME,
in addition to bounded polls. Scheduling delays may delay observation; the
software cannot rescue a permanently stalled MMIO access or stopped CPU.

## Closed Linux clock-consumer contract

Opt-in rejects CONFIG_CPU_FREQ, SMP, CPU_IDLE, SUSPEND, HIBERNATION, OF_OVERLAY,
MODULE_UNLOAD or DEVMEM. It requires I1 identity and DT timebase250MHz. Runtime
DT scanning rejects CPU-clock consumers beyond the existing CMU read-only
alias, including any consumer of CMU index1. Fixed UART/TIME/GMAC clocks stay
unchanged; only GMAC CMU5/6 are used in the current DT.

Actual RISC-V __delay/udelay/ndelay use CSR_TIME; time_init derives lpj_fine from
riscv_timebase. Thus CPU frequency is not the timer/delay calibration basis.
The supplied CPU CCF provider is a read-only NOCACHE observer in this closed
image, not an active rate-control/notification consumer. None of the six
project drivers registers a CPU rate notifier. This is not a generic license
to bypass CCF: adding CPU clock consumers or rate notifiers requires a new
integration review. Arbitrary future modules are not part of the contract.

## Why this is not a partial cpufreq driver

The real kernel target_index failure path sends a synthetic rollback to old
frequency. Hardware could instead have fallen back50. Driver-owned ASYNC
notifications can report a proven actual fallback correctly, but no valid
END-unknown API exists. Passing0 risks invalid frequency scaling; inventing old
is false. A pending read-only recovery worker would need policy/lifecycle proof.
Also, pending get() must not trigger core out_of_sync→a second BEGIN deadlock,
and driver suspend errors alone do not veto system suspend. This candidate
avoids registering that framework rather than pretending these issues solved.

## Validation and remaining work

Host tests execute the same transaction header and compile the production
probe/owner/arm/target function bodies directly against Linux/DT/MMIO mocks.
They cover root/arm/starting gates, read-only downgrade, registration failure
zero-write behavior and optional one-shot boot. Transaction checks include exact tuples, zero-write
preflight failures, cold-boot provenance, unknown/reserved bits, completion
wrap, fallback, deadline, late completion remaining poisoned, wrong same-Hz
tuple and pthread single-owner sequencing. ASan/UBSan can run with leak checking
disabled in this ptrace environment; that is not a LeakSanitizer pass.

Actual kernel W=1 compilation, final source/receipt binding and independent
integration review are separate acceptance steps. Linux IRQ, scheduler,
console and concurrent DMA load on real hardware remain unverified. No board
operation is performed by these cloud checks. Fabric runtime/automatic DVFS
remains unimplemented pending GMAC/DMA drain and IRQ-preservation proof.
