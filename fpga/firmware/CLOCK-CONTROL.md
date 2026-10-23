# Software clock control and board telemetry

Common-platform BootROM builds (`--boot-menu --common-platform
--common-clock-profile boot50-dynamic`) expose **f** from the UART menu.
No U-Boot is required. Boot still starts at 50 MHz; entering the console and
reading status do not change clocks. A new bitstream containing CMU rate ABI v2
and the telemetry pages is required for these commands; the R35 bitstream does
not acquire these capabilities by updating firmware alone.

Commands (press Enter):

- `status`: configured Hz, status/error bits, admission flags and capability bounds.
- `list`: initial software candidate points, 50 through 150 MHz in 5 MHz steps.
- `cpu 75` / `fabric 100`: independently request an exact rate in MHz.
- `perf`: measured clock Hz and one coherent window of performance counters.
- `quit`, Escape or Ctrl-C: return to the menu. Inactivity also exits after 30 seconds.

Printed numeric values use hexadecimal. Requests require quiet DMA and are
serialized; the autonomous always-on hardware drains traffic, gates clocks,
programs the MMCM, waits for lock and safely resumes. Firmware never bit-bangs
DRP or stops its own execution clock. Polling is bounded; timeout is not a
cancel and must not be followed by a blind retry. Inspect status and errors.

`valence_clock.h` is freestanding C with caller-supplied ordered 64-bit MMIO
callbacks, suitable for BootROM or a Linux kernel driver using mapped I/O and
its own synchronization. It is not a userspace `/dev/mem` API or an installed
cpufreq driver. Callers must serialize the staging plus request transaction.
The software exact integer search uses reference 250 MHz, D=10, M=32..62,
O=3..128 and checks `250000000*M == requestedHz*D*O`; no rounding, frequency
whitelist or vendor DRP addresses are embedded. Hardware additionally enforces
10..300 MHz CPU / 10..250 MHz fabric. The initial console deliberately exposes
only 50..150 MHz; extending software policy does not require a new bitstream
when the tuple remains inside the advertised hardware envelope. The initial
21 profiles use the same tuples as the native test: 50..75 MHz use O20,
80..150 MHz use O10, and M is the exact requested MHz multiplied by O / 25.
50 MHz is D10/M40/O20, matching cold boot and fallback. Other exact solutions
from the generic search are not advertised or native-qualified by this suite.
M63/64 are excluded due to a vendor driver/model analog-parameter conflict.

## Do not confuse three different claims

1. Configured Hz is the controller's selected setting, not a frequency meter.
2. Measured Hz is managed clock edges counted against the independent 50 MHz
   always-on reference over a 50,000-edge window. Stale/transition samples are
   not printed as valid measurements.
3. Neither reading proves setup/hold closure or stable execution. Admission
   flags 0x30 mean diagnostic candidate/admitted, not component or SoC timing
   qualification. A requested high rate can still fail to execute correctly.

CPU counter order: clock edges, retirement lane 0, scalar lane 1 request fire,
D-cache coherent A fire, A backpressure, accepted 64-byte data line grants,
backpressured data line-grant cycles, no-retire. Slots 5/6 observe the internal
`lineGrant(1)` refill path, not ordinary coherent D responses/ReleaseAck.
Each slot-5 event is one complete 64-byte line, not one bus beat; slot 6 counts
stall cycles and must not be multiplied by 64 as transferred bytes.
For the current single-retire I1, retirement lane 0 / edges is IPC; this must
not be presented as total IPC of a future multi-retire core. Private-cache miss
and detailed core-stall counters are not implemented by this event ABI.
Fabric counter order: edges, AXI AR fire, AR stall, AW fire, AW stall, R beat
fire, W beat fire, R stall. Beat counts are accepted traffic, not bytes unless
combined with actual bus width and valid byte lanes. CPU and fabric samples
share an AON publication boundary but Gray synchronization adds source-edge
boundary uncertainty; they are not exact cycle-simultaneous observations. The meter continues counting from
AON while managed clocks stop, but MMIO responses still depend on the fabric
transport resuming; this is not an independent always-on debug port.

## Focused checks

Build and run `test_valence_clock.c`, `test_valence_perf.c` and
`test_boot_clock_console.c` with a C11 host compiler and `-Wall -Wextra -Werror`.
These tests exercise exact profile generation, safe rejection, bounded waits,
coherent sample reads, transition invalidation and the actual console parser.
They do not claim native MMCM, routed timing or board qualification.
