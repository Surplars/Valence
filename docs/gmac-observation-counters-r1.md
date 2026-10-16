# Low-overhead GMAC observation counters, 2026-10-16

Second independent commit, based on 232d3fa9a968341141b52877999d767543bf5ecc. Software observation only. No hardware ABI change, added hardware MMIO, added ktime calls, hardware queue-depth change, or ownership-policy change. No kernel compilation or board measurement; actual negotiated link speed remains unknown.

## Export and precise definitions

Nine cumulative unsigned 64-bit counters are appended to the existing `napi_status` sysfs line, preserving all original field names and order. The existing `net-status` script already prints it. They start at device allocation, survive ifdown/ifup, and are not reset by reads. Read snapshots use READ_ONCE per field, not an atomic aggregate snapshot. Compare matched interval deltas; a single counter's wrap uses ordinary modulo arithmetic. Counter storage adds 72 bytes to device private state, plus target-dependent possible structure alignment; hardware resource cost is unchanged.

| Appended field | Definition |
|---|---|
| poll_budget_zero | Every NAPI invocation with budget zero, including inactive invocations; never implies RX work or NAPI completion. |
| poll_rx_budget_exit | Return caused by actual RX work reaching packet budget. Checked first, so wins when packet and elapsed-time limits coincide. |
| poll_rx_time_exit | Return below packet budget caused by the existing clock check reaching the original two-millisecond deadline. Mutually exclusive with packet-budget exit for each invocation. Includes elapsed time before RX and in GRO just as before; not a hard preemptive cap on a packet. |
| tx_reclaimed | Successfully acknowledged/released TX completions, including hardware error completions. Excludes a completion whose ownership check/release fails. |
| tx_poll_no_owner | Active poll entering TX cleanup with no software-owned TX buffers. It counts idle state, not an error, and still performs the posted STATUS ownership/fault check. A newly detected reset or unexpected hardware owner can coexist with this counter. |
| tx_poll_pending_no_completion | Active poll with software TX ownership whose first completion check reports no completed work; excludes ownership faults and polls that reclaimed at least one completion. Supports posted and legacy modes. |
| tx_full_stops | Successful enqueue fills the posted ring (or occupies the single legacy buffer), and the queue is observed awake before the existing stop request. Repeated full checks or NETDEV_TX_BUSY calls do not increment it. Already-stopped queues do not increment it. Link/config/fault/ifdown stop requests are excluded. |
| tx_poll_wakes | NAPI TX-cleanup wake request whose original space/carrier/not-faulted predicate passes and whose queue is observed stopped immediately before the existing wake call. Already-awake calls do not increment. Configure/phylib wake calls are outside this counter's scope. This records a sampled request condition, not proof of a scheduler transition or transmitted packet. |
| rx_alloc_fail | Valid-length, non-error RX completion for which napi_alloc_skb fails. Does not count malformed/error frames. |

All original wake/stop calls remain in their original conditions, including wake calls on an already-awake queue. The counter guard does not suppress calls or add a hardware read. Counters are written from their existing serialized NAPI/xmit contexts; a reader may observe values from different instants. Empty TX/RX polls can be normal, and reclaimed error completions are intentionally included in tx_reclaimed.

## Independent host verification

Actual driver function bodies are compiled with fake kernel/MMIO boundaries under ASan/UBSan. The shared fake queue now tracks awake/stopped state instead of just counting calls. The counter-specific test uses independent numeric expected event values and counts every driver MMIO wrapper call. It executes the real napi_status_show function, verifies old field ordering and appended values, and checks that reading sysfs performs no MMIO or clock reads.

22 cases pass, including:
- Active empty zero/positive-budget polls and zero-budget no-clock behavior.
- TX pending, completed, errored, malformed ownership and reset with no software owner.
- Ring fills once, repeated busy submission, already-stopped ring fill, wake only when stopped, no wake when link is down.
- Packet/time priority when both limits coincide, limits 1..4, full packet batch with exact MMIO and clock-call counts.
- Allocation failure versus malformed frame, RX STOP fault, and inactive ifdown zero-budget invocation.
- Legacy TX completion and sysfs export.

Four mutation controls are rejected: increment both exit reasons; count every wake attempt; mark idle TX as pending; omit full-stop events. Existing RX49, TX33 (with payload mutation), clock13 (with three clock/deadline mutations), and ten IRQ/source-contract unittest cases also pass. Kernel scheduling, true CPU-cycle overhead and board interrupt timing are not emulated or claimed.

Reproduction commands from worktree root (fresh output directories required):

```
python3 fpga/firmware/linux_net/test_napi_counters_driver.py --out /tmp/gmac-counter-events-export
python3 fpga/firmware/linux_net/test_posted_rx_driver.py --out /tmp/gmac-counter-rx-final
python3 fpga/firmware/linux_net/test_posted_tx_driver.py --out /tmp/gmac-counter-tx-final
python3 fpga/firmware/linux_net/test_napi_clock_driver.py --out /tmp/gmac-counter-clock-final
(cd fpga/firmware/linux_net && python3 -m unittest test_build_image.ImageTests.test_irq_napi_source_contract_and_loader_order test_irq_napi_model)
git diff --check
```

Persisted receipts: `docs/validation/gmac-observation-r1/`.

## Using later board results

Record counter and /proc/stat, /proc/softirqs, /proc/interrupts, network byte/packet/error/retransmit values immediately before and after matched TX/RX traffic, with actual speed/duplex/carrier and packet size/duration. A high time-exit delta indicates the software's elapsed-time limit was encountered; a high budget-exit delta identifies packet-budget limiting. Full-stop/wake cycles identify queue backpressure episodes but do not alone identify DMA bandwidth or CPU as their cause. Pending-without-completion versus no-owner helps interpret zero-RX polls. No automatic traffic or board action is part of this patch.
