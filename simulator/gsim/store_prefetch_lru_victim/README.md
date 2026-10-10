# Store-origin prefetch LRU victim qualification

Current integration status: [opt-in source checkpoint](../../../docs/experiments/frontier-lru-opt-in.md). The preparation status below describes the original fixture checkpoint.

Status: prepared source and host oracle only; actual generated-header syntax,
ASan/UBSan native model runs and negative controls must pass before qualification.
No earlier actual-cache result is inherited.

The fixture uses actual `NonBlockingCoherentLineCache`, Mixed coherent home,
atomic/DMA boundary, TL engines and the original mixed AXI backing model. The
original `harness/coherent_cache_home.cpp` is included unchanged. The topology is
512 lines, two ways, two MSHRs, two response entries and two WB slots. Read/store
prediction and store-PF MRU insertion remain ON. Only `storePrefetchLruVictim`
differs. This standalone component has posted coexistence OFF; it is not the
complete CPU profile, an executing CPU, throughput qualification or board test.

The actual RAM aperture is 128 KiB at `0x1000080010000`. A line is 64 bytes and
the independently derived set-alias stride is 16 KiB. X, Y and P are distinct,
in-range full physical addresses at base+128 plus zero, one and two strides.
AXI uses the original 32-bit aperture offsets; no narrowed tag or hacked decoder
is used to manufacture a high-address witness.

The emitter constructs the top once and records all eleven fields from the
actual cache's `CoherentCacheConcurrency`, actual cache/home `CacheTagGeometry`,
actual valid/owned array lengths, actual tag-bank counts and actual home owner
array lengths in `actual-parameters.json`. This reflection creates no hardware.

## Independent expected state and bytes

`policy_oracle.h` imports no production hardware helpers. It uses full physical
addresses, real accepted ordinary accesses, exact victim capture, successful
refills and actual invalidating probes to maintain valid/dirty residency and
conventional two-way access order. PF allocations save an independent expected
way/slot/victim in their host generation. Failed fills do not install or touch
LRU. Store PF insertion is MRU and read PF insertion remains oldest.

Pending-candidate snapshots compare the actual replacement bit, origin, both
valid/dirty/full-PA ways, selected way/slot/full PA, and captured allocation.
WB capture and refill/installation must preserve the independently chosen slot.
All payload reads are guarded by their actual owning events. Full-width scalar
getters are explicitly cast before text output, including one-bit observations.

The inherited independent byte/mask, CPU/DMA FIFO, held response, A/D/E, complete
C burst, immutable WB generation, late exact ReleaseAck, real AXI fault and
full cache/home flush checks remain active. Every successful case saves separate
131072-byte authored expected and actual backing images, with all byte lanes
serialized explicitly. Both policies must have identical expected and actual
images for every identically authored case.

## Runtime matrix

The four prior scenarios remain: cold-candidate/credit pressure; dirty PF with
held C, late Ack and a reused MSHR/direct-demand ABA; 1024-line dirty steady
stream; actual AXI SLVERR with failed PF, precise DataPort store error and retry.
Full WB occupancy is required during the retained original ABA schedule.

Twelve additional scenarios cover dirty-LRU/clean-MRU discrimination and its
mirror, both invalid, each single invalid way, both clean with both LRU values,
both dirty with both LRU values, unchanged read-origin clean-first selection,
blocked both-dirty read PF, and a failed PF after selected victim release.

The main case fills dirty D in way 0, then completes a real ordinary C demand
into clean way 1. No extra source touch is used. Real sequential store history
creates P. OFF captures clean C and the first of seven later C words reloads;
ON captures dirty D, sends all eight real C beats and all seven C words hit.
Both modes hold the first C offer and dirty middle beats, then hold the exact
ReleaseAck after the PF MSHR retires. The both-dirty companion requests real DMA
while C is held so the actual home creates a matching probe; B cannot pass the
saved release owner before its Ack. The real-home maintenance barrier is allowed
to delay PF refill in this probe case.

Four further schedules cancel a genuinely pending candidate with a target
read, same-set store, foreign read miss or actual flush. No internal state,
permission override, synthetic manager or changed guest is used.

One-way behavior currently has only a separately labeled host-oracle control.
No one-way actual-model or probe-before-capture qualification is claimed here.

## Running and closure

The coordinator generates OFF/ON models from an immutable Scala freeze. Then,
after a serial heavy slot is granted and these host files are committed:

    python3 simulator/gsim/store_prefetch_lru_victim/run.py \
      --slot-granted --generated GENERATED_GATE_DIRECTORY \
      --tool-files TOOL_RECEIPT --output NEW_RUNTIME_DIRECTORY

The runner requires the generated gate's completed status, exact all-Scala,
resources/build source hashes, exact tool receipt and hashes, generated artifact
hashes, and actual constructor records. It first syntax-checks against each real
generated header, then compiles serially with ASan/UBSan and runs all 20 cases.
A runtime receipt retains every command/log/hash, raw source closure and complete
backing images. A failed attempt stays intact. Exact previously compiled model
objects may be reused with `--reuse-objects-from RECEIPT` only when generated
sources, tool hashes and model compilation flags match; the driver is relinked.

Each mode separately runs five required failing controls:

- `--inject-mismatch`: original independent CPU byte mismatch
- `--inject-wb-prefetch-aba`: real direct-demand/stale-PF capture changes origin
- `--inject-policy-lru-bit`: flips the actual allocating candidate's observed LRU bit
- `--inject-policy-origin`: flips that allocating candidate's observed origin
- `--inject-policy-full-pa`: flips bit 40 of an actual valid candidate-way address

These are host-observation mutations at real DUT events, not faulty RTL runs.
Each must fail at its exact independent diagnostic; each semantic mutation must
emit its actual trigger, and none may emit the terminal positive marker.
