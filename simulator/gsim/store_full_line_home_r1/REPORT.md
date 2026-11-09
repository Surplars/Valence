# B0 permission-only Home protocol qualification

## Result

All scoped tests passed: five original ON/internal positives and three exact engine assertion negatives; five ON/standard-D positives; OFF/internal normal Block and exact disabled-Perm assertion; two additional ON/internal future-directory survival cases. Independent final receipt review is pending at report creation.

The isolated default-off Home option suppresses both read-dispatch paths for enabled AcquirePerm. Permission completion uses one standard D Grant plus E on either transport configuration. Normal AcquireBlock returns eight standard D data beats, or one 512-bit internal grant. The fixture uses the actual acquisition engine, Home and AXI bridge, with an independent byte memory and public-edge oracle.

## Additional-arm measurements

| Case | Standard cycles | Internal supplement cycles | Requests/E/results | AR / returned bytes | Dirty releases/B/ACK |
|---|---:|---:|---:|---:|---:|
| basic |64|—|2|1 / 64|0|
| denied shim |24|—|1|0 / 0|0|
| mixed held |46|—|2|1 / 64|0|
| future B late |229|215|5|2 / 128|2|
| future E late |231|217|5|2 / 128|2|

Standard grant-event counts are 9,1,9,19,19 respectively. Internal future cases each have five grant events. OFF normal Block takes43 fixture cycles with one internal grant, one AR and eight R beats. These are directed fixture cycle counts, not CPU throughput measurements.

Every permission target has a zero-read budget through drained completion, except the future target5120 which is explicitly checked at zero before a later intentional Block reacquire. After old B/ReleaseAck, the new target accepts a real eight-beat dirty release, independently pairs AW/W/B, and is reacquired with the exact written 512-bit payload. This witnesses DUT directory preservation and backing-memory bytes for both B-before-E and E-before-B schedules. The subsequent legitimate64-byte read is counted separately.

## Ownership and error scope

Request/source/sink/E/result conservation, held offers, complete512-bit data, AXI ID/address/length/last and dirty C-to-W-to-B conservation are checked independently. Completion never precedes E. Future grants remain blocked until C-last, while unrelated work progresses. ReleaseAck retains its existing strict priority when unlocked; continuous-release fairness is not established.

The denied shim changes only the engine's observed D outcome. Home still publishes its successful permission grant, so the separate Home directory oracle must retain that entry. This is an engine error-propagation test, not a Home-produced denial. Corrupt, wrong opcode and bad cap fail with exact engine assertion signatures; OFF Perm fails with the exact Home admission assertion. All expected negatives are sanitizer-clean.

## Resources and provenance

All models use fresh isolated objects from the same reviewed source and qualified50cb dependencies. Additional models have identical125-method public APIs; the common driver is freshly linked against each model. Last runtime allocation21,381,120 bytes, free2,327,207,936 bytes, below48MiB cap and above838,860,800-byte floor. Serial stage/run receipts retain sampled resource peaks, executable hashes, logs, stderr and exact command inputs.

Original ON/internal evidence is preserved in ON_INTERNAL_ARTIFACT_MANIFEST.json and REPORT_ON_INTERNAL.md. Additional results are arm-runs/{standard,off,supplement}/RESULTS.json and four mode receipts. B0_ARTIFACT_MANIFEST.json binds the complete current evidence before final packaging.

## Next gate and limits

B0 establishes Home/engine protocol behavior only. No actual cache installation, CPU/store-buffer progress, area/timing or application gain is claimed. B1_INTEGRATION_PLAN.md proposes an actual-cache fixture using provisionally selected qualified Stage A r1. Measured r2 mapping was worse (8187 LUT/6589 FF versus r1 7143/6589), so source register reduction is not a reason to select r2. No B1 implementation or production enablement is included.
