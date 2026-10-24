> Follow-on source notice: immutable r2 remains read-only. This current source
> adds explicit I1 CPU-only control/boot opt-in, documented in
> [CPUFREQ-CANDIDATE.md](CPUFREQ-CANDIDATE.md). Without that opt-in, the original
> read-only behavior below remains. This is not cpufreq or fabric DVFS.

# Linux CMU rate / telemetry driver

`valence_clockmon.ko` provides actual read-only support for CMU rate ABI2 and
telemetry ABI1. It does not provide cpufreq, devfreq, runtime rate writes or a
governor. Loading it never changes clocks, clears error bits, enables IRQs,
touches DRP, gates a domain, or programs DMA. `dvfs_policy` explicitly reports
runtime switching disabled. Boot remains the firmware/hardware decision; this
driver neither assumes current50 nor silently switches to125.

The kernel/rootfs can be shared, but the current Common I1 dynamic composition
has ABI2/monitor and the Common A1 static composition does not. A1 must omit
or disable this node and must not reference it from CMU clocks. A DT must
describe this node only when the actual hardware contains the extension. Reading an absent, nonresponding MMIO device is not
made safe by checking its ID after the access.

## DT / build integration contract

One node, compatible `openion,valence-clock-monitor-v1`, with two resources:

    reg = <0 0x10080800 0 0x100>, <0 0x10080900 0 0x200>;
    reg-names = "rate", "perf";
    #clock-cells = <1>;

The existing CMUv1 node retains address10080000 and its compatible, but its
reservation must end at10080800 (size800), not overlap this extension. Existing
leaf gate control remains in valence_cmu. Do not register two overlapping
providers or label its cached nominal rate as an independently measured rate.
On I1, label the node `clockmon0` and set the CMUv1 node's `clocks =
<&clockmon0 0>` and `clock-names = "cpu-rate"`. Provider indices are CPU0 and
fabric1. CMU index1 aliases the CPU clock_hw directly; it does not add a child
whose recalc receives a cached parent rate. CLK_GET_RATE_NOCACHE reads stable
applied configured Hz each time; busy/fatal/invalid/unstable returns unknown0,
never a nominal fallback. This is not measured Hz and has no set_rate operation.
A1 omits this optional dependency and keeps its static CMUv1 rate. Load
clockmon before CMU; clockmon has no CMU parent, so there is no probe cycle.
Both providers suppress sysfs bind/unbind and the shipped kernel disables
MODULE_UNLOAD. This is a static-DT, resident-provider contract; hot removal or
runtime DT overlay removal of these clock devices is not supported.
The builder owns Kconfig/Makefile/DT/module/rootfs integration. The real module
inventory is the existing five plus this one combined driver, not seven.

Probe checks exact resource bounds, both rate IDs/version/mode, boot50,
reference250MHz, D10/M32..62/O3..128 capabilities and CPU/fabric limits. It
checks both meter IDs/version/width (4..32) and independent50MHz reference.
Malformed/unsupported devices fail probe. Busy/fault state remains observable;
it is not cleared or repaired by probe.

## Sysfs ABI (read-only)

Under the bound platform device (`/sys/bus/platform/drivers/valence-clockmon/`):

- `dvfs_policy`: runtime_switching=disabled, read-only, no boot change.
- `rate_status`: CPU/fabric configured/requested/target/boot Hz, status/errors,
  staged MDO, capability/admission, completion/state/range/reference fields.
  These are bounded stability reads of live registers, not an atomic hardware
  transaction snapshot. Staged MDO is NOT the confirmed active MMCM tuple.
  Configured Hz is NOT measured Hz. Diagnostic admission0x30 is NOT timing proof.
- `snapshot`: both banks in one text read, same sequence/timestamp/window,
  flags/validity/counter width/reference, measured Hz when usable, and eight
  delta/total pairs per bank. Unknown bits, overflowing counter width, wrong
  reference, zero window, or a counter width/window that could wrap even once
  at the maximum admitted domain rate return EPROTO. Changed sequences/live invalidation
  trigger at most four retries then EAGAIN. A coherent invalid window prints
  valid=0 and measured_hz=unavailable, never a valid-looking cached frequency.

There is no background polling or sampling interrupt. Reads are serialized by
a driver mutex and use ordered64-bit readq; no write callback exists. Multiple
reads may legitimately return the same hardware sequence. Tools calculating
rates over time must require sequence advancement and respect the raw counter
width when handling modulo wrap. Publication coherency is not exact simultaneity
of asynchronous Gray source counters. MMIO itself still needs fabric progress;
bounded software retries cannot recover a stopped/nonresponding bus.

CPU events0..7: edges, retire_lane0, scalar_lane1_request_fire, coherent_A_fire,
coherent_A_stall, complete_64byte_lineGrant, lineGrant_stall, no_retire.
Fabric events0..7: edges, AXI_AR_fire, AR_stall, AW_fire, AW_stall, R_beats,
W_beats, R_stall. Do not call request_lane1 a second retirement lane. A line
grant counts64 bytes; a stall is cycles, and AXI beats are not automatically
payload bytes. The driver does not invent cache-miss or total-A1-IPC events.
These are not a Linux perf PMU and do not support perf interrupt sampling.

## Runtime DVFS remains intentionally disabled

An eventual writable driver must serialize both domains and the entire staged
MDO/request/completion transaction, preserve hardware epoch/drain/receipt
ownership, integrate Linux DMA/GMAC submission closure and completion, and
handle interrupts/console/timers without disabling the very progress it needs.
Timeout is not cancellation; never resubmit or restart clocks blindly when
busy/fatal. A CPU target callback cannot safely stand in for fabric policy.
No direct userspace /dev/mem writes or generic fixed-clock set_rate substitute.

The emitted dynamic composition sets externalIrqsAbsent=true; in the platform
logic fabric safety requires that compile-time contract, while CPU is separately
allowed. This does not mean Linux IRQs/DMA are absent: integrated GMAC/CMU/UART
and AIA are real and need their specific owner/interrupt preservation proofs.
Before enabling runtime writes, verify the exact emitted external io.sources
tie-off and every internal drain/interrupt owner under concurrent Linux traffic,
not a DT boolean or an idle RAM payload. No custom SBI clock-rate extension is
currently supplied by the generic OpenSBI build.

Validated125MHz policy must use D10/M40/O8 (0x08280a), not the legacy canonical
125MHz D10/M50/O10. Same Hz does not imply the same native or timing evidence.
50MHz is D10/M40/O20. A pre-SBI firmware selection can establish an approved
boot rate without promising runtime Linux DVFS; Linux timebase stays250MHz,
and telemetry reference stays50MHz.

Host check: compile/run test_clockmon_abi.c with C11, -Wall -Wextra -Werror.
This executes the same parsing/coherency routines as the driver, including
two-bank invalidation races and bounded failure. Kernel module compilation,
actual probe/MMIO traffic, Linux concurrency and board behavior are separate
acceptance steps; host mocks do not prove them.

### Next CPU-only implementation, not delivered here

1. Add a separate sleepable cpufreq target_index driver and one shared rate
   transaction owner, with an exact profile table (initially boot50 and approved
   D10/M40/O8 only). No fast_switch and no boot-time transition or fabric write.
2. Keep stage/request/error/completion handling under that owner. Require a
   present, idle, valid controller, capture the old completion generation, then
   stage MDO and request once. Observe actual completion and configured Hz;
   on timeout retain an uncertain/busy state and prohibit another request until
   hardware resolves it. Do not treat software timeout as rollback/cancellation.
3. Preserve the existing CPU drain/epoch adapter and external receipt logic.
   Do not hold spinlocks, disable all interrupts, or stop progress needed by
   in-flight memory/interrupt completion. CPU-only changes must leave the
   fabric, DDR/UI, AON and fixed250MHz Linux timebase unchanged.
4. Prove real Linux interrupt, console, scheduler and concurrent DMA traffic
   across both directions and faults, plus native exact-profile timing and
   hardware cancellation/rollback outcomes. Report configured and independent
   measured frequency separately. Host MMIO mocks alone are not acceptance.
5. Fabric DVFS remains a separate task: GMAC/DMA submission closure, draining
   all ownership paths without discarding completions, IRQ retention and the
   exact externalIrqsAbsent compile contract must be verified first. The
   current hardware does not categorically reject fabric changes; missing
   Linux coordination/validation is the blocker, not an invented absent lane.

The separate boot-only I1 pair candidate is documented in `BOOT-PAIR-CANDIDATE.md`.
It does not alter the immutable CPU-only Debian delivery and does not expose
runtime fabric writes. CMUv1 index2 remains fixed TIME250.

## Explicit A1 runtime read-only candidate

This later source candidate does not modify the frozen I1 boot-pair or earlier
Debian packages. It is not enabled for the existing static A1 hardware.

Before mapping any extension MMIO, the driver requires all three identities:
root `openion,valence-a1-runtime-v2`, CPU `openion,orbital-a1`, and monitor
`openion,valence-a1-runtime-clock-monitor-v2`. Rate/performance resources remain
exactly `0x10080800/0x100` and `0x10080900/0x200`. CPU meter descriptor must be
ABI2 (`0x544d002000000002` at width32); fabric remains ABI1. An I1 profile still
strictly rejects ABI2. A matching DT is a deployment assertion, not bitstream
authentication; using it on old hardware is unsupported.

The A1 profile rejects the presence of any CPU control/observer-policy, CPU boot,
fabric boot, or I1 pair property before MMIO mapping. No CPU control initialization
or transaction is called. CPU arm/target sysfs writes remain disabled, and no
fabric write interface exists. Default boot targets are50/50MHz; observed actual
rates are read from hardware, not inferred from these targets. It does not inherit
I1's125MHz qualification or enable A1 automatic scaling.

CPU snapshot output now explicitly includes `retirement_lanes` and
`scalar_request_lane`. I1 uses1/1: event1 counts retirement lane0, event2 counts
scalar lane1 request fires. A1 uses2/0: event1 is the modulo-width sum of two
independently Gray-synchronized retirement lanes, event2 counts scalar lane0
request fires (the A1 uncached/MMIO lane). Event7 is a cycle with neither lane
retiring. Fabric fields are unchanged. The A1 window-wrap safety bound accounts
for up to12 retirements per50MHz reference cycle at the300MHz architectural cap,
not the single-lane6 bound. This cap is a parser bound, not physical qualification.

Host ABI tests cover strict profile mismatch, independent CPU/fabric ABI checks,
32-bit deltas, modulo totals, dual-lane narrow-width wrap limits and live window
invalidation. The production profile/probe extraction test verifies triple identity,
legacy rejection, every forbidden write property and zero writes. Kernel module
compilation, full hardware acceptance, physical implementation and Linux board
validation are separate evidence; host tests alone do not establish them.
