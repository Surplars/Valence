Qualification: the actual cache component gate passed on frozen bc518ec. See docs/posted-store-cache-qualification.md and component-results.json for exact source, four models, 15 positive cases and six RTL-negative cases. Separate executing-CPU lineage and real-home gates have now passed at their own frozen sources; see docs/posted-store-delivery-review.md for their limits. The combined delivery source has not run hardware checks.

# Actual-cache integration, first source freeze

Initial-checkpoint status: SOURCE_ONLY_RUN_READY. That historical checkpoint
made no Scala, GSIM or cache correctness claim; the qualification above is the later result. The previously qualified standalone owner source
and results remain separate. This fixture uses the actual private cache,
original acquire engine and original tag/data SRAMs with a synthetic external
TileLink manager and explicitly supplied CPU proof premises. A real home and
executing CPU require later separate qualification.

The frozen gate runs config/OFF pruning/physical SRAM write-port checks,
OFF/ON generation64 WB2 models, an independent tiny-generation2 model and an
ON WB1 model. Every top-level driven/observed value is scalar and at most 64
bits. Three mechanical transport tests use a C++ stub, never an RTL model.
The manager records complete raw cycles, samples backing bytes at actual
Grant ownership, obeys non-interleaved D bursts, holds A/C/E/CPU responses,
and verifies actual load and C-probe/Release bytes against authored byte intent.
Full backing memory is checked after actual flush. Full owner/token/WB event
lineage is additionally checked with the independently authored owner oracle.

The source-authored ON WB2 schedules cover five stores reusing two response
tickets before first refill, two owners with younger refill first and oldest
installation, a credit-held third store becoming a legacy hit after install,
real synthetic B/C probes before A and after E/installation/held ACK, explicit
pre-A/post-probe DMA changes, clean/dirty victim C-last overlap with retained
ReleaseAck responsibility, pre-capture victim cancellation, flush while live,
and continuing/closing epochs. Five expected real RTL assertion cases cover
fatal post-ACK error/permission violations, changed held proof/context and an
invalid episode close. The separate generation2 case exercises real legacy
fallback; the WB1 model starts with a bounded merge/read/flush schedule.
These are synthetic transport schedules, not a claim that a specific home
would originate every schedule. CPU authority, recoverable Sv39 fault behavior,
CPU throughput and synthesis resources remain outside this gate.

Source the pinned recovery activation script, obtain a heavy slot, then run:

    python3 simulator/gsim/posted_cache_rebuild/run_component.py --slot-granted --output NEW_ATTEMPT_DIRECTORY

The runner requires clean committed input, validates exact installed tools,
never rebuilds tools, and preserves each attempt with raw logs/model artifacts.
It uses a 200 MiB attempt budget and 700 MiB free-space floor, ASan/UBSan,
bounded per-step timeouts and source stability checks. No input is edited
while its bound run is active. The initial owner retention and metadata costs
are intentionally preserved; no historical speedup or resource count applies.

Attempt 0e6f03e reached all eleven positive ON WB2 cases after passing OFF and
config checks, then correctly asserted a changed held epoch. The fixture
expected only the separate held-context assertion, while the generated model
evaluated the original-proof/current-epoch assertion first. Preserve that FAIL
receipt. The next host-only correction accepts only the two exact source
guards for that same violation (likewise the two exact episode-close guards),
still requires abnormal native exit, rejects sanitizer failures, and writes
per-case progress. No production/model input changes accompany this correction.

The first integrated source had a real exhaustion-fallback gap: a legacy dirty
miss could return its CPU response after C-last but before the old ReleaseAck.
The owner fallbackPending bit then cleared despite that WB responsibility. A
new generation2 raw-manager schedule rejected the exact old compiled model at
cycle 266: actual cache busy was zero, owner busy was legitimately zero, but
the independently accepted Release source 2 still had no Ack. The preserved
control receipt binds the old binary/FIR/CPP/header/object/driver hashes.

The correction adds fallbackDrainActive/epoch only when the optional feature
is ON. Actual fallback.fire captures it. It clears conservatively only after
all already accepted cache response/MSHR/WB/eviction/bypass/engine/probe work
drains, including any actual probe.fire on the proposed clear edge. It is not
a per-owner WB reclamation optimization and does not infer old ownership from
a reused slot. New admission is blocked throughout, so the preceding episode
cannot be replaced before its real ReleaseAck. Raw unaccepted request/probe/
flush valid and episodeActive are excluded from the clearing predicate. The
cache busy, context assertion and episode-close assertion include this tail.

The extended gen2 gate holds that dirty ReleaseAck after the CPU response,
services a real probe, holds the next proof behind the tail, requests flush,
accepts another probe on the old drain edge, then verifies progress after the
real Ack and exact backing bytes. A context mutation during the WB tail must
hit its exact RTL guard. This correction requires a new source/model binding;
earlier partial gates and the interrupted executor exit 130 are not PASS.
