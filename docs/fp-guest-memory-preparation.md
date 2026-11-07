# FP guest-memory component preparation

This is a default-off preparation stage following `dual-fs-preparation.md`.
It does **not** enable guest F/D. Both actual `MachineSystemUnit` and
`IntegerBackend` H+FP guards remain, and the real backend still needs a coherent
integer/H/FP memory-owner selector. No default, ISA advertisement or firmware
declaration changes here.

## Production changes

`DataResponseBuffer` can optionally store `GuestFaultMetadata` in the same
two-credit envelope as the native response. Its public native memory protocol
does not change. Data, error, page-fault indication, optional reservation handle
and guest metadata share enqueue, dequeue and live-versus-queued selection.
The default has no new metadata ports or payload fields. All four existing
flow/registered-payload/registered-head combinations retain their latency,
capacity and occupancy-only ready contracts. A full queue cannot borrow a
same-edge dequeue credit.

`FloatingPointMemoryPipeline` takes optional effective guest-address provenance
and response metadata when `hypervisorExperiment` is selected. Guest-address
provenance is captured with permission and translated-handling inputs at the
existing LSU `start.fire`, not at earlier AGU preparation. Response metadata
passes through the real response buffer to the LSU, whose existing precise
fault classification is unchanged.

`FloatingPointMemoryContext.translated` distinguishes translated handling from
architectural V: host translation active **or** effective guest-address context
requires downstream translation checks. In particular, VS Bare does not bypass
G-stage translation or prematurely apply physical PMP to a guest address.
The final translated physical address still receives normal PMP/PMA checks.

`FloatingPointResult` optionally carries the complete guest fault envelope.
Shared production converters replace both result conversions in
`FloatingPointSystem`; they preserve complete ROB index/tag, data, exception,
cause, original tval and all metadata, including successful guest-address
provenance. Memory flags are zero. Arithmetic and illegal producers initialize
their guest metadata to zero. The existing FP state retains the whole matching
result and mutates architectural FP state only on an authorized successful
matching retirement.

Distinct optional `fpMemoryFault` plumbing and the effective-context helper are
present in MSU/backend source, behind the unchanged H+FP rejection guards.
They are preparation for later integration, not proof that this dormant
assembly executes.

## Ownership and timing

- The FP execute handshake is the registered LSU acceptance boundary. An AGU
  payload may exist earlier; permission and effective context remain live until
  acceptance.
- The guest adapter captures context later at its native virtual-request
  handshake. The caller must hold context between those boundaries. After that
  capture, unrelated live context changes cannot alter the accepted owner.
- The walker requires PMP state stable until idle. Context capture is not
  permission to replace PMP while a walk is active.
- The adapter's guest fault output has only the corresponding virtual response's
  lifetime. Incidental register retention cannot substitute for buffering it
  with the accepted response.
- ROB index plus the complete tag identifies the FP owner. A native return
  handle identifies a different reservation namespace; neither replaces the
  other.
- The ordinary FP pipeline remains single-owner. Its two response and two
  completion credits do not grant speculative or overlapping FP execution.
- No new cancellation, reset-while-owner or IRQ behavior is introduced.

## Focused GSIM entry

Run `make gsim-fp-guest-memory-test` with the pinned repaired GSIM toolchain.
The entry uses the same strict `common.setup(False)` binding as the earlier
portable H tests and has no unverified-reuse or simulator-fallback option.
`IonSoC.fpGuestMemoryPreparation` retains all production and HardFloat sources,
while restricting test compilation to the affected fixtures and configuration
checks. Native drivers run with ASan/UBSan.

The nested-memory fixture connects genuine FP state, FP memory, guest data
adapter and nested Sv39/Sv39x4 walker components. Its independent native memory
model answers real PTE and physical data requests. No synthetic successful FP
memory result is injected. Decoded commands and exact-token retirement grants
are component stimulus, **not** executed CPU instructions or an operating
system's retirement stream.

The bounded matrix covers FLW/FSW lanes and FLD/FSD, raw data and neighboring
bytes, nonidentity VS/G translation and VS Bare/G active, selected VU permissions,
and original misalignment, VS page faults, explicit and implicit G faults,
final physical PMP/PMA denial and physical response errors. It checks raw
unshifted GPA, original-address tval, access class, guest-address provenance,
unchanged fault destinations/flags and absent forbidden physical offers under
two deterministic legal stall schedules. Full-width owner tags and pre-acceptance
versus post-adapter-capture context changes are observed directly.

A separate buffer fixture exercises all four legal modes with metadata on/off
and return handles present/absent. It verifies full queues and held responses
without adding an artificial readiness gate to the production FP pipeline.
Named negative controls corrupt independent checker observations and must fail
at their named checks; a crash, timeout or sanitizer failure is not proof.
Raw observed traces support a separate replay audit.

## Remaining release gates

This stage does not exercise actual-core H+FP arbitration, guest arithmetic
instructions, HS trap-handler CSR reads, software save/restore of host and two
guest FPR/fcsr images, or an OS. Component result handling is not evidence of
precise CPU retirement or complete software isolation. Full guest F/D remains
unavailable until those real-core end-to-end and context-switch gates pass.
The single physical FPR/fcsr bank still requires explicit software management.

There is no independent-clock, multicore, ISA-compliance, PPA, board or speedup
claim. The current component build budget does not establish capacity for a
full-F/D core build. Preserve prior source/evidence, use fresh source-bound
outputs, and stop on resource shortages rather than weakening validation.

Normative references remain the pinned RISC-V v20250508 H 1.0, Machine 1.13,
F 2.2 and D 2.2 chapters. Guest-page GPA stays unshifted in component envelopes;
later trap CSR logic is responsible for the specified HTVAL shift. Implicit
VS PTE accesses retain the original load/store exception class and their own
read permission semantics.
