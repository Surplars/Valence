# Board performance telemetry ABI v1

This is passive hardware measurement, not a configured-frequency readback and
not an ILA dependency. The existing MMIO path (including a debug master with
MMIO access) reads it. The current register source is the fabric clock, so
that clock and the relevant MMIO transport must run to complete reads. CPU halt
does not stop measurement, but this block alone is not an independent AON debug
transport that can read through a stopped fabric. It does not introduce
traffic stalls or affect functional READY signals.
The I1 diagnostic platform wires CPU and fabric events as listed below.

## Registers

CPU base `0x10080900`, fabric base `0x10080a00`. Read-only, aligned 64-bit reads
(size=3, byteEnable=255). Writes, narrow/misaligned accesses, holes, and addresses
outside both pages return an error, with no counter side effect.

| Offset | Meaning |
| --- | --- |
| 0x00 | 64-bit publication sequence, incremented each observation window |
| 0x08 | flags: bit0 published sample valid; bit1 zero managed edges; bit2 currently invalidating |
| 0x10 | reference frequency, 50,000,000 Hz |
| 0x18 | observation window, 50,000 reference edges (1 ms) |
| 0x20 | reference-edge timestamp of publication, modulo 2^64 |
| 0x28 | ABI: bits63:48=0x544d, bits39:32=counter width (32), low32=version1 |
| 0x40..0x78 | eight unsigned per-window counter deltas, zero extended to64 |
| 0x80..0xb8 | eight cumulative modulo-2^32 totals at the same publication |

Both banks publish on the same AON edge, with the same sequence and timestamp.
Read sequence, desired fields from either/both banks, then sequence again;
retry if sequences differ. Each 64-bit MMIO read is atomic. No software latch
or write/clear is needed. A cold reset clears the sequence; software must
reinitialize its observation state after cold reset. Sequence wraps after
2^64 windows. Bit1 belongs to the published sample. Bit2 is live; bit0 is also immediately
revoked when invalidation starts, even before the next publication. Read flags
again before the final sequence check to reject a transition during the read.

Counter0 is unconditional real managed clock edges, even while the CPU is idle.
CPU counters1..7 are respectively:
1. architectural retirement lane0;
2. scalar data lane1 request accepted (uncached/MMIO);
3. coherent D-cache client1 A-channel accepted;
4. that A channel valid and not ready (backpressure cycles);
5. D-cache client1 private lineGrant accepted (one complete64-byte refill grant);
6. that lineGrant valid and not ready (backpressure cycles);
7. cycle without retirement lane0.

Fabric counters1..7 observe the fabric-side DDR AXI boundary:
1. AR accepted;
2. AR valid and not ready;
3. AW accepted;
4. AW valid and not ready;
5. R beat accepted;
6. W beat accepted;
7. R valid and not ready.

These are not private cache hit/miss counters, aggregate SoC bus traffic, exact
instruction dependency stall causes, or DDR physical-device utilization. An
accepted coherent beat is not necessarily a cache miss or one instruction.
“No retirement” includes idle/reset/quiesce and traps, not just performance stalls.
Compare intervals that execute a known workload and exclude invalid epochs.
This profile uses internalLineGrant: cache fills return on the dedicated
512-bit lineGrant, not ordinary TileLink D GrantData. Counters5/6 therefore
observe lineGrant exclusively. They do not OR D and lineGrant (ReleaseAck may
overlap a line grant), and they do not count D ReleaseAck traffic. Each accepted
lineGrant counts one complete64-byte refill transfer, not eight D-channel beats.

CPU retirement/edges gives sampled IPC; A backpressure and DDR request/beat
rates distinguish visible transport pressure from a lack of CPU progress.
R/W count beats, not bytes: partial last beats/write strobes are not counted as
full payload bytes. No hidden or fabricated hit/miss metrics are exposed.

## Measurement and CDC

Each event is a single Boolean event per source edge. The eight32-bit binary
counters increment by zero or one only, with registered Gray encodings, then
cross independent two-stage ASYNC_REG synchronizers. Both synchronizer banks
are reset from synchronized common cold reset. The sampling logic never reads
a live asynchronous binary counter. No request handshake is needed from a
stopped managed clock, so stable stopped clocks eventually measure zero.

Cumulative values wrap modulo2^32; subtraction is modulo2^32. The integration
must keep fewer than2^32 source edges per observation window (300MHz/1ms=300000,
well inside the limit). Natural wraps do not invalidate measurements. Event
counters cannot increment faster than the edge counter. Warm switching must
NOT reset counters. Assert AON invalidate throughout reset/clock transitions
or other invalid epochs; this immediately revokes published validity (so a
short completed switch cannot make an old sample look current), and a dirty
interval and the following interval are
rejected. Startup likewise requires two discarded intervals. The interval
immediately after a short invalidate is not falsely reported as stable.

Snapshots are coherent AON publication records, NOT an assertion that all
asynchronous event counters were sampled on precisely the same managed edge.
Two-stage sampling adds boundary uncertainty; event counters can differ by
near-boundary events. Metastability resolution/phase can add another sampling
edge. This is bounded statistical telemetry, not cycle-exact causal tracing.
At nominal1ms window, one counted edge corresponds to1kHz. Accuracy also
inherits the actual50MHz reference oscillator accuracy. Use longer software
averages for frequency estimates. The PHY clock lock flag alone does not prove
this reference assumption. Check sample valid and live invalidating flags.

Required physical constraints are in
`fpga/zu15eg/performance-telemetry-constraints.tcl`. Apply the procedure at the
actual post-synthesis telemetry hierarchy, with a delay/skew budget below the
fastest supported source period (e.g.3.0ns for300MHz target), and verify routed
coverage. It traces actual source drivers to survive Gray-MSB register merging.
ASYNC_REG alone is insufficient. Broad asynchronous false paths must not
supersede the max-delay constraints. No routed timing/CDC success is claimed
by elaboration or simulation.

## Firmware example (RV64, ordered volatile MMIO)

```c
#include <stdint.h>
struct sample { uint64_t seq, flags, ref, window, count[8]; };
static uint64_t rd(uintptr_t a) {
    uint64_t v = *(volatile uint64_t *)a;
    __asm__ volatile ("fence iorw, iorw" ::: "memory");
    return v;
}
static int read_sample(uintptr_t base, struct sample *s) {
    uint64_t last, end_flags;
    do {
        s->seq = rd(base);
        s->flags = rd(base + 8);
        s->ref = rd(base + 16); s->window = rd(base + 24);
        for (unsigned i = 0; i < 8; ++i) s->count[i] = rd(base + 64 + 8*i);
        end_flags = rd(base + 8);
        s->flags |= end_flags & 4;
        if (!(end_flags & 1)) s->flags &= ~1ULL;
        last = rd(base);
    } while (last != s->seq);
    return (s->flags & 5) == 1;
}
/* measured_hz = count[0] * ref / window;
 * CPU ipc_scaled_1000 = count[0] ? count[1] * 1000 / count[0] : 0;
 * Do not interpret count[1] as retirement for the fabric bank. */
```

Read CPU and fabric under one outer sequence check when comparing the same
observation interval. If a slow debugger cannot finish before the1ms update,
use a firmware routine to copy the coherent result into ordinary RAM, then
read that RAM through the debugger. Do not silently combine different windows.

## Native flow integration and required acceptance

The canonical `fpga/common/post_synth.tcl` and `post_opt.tcl` both invoke
`common_performance_telemetry_constraints`. `diagnostic.py` freezes the emitted
`performanceTelemetry` Boolean as configuration `performance_telemetry` and
writes `set valence(performance_telemetry) 1` for enabled candidates.
`board_inputs.py` rejects disagreement between emitted feature/ABI and config.
The enabled procedure requires `u_soc/monitor`, exactly16Gray banks of32bits,
and the complete register bridge. Disabled legacy configurations reject an
unexpected monitor instead of silently omitting constraints. One scoped cell
collection is reused for all banks. Post-opt reapplies these after mapping.

A manually generated/local continuation Tcl must set the same explicit feature
flag and source/call these hooks; it must not inherit a legacy flag0 config.
Before placement, retain the `COMMON_TELEMETRY_BOUNDED` receipt and16
`VALENCE_TELEMETRY_GRAY` records. After routing, verify all16 banks' actual
max-delay and skew timing and the complete register bridge in reports. A Tcl
mock test validates collection/count/error behavior, not physical CDC closure.
The old immutable diagnostic baseline remains immutable: a fresh changed-RTL
source inventory/profile must be reviewed rather than bypassing its gate.

## Focused functional evidence (2026-10-23)

The emitted width10/window128 component fixture passed the independent Icarus
RTL oracle: real50/100MHz and stopped0, unrelated phases, natural counter wraps,
active/inactive event masks, cold reset, transition-invalid windows, read-only
MMIO holes/out-of-range rejection, sequence retry, and response stability under
backpressure across publications. A short-transition regression deliberately
rejects the pre-fix RTL because it resurrected an old valid snapshot after the
live invalidate level cleared. The fixed RTL passes the same oracle.

Commands: emit `ip.ClockPerformanceTelemetryMain`, then run
`simulator/cdc/test_clock_performance_telemetry.py --rtl <emitted-dir> --out <receipt-dir>`.
The runner records actual RTL/testbench hashes, exit codes, and terminalPASS/FAIL.
`fpga/common/test_performance_telemetry_constraints.py` supplies three focused
mock/static constraint tests; existing board-input14 and diagnostic4 tests also
pass. Neither Tcl mocks nor functional RTL simulation prove metastability MTBF,
routed skew/delay closure, native primitive legality, or board frequency limits.
The full-I1 guest test separately exercises real telemetry reads and DDR loads;
its final acceptance must be reported from the actual run, not this component test.


The first full-I1 telemetry attempt exposed an integration error: counters5/6
observed ordinary D, while the guest correctly required a real cache-fill
response. With internalLineGrant enabled, the initial clean read returned on
the dedicated lineGrant and produced no D ReleaseAck, so the guest's positive
response-count check could not complete. The integration now observes the
actual lineGrant exclusively; the guest's positive oracle was preserved. That
failed attempt remains failure evidence, not a successful full-platform run.
