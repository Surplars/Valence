# Read-progress transport evidence

This is an isolated, default-off source/test backup. It preserves seven source files and the executed queue, StoreBuffer, checked-translation and integer-LSU fixtures/drivers. It does not enable a production profile. Actual ROB-head minting, FP/frontier routing, full platform wiring and cache admission are outside these qualified component results and are not included as completed work.

The baseline is the exact historical 50cb source closure, not an arbitrary current checkout. Obtain the source-only archive at repository path `simulator/gsim/translated_response_empty_flow_r1/historical-qualified-source.tar.gz` from evidence commit `5614cb808b5475ce893e564e3b6f25e73cfb6b02`; SHA256 `9d9c10c2103d6b12651fa4dc155eeb0373eaa094cb8cf42a681d21c06c40754d`. Retain its license/notices. This package is an evidence subtree, not a patch to the repository's current CPU defaults.

The external DataRequest remains 184 bits (181 original bits plus 3 return-handle bits). “275” in historical profile filenames is not that bundle width. The optional queue record changes from 670 to 671 bits, and MemoryOperation has its own explicit optional field. Recompile all affected Scala callers; never mix changed constructor/bundle ABI with stale classes.

TESTED_SOURCE_BINDINGS.json gives relative source provenance and hashes. All copied Scala/C++/Python test files are byte-identical to the qualified source. prepare_layout.py is new packaging-only glue; it creates the old relative-path layout without rewriting test logic. Its dry-run/source-copy validation is separate from hardware qualification. A fresh packaged hardware rebuild has not been executed.

## Qualified outcomes

- Queue: all four enable/projected combinations passed. Each accepted 1,843 records, returned 1,839 and discarded 4 only under coordinated reset; 528 full stalls, 1,230 simultaneous transfers and 3,003 cycles. Normalized semantic digest 10163256423396587046 matched all four. Six observation mutations were rejected. Frozen-proof/read-qualification combinations and final projected record roundtrip were exercised.
- StoreBuffer: held qualified direct read under actual retained external posted ownership passed. Broader suite: 10 positives, 4 RTL assertion negatives, 4 observation negatives, including 60 handle/size/lane combinations. Original-versus-candidate default-OFF standalone SV was raw-byte identical, SHA256 d8e10d1e9b570da9fbd4d7dc032d862ce1d00c2a6fb6ca3c9bdd9a8273590e88.
- Checked adapter: permitted held physical ingress, denied-bare qualification filtering, actual translated PMP fault, and identity/spill/full-handle reuse passed. The denied-bare test is a synthetic upstream trust violation used to test the new filter; it does not claim a newly synthesized bare fault. Raw default-OFF SV equality is recorded with its exact hash in VERIFIED_OUTCOMES.json.
- Selected integer LSU: 44-cycle positive with 5 starts/requests/replies, 4 completions, 1 cancelled drain, 3 publications, 1 replacement, 9 qualified holds and 6 completion stalls. Five actual RTL assertion controls and five observation-oracle controls passed. This fixture supplies MemoryOperation and cancellation explicitly; it does not establish real ROB-head authority.

The source/output seals and exact corrected structural hashes are summarized in VERIFIED_OUTCOMES.json. Source/report claims are independently reviewed; no CPU speed, cache throughput, FPGA Fmax or whole-SoC area result is claimed here.

## Preserved failures and limits

The original queue fixture had stale profile/arity expectations and lacked the selected registered Home request boundary. Its fixture-only correction compared all named original fields before emission. A monitor suspected disappearing-file stat race retained the prior failed-receipt executable; a new binary was linked. A final reserve stop raised the queue cap from 32 to 36 MiB without changing hardware/tests. StoreBuffer canonical test premises were corrected to virtualized=true before broader execution. Backend fixture indexing needed a SourceInfo-only correction before small-LSU emission. LSU source/API checking was corrected to derive constant-getter widths from FIR declarations, rather than assuming storage members.

All actual runs used ASan/UBSan/no-recover, with leak detection disabled. Observation mutations are oracle sensitivity, not mutated RTL execution. Fatal DUT negatives record the exact pre-anchor/assertion and child SIGABRT; their final input has no returned JSON frame. Coordinated reset is distinct from recovery, which retains accepted external obligations. Full generation exhaustion and untested integration paths are not implied by these results.
