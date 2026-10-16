# GMAC driver cost audit and clock guard, 2026-10-16

## Scope and evidence

Base: `f4ae994` (full SHA in the verification receipt). Cloud-only source and host tests. No kernel build, RTL run, synthesis, or board measurement was performed for this candidate. Keep the published worktree unchanged. This is a small software clock-read reduction, not a throughput prediction.

Supplied board context: CPU 100 MHz; Linux TX 11.4 Mbps / RX 14.1 Mbps; memory READ 159.740, WRITE 72.575, COPY 58.653 MiB/s; BootROM DMA 327.980 MiB/s. Posted RX/TX each four slots, MAC RX four slots, DMA credits four. IRQ 6879, NAPI polls 7522, RX work 17632, empty polls 723, RX max batch eight, TX max batch four, completion peak four; RX errors zero/drop one. Link speed and CPU/softirq utilization were not supplied. These do not establish negotiated 1 Gbps, CPU saturation, or that the memory tests and network test have identical bottlenecks.

Aggregate ratios: 2.344 RX work/poll, 2.563 RX work/IRQ, 9.612% zero-RX polls. Zero-RX polls can reclaim TX and are not necessarily useless. These are lifetime ratios, not a matched measurement interval. The max batch reaching eight does not reveal how often the packet or time limit was hit.

## Steady-state posted path cost (source-level calls, not bus latency)

| Event | MMIO | Payload / synchronization |
|---|---|---|
| RX completion | STATUS, COMPLETE_ADDRESS, COMPLETE_RESULT: 3 readq | dma_rmb; one skb allocation; memcpy of full frame when allocation succeeds |
| RX release/repost | POP, POST_ADDRESS, POST: 3 writeq | dma_wmb before publication; original buffer is retained until copy completes |
| TX submit | ADDRESS, RESULT(length), COMMAND(POST): 3 writeq | one skb_copy_bits of full frame, dma_wmb; original skb freed only after copied payload has its pinned owner |
| TX reclaim | STATUS, ADDRESS, RESULT: 3 readq; COMMAND(POP): 1 writeq | dma_rmb; owner checked by count/order/address/length before release |
| No completion peek | 1 STATUS readq per RX/TX probe | validates ownership/STOP/reset even when empty |
| IRQ entry/rearm | one mask write / one unmask write when allowed | retained completions and active-state locked recheck preserve rearm race handling |

At RX poll exit on no work there is an additional STATUS read, unless the budget/time exit occurred first. TX reclaim can likewise add a terminal empty STATUS read unless its bounded loop already reached tx_slots. Even with zero TX software owners that read detects reset, stopped, or unexpected hardware ownership. Preserve it: removing it, including a last read after draining, weakens fault detection and can hide a new fault or repeated interrupt condition.

The three completion reads are serial in program order: STATUS establishes availability and ownership counts; address establishes expected FIFO owner; result establishes length/error. Retained completion semantics keep the head stable. Removing address or status checks without an equivalent independent guard weakens protection. Publication writes stage address/length followed by command. `readq/writeq` ordering and `dma_rmb/wmb` must remain; source call counts do not imply every write incurs a full roundtrip, and board cycle costs are unmeasured.

For N RX work and P NAPI calls, baseline performs P+N ktime_get_ns calls, including budget-zero calls and the last packet that already exhausts the budget. The supplied aggregate counters imply 25,154 such calls if they cover this unchanged source and a common lifetime. No time/cycle cost is known. Candidate saves one per budget-zero invocation and one per packet-budget-exhausted invocation; their frequencies are unknown. Positive-budget empty polls still take one clock read. Deadline is unchanged and checked after every packet below the packet budget, including GRO processing time, exactly as before. Neither version bounds a single packet operation or TX cleanup to two milliseconds.

Locks: one spin_lock_bh/unlock pair for TX cleanup per poll; one pair per RX attempt (including an empty attempt); one extra pair after successful NAPI completion to gate IRQ rearm; one pair per xmit. RX allocation/copy and TX copy remain under the lock. GRO remains outside. Queue core also performs bounded owner popcount, free-slot scan, and runtime modulo; requested software slot counts can be non-power-of-two (three is tested), so replacing modulo with a mask is invalid.

Each successful frame has one driver payload copy, hence at least one CPU source read and destination write in addition to DMA transfer. Memory COPY benchmark throughput cannot be converted directly to the driver fraction: cache/mapping, packet size, allocation, protocol/checksum work (CHECKSUM_NONE/no offloads), user copies, MMIO, and interrupts differ. RX/TX pools remain eight KiB each. This patch does not change hardware resources, ring depth, or zero-copy policy.

## Candidate and verification

Driver changes only:
- Skip deadline clock read for budget zero.
- Short-circuit packet-budget exhaustion before the per-packet clock read.
- Keep all ownership checks, barriers, copies, TX status reads, lock scopes, IRQ rearm, and ifdown pinning.

Original posted RX/TX tests failed to compile before changes: their shared fake kernel struct omitted managed_phy/link_speed, the real media decoder include was missing, and netif_carrier_on was missing. Fixing these test stubs was required; it does not prove a kernel build. The repaired stub exposes numeric media/MAC status inputs; it does not force media success. New cases cover 10/100/1000 media readiness, bad epoch/link/duplex/rate/version, MAC-not-ready, and managed ifdown/ifup without phylib calls.

After stub repair, original driver: RX 49 / TX 33 cases PASS. Candidate: RX 49 / TX 33 PASS, including TX payload-corruption negative control. New actual-NAPI-body suite: 13 cases PASS; budget zero, exact budgets 1..4, empty RX, TX-only, deadline just below/at/above 2 ms, fault, ifdown, and IRQ arrival on unmask. Three independently injected mutations are rejected: restoring the budget-zero clock read; restoring the exhausted-budget clock read; delaying the deadline by one second. Tests use ASan/UBSan and numeric fake-MMIO oracles. They do not execute a kernel scheduler or prove physical interrupt timing.

Commands from this worktree (each --out must be new):

```
python3 fpga/firmware/linux_net/test_posted_rx_driver.py --out /tmp/gmac-clock-baseline-rx
python3 fpga/firmware/linux_net/test_posted_tx_driver.py --out /tmp/gmac-clock-baseline-tx
# Above two ran after stub repair, before driver modification.
python3 fpga/firmware/linux_net/test_napi_clock_driver.py --out /tmp/gmac-clock-candidate-cost
python3 fpga/firmware/linux_net/test_posted_rx_driver.py --out /tmp/gmac-clock-candidate-rx
python3 fpga/firmware/linux_net/test_posted_tx_driver.py --out /tmp/gmac-clock-candidate-tx
(cd fpga/firmware/linux_net && python3 -m unittest test_build_image.ImageTests.test_irq_napi_source_contract_and_loader_order test_irq_napi_model)
git diff --check
```

Last unittest invocation: 10 tests PASS. JSON receipts are in `docs/validation/gmac-clock-guard-r1/`. Actual kernel compilation and all board A/B results remain outstanding.

## Next observation design (proposal only; not implemented)

No ABI or extra MMIO required; extend existing napi_status with counters owned by serialized NAPI/xmit contexts:
- poll_budget_zero: increment once at entry for zero budget.
- poll_rx_budget_exit: increment only on work >= budget.
- poll_rx_time_exit: increment only when the existing required ktime read reaches deadline below budget. Do not add any new clock reads.
- tx_reclaimed, tx_poll_no_owner, tx_poll_pending_no_completion: distinguish useful TX-only polling and empty checks without skipping checks.
- tx_stop_full and tx_busy_full: count full-ring stop decisions and rejected submissions separately from link/config/fault stops.
- tx_wake_calls plus tx_wake_from_stopped: distinguish repeated wake attempts from actual stopped-to-runnable transitions. Check existing queue-stopped state under the same lock before the call; avoid treating an already awake call as a transition.
- rx_alloc_fail and optional coarse batch histogram (0, 1, 2..3, 4..7, 8+) for actual work per poll, including budget returns whose return value differs from work.

Counters are cumulative observational values; READ_ONCE snapshots are not atomic across counters. Reset only with the documented lifetime, and compare matched before/after deltas. Do not add per-packet timing, hot-path printk, or forced extra MMIO just for instrumentation. Add host tests for exact exit reasons, full/wake counts, budget zero, STOP/fault and link loss to prevent counters from changing policy.

For a later explicitly requested board A/B: capture actual ethtool/sysfs speed/duplex/carrier; matched /proc/stat CPU/softirq deltas, /proc/softirqs NET_RX/NET_TX, /proc/interrupts, net-status, packet/byte/error/drop and TCP retransmit deltas around identical traffic duration/size/direction. Existing net-status does not include CPU, softirq, or link speed. Measure separately TX, RX, and bidirectional traffic; do not interpret a cumulative empty-poll count or successful throughput alone as CPU saturation or a gigabit link. Add observational counters before considering queue-depth increases or zero-copy.
