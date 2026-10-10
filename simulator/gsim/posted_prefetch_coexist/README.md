# Posted-store / next-line-prefetch coexistence candidate

Status: SOURCE_ONLY_RUN_READY. Host oracle/transport checks are separate from
hardware qualification. No existing `component-results.json`, old binary, or
historical PASS is imported. The original cache/home fixtures remain untouched.

`PostedPrefetchCoexistGsim` instantiates the actual private cache, acquire engine,
tag/data SRAM and posted owner in both policy configurations. Its switch is only
`concurrency.postedPrefetchCoexistence`; next-line read/store prediction, two
MSHRs, two response entries and two writeback slots remain the same. All scalar
bindings are at most 64 bits. The full `CheckedStorePrefetchObservation` is bored
from the cache; public `io.prefetch` events are observed separately.

The policy OFF/ON matrix uses generation64 and generation2, WB2. Every scenario
starts a fresh generated model. Both generation64 policies rerun eleven original
cache schedules and five exact RTL-negative controls on the new binding. They
then run ten new coexistence schedules:

- Actual proof-bearing legacy resident stores with partial bytes and a retained
  empty cohort: ON makes a store candidate, OFF suppresses it. The original full
  owner/root and actual final backing bytes remain independently checked.
- Actual accepted sequential reads inside a retained empty cohort: ON allocates
  and serves demand from the next line, OFF preserves historical suppression.
- A prior read candidate meeting a held new-owner proof. Its pre-edge busy state
  must block posted admission while the offer cancels PF allocation; the exact
  unchanged token later makes progress.
- Matching request/proof payload with an ineligible `headAuthorized=0`, held by
  two actual occupied response credits. Even this resident write cancels the
  prior candidate and cannot gain posted authorization.
- PF A held, then all eight GrantData beats with E held, an invalidating probe,
  and a held new-owner request. Probe and new posted admission wait for the
  actual PF installation/drain.
- Store-origin PF with a real dirty victim; its ReleaseAck remains held after
  PF MSHR release. A victim probe and new posted owner remain blocked until that
  exact saved release source retires.
- Live PF with held E plus two held CPU responses and a third proof-bearing
  resident store. PF refill consumes no CPU response credit; the original held
  store later completes with its own response and bytes.
- A seal before a younger partial same-line store. The younger original offer
  remains held until the old owner installs and it can take the legacy-hit path.
- Seal/flush/drain/endEpisode/context change with an active candidate or PF and
  retained cohort, followed by a new full root and epoch. These are cache-side
  prerequisites for FENCE/context/recovery only, not executing-CPU coverage.
- Failed speculative PF: no SRAM install, CPU response or posted event is
  invented. A later denied demand returns exactly its own precise error, and a
  subsequent successful demand verifies the independent original bytes.

Both generation2 policies rerun exhaustion/fallback and dirty fallback tail
coverage, including the exact context-change-before-ReleaseAck assertion. They
also create a read candidate before an exhausted dirty fallback and verify
cancellation, actual fallback ACK/ReleaseAck-tail retention and later progress.
The ON model adds the new guard case: an exhausted proof-bearing resident hit
is offered after a read PF's MSHR retires but while its clean ReleaseAck is held.
It waits through the real ReleaseAck edge, then fires fallback once, preserves
its held original CPU response, and reclaims the final tail. The unchanged OFF
path is not claimed to support that newly guarded overlap.

## Oracles and scope

`cache_base.py` is a source copy of the original cache adapter with local import handling,
lossless compressed trace storage and independent final-image evidence added. It uses the independently authored posted contract for
full CPU token, owner generation, cohort root, epoch, reservation, WB ticket,
response ticket and final byte conservation. New requests use tags above 2^63.
The synthetic TL manager checks every actual load, ProbeAckData and ReleaseData
against separately authored byte intent. Actual flush must reproduce the entire
4096-byte backing image; no expected memory comes from an observed PASS pulse.

`pf_oracle.py` separately tracks the authored next-line address, original
read/store origin, exact MSHR source, all eight Grant beats and E, and captured
WB source until C-last plus the exact ReleaseAck. It compares the public PF
counts and busy state to those independently retained obligations, including
WB ownership after MSHR reuse. It rejects mixed posted/PF ownership, speculative
CPU responses, a failed PF SRAM write, and new posted/ON fallback admission
across pre-edge PF work. The original byte oracle independently checks PF
installation against coherent authored memory as well as its exact Grant bytes.

The manager and successful CPU authority premises are explicitly synthetic.
These tests establish neither real-home reachability nor CPU proof provenance,
SV39 fault/recovery execution, FENCE execution, board throughput, FPGA timing,
or a production enablement decision. Original permission, credit, response,
seal and post-ACK fatal-error controls remain active.

## Running

Host-only checks (including a tiny scalar C++ ABI stub, never a GSIM model):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s simulator/gsim/posted_prefetch_coexist -p 'test_*.py' -v

After an explicit serial heavy slot is granted, freeze and commit the source,
activate the recovered pinned toolchain, then use a fresh output directory
outside the checkout:

    python3 simulator/gsim/posted_prefetch_coexist/run_component.py --slot-granted --output NEW_ATTEMPT_DIRECTORY

The runner rejects a dirty/unfrozen checkout, binds all tracked source hashes,
HEAD/tree and the pinned tool manifest, builds only the new top, invokes
`ooo.PostedPrefetchCoexistConfigSpec`, runs ASan/UBSan native models, and records
complete per-cycle input/output gzip JSONL plus each case result. No raw cycle
is sampled or omitted. Closing each model decompresses the entire trace, checks
its contiguous cycle count, and records compressed/uncompressed SHA256 values.
Every positive case also saves separate 4096-byte authored expected and actual
backing images, with hashes, after actual flush and full-image equality. Semantic
negative cases retain their incomplete trace with no final-image success claim. Every new attempt
has a unique directory; failures are preserved. It uses serial compilation,
bounded step timeouts, a 200 MiB attempt budget and 700 MiB disk floor. No tool
rebuild, generic setup, whole GSIM suite, CPU/board run or synthesis is invoked.
