# Canonical virtual-store focused source fixtures

Status: source prepared on 2026-10-10. **Not compiled, elaborated, generated, executed or qualified.**
No simulator/toolchain setup, downloads, production preset changes, commits or pushes were performed by this work item.

## Entrypoints

| Scala emitter | Generated top | C++ harness |
| --- | --- | --- |
| `ooo.CanonicalStoreTrackerGsimMain <target-dir>` | `CanonicalStoreTrackerGsim` | `canonical_store_tracker.cpp` |
| `ooo.CanonicalStoreAdapterGsimMain <target-dir>` | `CanonicalStoreAdapterGsim` | `canonical_store_adapter.cpp` |
| `ooo.CanonicalStoreLsuGsimMain <target-dir> [2 or 4]` | `CanonicalStoreLsuGsim` | `canonical_store_lsu.cpp` |

The common independent software helper is `canonical_store_oracle.h`. The real-adapter driver also reuses
the existing software-only `virtual_load_test_memory.h` page-table generator. Build these through the
repository's existing GSIM flow after the parent authorizes the combined compile/check slot. No new build
target or Python runner is installed by this source-only work item. The LSU driver is intended to run with
both legal two-slot and four-slot emitters; it requires no private DUT field access or slot indices.

## Intended assertions

- Tracker: unsolicited/stale events cannot create ownership; start/capture require distinct edges; full ROB
  token, epoch, VA, size and mask matching; invalid matching shapes; 64-bit PA aperture boundaries; registered
  proof retention; owner loss, context loss, epoch change and same-edge invalidation precedence; legal eight-bit
  generation values through 255 without inventing allocator wrap; epoch rollover after complete proof disposal.
- Byte-disjoint helper: independent 128-bit half-open intervals, exact/partial aliases, all aligned subword
  lane combinations, same-beat disjoint bytes, upper PA bits, maximum-address endpoints and unaligned rejection.
- Real adapter and Sv39 service: cold walk/warm hit; real PTE flags, read/write permissions, A/D/U/SUM and PBMT;
  software-selected PA; final physical write PMP denial while PTE reads remain allowed; missing/stale origin;
  malformed lane mask/alignment; explicit RAM end and high PA; legal flush/remap/ASID changes; no certificate
  for fault, atomic, physical, uncached or ordinary-read cases; exact request/certificate/response ownership;
  queue fill, physical/response backpressure and full drain; successful authorization followed by a late physical
  store error. An observed certificate is compared with expected truth and never used to decide permission.
- ParallelLSU: no relaxation before the store request's registered acceptance, including the acceptance edge;
  exact token/tag and eligible owner class; no exemption for unprechecked/physical/atomic/store/forwarded/serial
  candidates; positive younger-load start while the real store response remains outstanding; held request/origin
  and arbiter-owner retention; cancellation while held and after acceptance; real ordered responses; original VA
  and precise late load/store access-fault cause; same-slot completion/replacement clears the old acceptance fact;
  complete request/response accounting after cancellation.

## Deliberate fault modes for later harness sensitivity checks

- `canonical_store_tracker --inject-valid`: corrupt one observed valid bit before comparing with the oracle.
- `canonical_store_adapter --inject-pa`: compare the first true certificate against an intentionally wrong PA.
- `canonical_store_lsu --inject-payload`: compare requests against an intentionally wrong address.
- `canonical_store_adapter --force-undrained-flush`: attempt an unsupported flush with accepted work outstanding;
  the design's integration assertion should terminate execution. A harness exception if that assertion does not
  fire is an additional failure, not evidence that the assertion was exercised. Inspect the actual failure log.

## Boundaries of these sources

These are three focused component fixtures, not one backend/platform integration or a complete acceptance result.
Tracker `invalidate` is externally driven; this does not prove the backend wires retirement, error completion and
recovery to it correctly. The tracker cannot independently authenticate a forged in-range PA substitution; the
real adapter fixture provides the separate production-truth check. The LSU's registered owner authorization is
an explicit input, so that fixture proves the narrow serial exception, not backend physical alias admission.

The drivers do not establish ROB/PRF retirement, dependent cancellation, allocator exhaustion, backend rejection
of a second older unissued store, forced-flush assertion behavior until run, committed memory contents, cache
store-miss fencing, probe/DMA ordering, posted-store integration, same-cycle backend completion-forwarding,
full-platform drain, OFF generated-structure equivalence, timing, resource cost, ROI performance or board results.
The adapter's physical endpoint is a deterministic ordered response stub and compares every request's payload;
it is not a coherent cache/memory-version oracle. Those obligations remain with the parent's combined acceptance.

No PASS line in these source files is evidence of a run.

Host getter audit: physical/LSU request payload construction occurs only inside `if (request.valid)`;
origin token/epoch sampling additionally occurs inside `if (origin.valid)`. Tracker owner getters require
a previously accepted software owner, certificate getters require a valid checked event or verified valid
registered certificate, and response/completion getters require valid handshakes and an established owner.
Held-payload comparisons reject withdrawn valid before sampling bits. No eager invalid-payload getter is
passed to a helper that checks validity afterward. This source audit is not a sanitizer or DUT runtime result.
