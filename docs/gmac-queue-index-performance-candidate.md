# GMAC ring-index candidate and focused performance audit

2026-10-23, cloud-only incremental source candidate. Frozen Debian packages and
FPGA bits are unchanged. No board throughput or kernel-module qualification is
claimed; this is a small arithmetic change with host correctness evidence.

## Evidence-backed hotspots, not measured stall attribution

In `fpga/firmware/linux_net/valence_gmac.c`:

- Posted RX reads status, retained completion address and result for each frame.
  It allocates an skb, copies the coherent DMA buffer once, then POPs and reposts
  that same buffer. Release writes POP, address and POST. A consume/publish DMA
  barrier protects the ownership handoff. Removing the copy without replacement
  buffer ownership would permit DMA to overwrite data still owned by the stack.
- Allocation/copy/repost execute under `p->lock`; GRO delivery is outside it.
  This extends the serialized interval but changing it needs a separate ifdown,
  fault and buffer-ownership proof. No lock or copy is removed in this candidate.
- Posted TX copies skb data once with `skb_copy_bits`, permitting non-linear
  skb input, and retains each coherent slot through completion. Legacy TX has
  only one live transaction and stops its queue; posted slots are already used
  when hardware advertises them. No extra concurrency or offload is invented.
- NAPI has weight 8 and a 2 ms bound, cleans TX independently of RX budget and
  does not busy-wait for RX hardware. It avoids a clock read when budget is
  already exhausted. Per-frame time checks remain to bound softirq occupancy.
- IRQ is masked before scheduling, stays masked on budget/time exits, and is
  re-enabled after successful NAPI completion under the state lock. Latched
  completion closes the completion/unmask race. No interrupt barrier is removed.
- RX capacities are already published once at queue start, rather than per
  packet. The remaining three completion reads validate ownership and should
  not be removed based on a guessed FIFO ordering or a stale status snapshot.

`napi_status` already exposes allocation failures, batches, completion peaks,
budget/time exits, empty polls, full-TX stops and pending TX polls. Paired board
counter deltas plus packet sizes and actual clock/PHY rates are needed to rank
these costs. This code inspection is not evidence they dominate live traffic.

## Minimal change

Four ring head/tail updates used `(index + 1) % q->slots`. Queue initialization
admits depths 1 through 16, including non-powers-of-two, initializes indices to
zero and all updates preserve `index < slots`. Replace them with the shared
`vgq_next`: increment, compare with slots, wrap to zero. Do not use a bit mask.
All initialization rejection, ownership checks, MMIO and barrier order remain
unchanged. Malformed external inputs cannot select an unchecked ring depth.

Real GCC RV64GC / LP64D `-O2` assembly of production `vgq_post`,
`vgq_release(repost=true)`, `vgt_post`, `vgt_release` wrappers contains five
`remuw` instructions before, and zero div/rem instructions after. The fifth is
the repost path in RX release. This proves removal of runtime remainder, not a
measured packet-latency or bandwidth improvement. The compiler had not already
optimized it away.

## Short validation

- `test_queue_index.c`: all legal depths 1..16, all legal starting indices,
  64 complete wraps per start, 95,744 transitions equal the independent modulo
  oracle. Actual RX/TX post paths also traverse every depth and wrap their tails.
- Invalid depths 0/17, disabled queues, out-of-range/duplicate slots, zero or
  oversized TX length, invalid RX capacity, overlapping/misaligned buffers
  remain rejected. Invalid initialization is not passed into the internal helper.
- Actual driver-body fake-MMIO regressions: RX 49 cases and TX 33 cases PASS,
  including copy-before-POP/POST, queue full, IRQ rearm, reset/stop, budget-zero,
  legacy paths and pinned ifdown ownership. Mocks are not kernel/RTL execution.
- ASan+UBSan index test PASS with leak detection disabled because LeakSanitizer
  cannot run under the executor's tracing environment; no sanitizer was used as
  a claimed hardware proof. Normal address/undefined checks stayed enabled.
- Independent review confirmed the invariant and old/new assembly evidence.

Evidence directory: `build/gmac-queue-index-r1`. Reproduce short host tests:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined \
  fpga/firmware/linux_net/test_queue_index.c -o /tmp/test-queue-index
ASAN_OPTIONS=detect_leaks=0 /tmp/test-queue-index
python3 fpga/firmware/linux_net/test_posted_rx_driver.py --out /tmp/queue-rx
python3 fpga/firmware/linux_net/test_posted_tx_driver.py --out /tmp/queue-tx
```

No full image rebuild was run. A subsequent module/image candidate must bind
these exact sources and receive its normal module build/audit before delivery.
