# Native CPU/fabric boundary acceptance

This is a narrowly scoped independent-edge digital check of
`TileLinkClockDomainBoundary`, following the existing native MAC CDC Icarus
precedent. GSIM remains the project's supported general hardware simulator.
This component test does not qualify a whole CPU tile or a board profile.

## Explicit storage profiles

`ip.TileLinkClockDomainBoundaryMain <fresh-dir> [baseline|held]` exports the
64-bit address/data, three-bit source and one-bit sink profile:

- `baseline` (also the omitted-argument default): existing `CdcDataFifo`, RAM
  depth 4 per lane, approximately II=2 read/capture transport
- `held`: imported `HeldResponseCdcDataFifo`, RAM depth 16 per lane, with one
  captured output and one RAM response that keeps its slot until capture

The boundary's library compatibility default remains the baseline. The new I1
independent-clock assembly explicitly selects held storage for every data lane;
it never falls back to the II=2 comparison. The Makefile component targets
require `CPU_FABRIC_CDC_STORAGE=held|baseline` explicitly. The held implementation
is reused, not replaced or reinvented by this test. Its imported source SHA256 is
`2302decf7392cfd64fdec49a4c2b76470f45c98f736644c2ddb64d0cef21d126`.

The emitter uses `--lowering-options=disallowLocalVariables`; the runner rejects
unsupported local lifetimes rather than rewriting RTL. Run using existing tools:

```sh
python3 simulator/cdc/test_tilelink_boundary.py /fresh/held-export /fresh/results \
  --storage held --baseline-receipt /previous/baseline/receipt.json \
  --iverilog /path/to/existing/iverilog --vvp /path/to/existing/vvp
```

The baseline profile uses `--storage baseline`. Comparing with an existing
baseline receipt reads and hashes it without rerunning or altering old evidence.
The runner validates the selected FIFO type, RAM depth and five real instances.
The output directory must be new. A 4 GiB free-space floor is monitored while
children run; timeout or floor breach terminates their entire process group
while preserving logs. Receipts contain minimum free space, resource usage,
input/source/tool hashes, copied small inputs, and measurement summaries. Pair
one with the central compile/export receipt for elaboration provenance.
Nothing here invokes a Scala build, installs tools or uses a fallback simulator.

The separate actual-CPU short-boot entry is described in
[I1_INDEPENDENT_BOOT.md](I1_INDEPENDENT_BOOT.md). Its `test-only` and `full-cpu`
selections must be explicit; the small test fixture is never a release default.

## Functional coverage retained in both profiles

- Three clock ratios and phases, plus delayed initial fabric-clock startup.
  Both clocks run throughout normal operation. All five channel admissions
  remain closed until both reset-release sequences have completed.
- Whole-beat FIFO ordering and every payload bit at both logic values, including
  source/sink IDs, masks, denied and corrupt. Source and destination payloads
  remain stable under backpressure. Expectations use external accepted traffic,
  never DUT pointers, RAM slots or synchronized idle flags.
- Eight accepted A requests before the first D response, then source order
  5, 2, 7, 0, 6, 1, 4, 3. Each GrantData has eight contiguous beats, representing
  a 64-byte I1 line. E is accepted only after the complete grant, and its sink
  must be returned before reuse. Changing storage does not reduce owners.
- All five FIFOs fill and backpressure their sources. Each blocked lane must
  accept exactly `RAM depth + 1` beats: the pending RAM response still owns its
  RAM slot. B, C and E then finish `2 * depth + 16` beats each while A/D remain
  full and blocked. Depth 16 therefore receives more stress, not weaker stalls.
- In both directions, local transport-empty may be true while the remote output
  is held. Both transport-empty flags may also be true while eight external
  transaction owners still await responses.
- Common cold reset discards `depth` old beats per channel, followed by a
  no-traffic replay observation window and `depth + 20` clean new beats per lane.
  Every affected whole-system owner must participate in that reset contract;
  a FIFO cannot cancel an already accepted external operation.
- Payload/source/sink observation perturbations must be rejected. Treating both
  empty flags as global owner drain must also fail. These four negative controls
  never modify production RTL.

## Latency, capacity and throughput are separate measurements

The runner records empty-queue accept-to-delivery latency in nanoseconds and
elapsed destination edges for each lane, plus exact accepted capacity while
blocked. It then issues simultaneous unthrottled 128-beat streams and measures
96 interior transfer gaps per lane. Source rate, phase and credit return can
limit these end-to-end rates; no owner reduction or backpressure removal is used
in the separate functional scenarios to make performance pass.

The held profile additionally preloads every lane with 17 beats, one lane at a
time, and releases its sink. A 12-gap interior window must take exactly 12
receiving clocks even when the source clock is slower. This specifically checks
the local pipeline's II=1 capability; it is not substituted for the sustained
clock-ratio-dependent rates. Sufficiently supplied directions must also sustain
96 transfers per 96 receiving clocks in the simultaneous streaming scenario.

The old baseline receipt measured throughput but did not record exact blocked
capacity or empty-queue latency. A comparison reports those missing measurements
as such, without inventing numerical improvements. It explicitly records depth
4 to depth 16 and unchanged eight protocol owners. Logical payload RAM grows
from 2,076 to 8,304 bits across five lanes; capacity growth is a storage-depth
change, not credited as pipeline throughput improvement. This is not a
matched-depth area/performance comparison or a synthesis/resource result.

Raw bit-coverage and throughput streams intentionally exercise arbitrary beat
encodings. They are transport tests; the separate Acquire/GrantData/E phase
provides the owner-lifetime scenario.

## Component-scope exclusions and integration obligations

This boundary alone is not an independent-clock CPU tile. A full composition
must separately provide and verify:

- Ordered uncached request/reply crossing and the separate LineGrant crossing
- LR/SC reservation-clear events ordered with affected atomic requests
- Invalidation events with request/acknowledgment ownership
- Atomic 64-bit time snapshots and appropriate IRQ level synchronization
- A whole-system cold-reset contract covering every affected owner
- Complete tile quiescence, including cache/Home/DDR and uncached owners

These obligations are outside this component's acceptance, even if supplied by
another composition. No single-sided hot reset, clock gating, metastability,
Gray-bus timing/skew, physical CDC, synthesis, route, SoC boot or board
qualification is claimed. Retention/gating additionally requires stopping new
work, draining all owners while clocks and response/coherence traffic continue,
and establishing both endpoint transport-empty observations with appropriate
synchronization.
