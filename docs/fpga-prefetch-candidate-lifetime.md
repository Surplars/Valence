# Bounded prefetch-candidate lifetime experiment

Status: the focused module/authorization/context gate passes. Keep the selected
profile unchanged until exact-board measurements qualify a useful variant.

The frozen full-board attribution reports 3,021 candidates in each read/copy ROI.
Every candidate is rejected solely because demand eviction entered `eCapture` on
the same edge as token creation. All other allocation exclusions are clear. Read
captures are 3,019 clean and two dirty; copy captures are 252 clean and 2,769 dirty.
The current one-attempt token expires before that otherwise eligible lane opens.

## Token and protection contract

- A token is created only by an accepted ordinary physical RAM read whose immutable
  `prefetchNextAllowed` capability came from `NextLineAuthorization`. That checker
  verifies the complete next cache line against RAM range, current effective PMP
  privilege and the captured page/PBMT context; it refuses page crossings, faults,
  atomics, stores, virtual addresses and uncached/MMIO requests.
- The cache captures the complete next physical line address at creation. Token
  validity records the authorization; it never reconstructs the address from a reused
  MSHR, a later request or a live privilege state. No MSHR or response credit is
  reserved until the unchanged allocation conditions succeed.
- The physical cache interface has no live PMP/VM epoch port. Its authorization epoch
  remains protected by the existing platform drain: `candidateValid` contributes to
  `prefetchBusy`, wired to the CPU's `externalPrefetchBusy` and `memoryBusy`. Both
  `reserveSystem` and `safeTrap` require `!memoryBusy`; PMP/SATP/xRET/SFENCE and
  automatic trap/interrupt context commits cannot cross a live token. The originating
  CPU memory owner already holds that drain at the creation edge. This compositional
  contract must be verified, not replaced with a later context reinterpretation.

## Bounded retry and cancellation

Compare explicit lifetimes of one (reference), three and sixteen allocation
attempts after the creation edge. Three attempts cover the unstalled clean victim's
capture/send/idle sequence; a dirty eight-beat C burst needs ten attempts without
stalls, so sixteen provides a small bounded margin. Neither bound guarantees an
allocation under arbitrary backpressure.

The token may retry only while eviction capture/send is the sole exclusion. Demand
miss/store/barrier, resident or reserved target, unavailable MSHR, dirty target victim,
writeback conflict, probe, bypass, flush, another prefetch owner, allocation success
or deadline clears it. Thus it never waits behind arbitrary traffic or steals a
resource from demand. Reset clears validity; flush has final cancellation priority.
A context transition commits only after the token has expired/cancelled or its
allocated prefetch and release owners have drained. No stale token survives that
boundary. Invalidation probes cancel a pending token conservatively.

All existing `canAllocate` guards remain authoritative, including `eIdle`; there is
no allocation shortcut through capture/send and no added term in CPU request-ready.
With lifetime one, the original behavior and state footprint remain available. A
longer lifetime adds only a bounded remaining-attempt counter. `prefetchBusy` continues
to include the token throughout that interval.

## Required gates

Use independent real cache/home memory for clean/dirty victim timing, both physical
ways, candidate suppression on denied/uncached/page-end requests, duplicate demand,
probe and flush cancellation, owner reuse, failed prefetch and held GrantAck/ReleaseAck.
Hold C beyond the deadline and verify candidate busy ends without allocation; a
forced live-token mutation must fail that bound. Retest context/barrier producers
with a bypass-busy negative, preserving the independent permission oracle. Then
compare the exact byte-identical board read/copy/chase and independent-line workloads,
including useful bytes, speculative traffic, two-owner occupancy and latency tails.

The bound applies only to the unallocated token. Once a demand or prefetch is issued,
normal transaction ownership may hold context admission until external responses
arrive. Unbounded external backpressure cannot imply a bounded total trap latency.
The deadline tests hold C after token expiry and keep a same-line request offered to
prove no refresh and no additional token busy hold. Existing context/busy tests then
check protected system/trap admission and a deliberate missing-busy negative.

## Focused results

`prefetch-candidate-lifetime-r1` passes the one/three/sixteen-attempt models plus a
sixteen-attempt fixture whose captured target lies above 4 GiB. Each runs 15 directed
lifetime/ownership/cancellation cases, payload corruption and a forced-live-token
deadline negative. The ordinary prefetch/home cases and two independent seeded
CPU/DMA traces also pass for all three budgets. The separate whole-line authorization
model passes 11,556 cases and its permission mutation; the real CPU system/trap gate
passes 10 cases and the bypass-busy negative. The context claim is compositional: this
cache/home fixture does not contain the CPU context transaction itself.

An unstalled clean victim permits allocation at attempt 3. A dirty eight-beat victim
permits allocation at attempt 10. Three therefore drops the dirty prediction; sixteen
permits it. When C remains blocked, tokens last exactly 1/3/16 observed attempts and
expire without allocation or refresh despite a continuously offered same-line read.
Demand/duplicate/store/uncached/dirty-target/no-MSHR/flush exclusions cancel at the
first observed attempt; the actual probe reaches and cancels the longer token at
attempt 4. Reset cancels before any later stale allocation.

In the independent 64 KiB adjacent stream, 8,192 demand loads and 1,024 physical-model
reads are identical. Cycles improve 71,113→67,773 (4.697%) with either 3 or 16 attempts;
useful prefetches rise 503→999. Prefetch-busy cycles also rise 32,861→65,749, so this
is not a blanket control-latency win. The dependent chase remains 16,725 cycles and
both randomized traces are cycle/counter-identical across all three variants.

The emitted counter is absent at 1, two register bits at 3 and four at 16. Those are
logical state counts, not mapped FPGA area. Prefer 3 as the smallest demonstrated
stream improvement; 16 requires a meaningful exact-board copy benefit to justify its
longer token hold. No CPU workload, physical DDR, routed timing or mapped area result
is claimed by this focused receipt:
`docs/evidence/fpga-prefetch-candidate-lifetime-20261008.json`.
