# Physical data-path ownership attribution, 2026-10-07

## Result and decision

**PASS: one observation-only board model and one bounded RV64IMC execution.**
Guest output, every existing frontend/backend counter, and the complete ordered
retired-PC stream are byte-identical to the prior accepted runs. The result stays
at **486605 guest ticks, 486606 inclusive ROI cycles, and 360528 retirements**.
This instrumentation implements no functional optimization and measures no new
speedup, FPGA timing/resource result, board score, or official CoreMark score.

The old **73669** owner-qualified downstream-unknown head cycles are now fully
located at observed boundaries. **70762 (96.05%)** are actual transfer or response
acceptance cycles. The remaining **2907** cycles are held at a known boundary;
router/cache service and the reason a physical response is not yet consumed
remain unknown. A known boundary is not a proven causal bottleneck.

| Matching head-owner observation | ROI cycles |
|---|---:|
| Translation ingress to translation/identity stage: actual transfer | 11166 |
| Translated queue to checked queue: actual transfer | 18193 |
| Checked queue to physical request: actual transfer | 19504 |
| Physical/virtual response into relocated return buffer: actual acceptance | 21899 |
| Physical request issued, ordered response not yet accepted | 2000 |
| Waiting behind an older translation response owner | 471 |
| Checked request held before physical acceptance | 394 |
| Behind an older checked request | 42 |
| **Total previously unknown** | **73669** |

The 70762 transfer/accept cycles are useful progress, not blocked cycles or
avoidable latency. The 2000 physical-response-pending cycles can include service,
ordering, or return backpressure. No cache-hit/miss, DDR, router or MMIO service
cause is inferred from global activity. The 2907 held cycles are 0.60% of ROI,
not a projected performance improvement. Original primary categories and their
priority are preserved in parallel; only the old downstream-unknown category is
refined. The new primary partition still sums to 486606 cycles.

## Selected younger-load capacity and serial exclusion

Across **all ROI cycles**, the exact selected-profile issue guards identify:

- 67275 cycles with an otherwise eligible selected younger load and no serial
  exclusion, ignoring only slot availability
- **19198 cycles denied only by physical LSU slot/replacement capacity**
- **48077 actual younger-load start handshakes**

The two latter counts happen to sum to the candidate count in this run. Capacity
opportunities are 3.95% of all ROI cycles and 28.54% of selected candidate cycles.
They overlap the primary partition and are not distinct instructions, lost
retirements, or a speedup bound. The probe observes the actual selected younger
load, not every unselected ready ROB load. Thus it establishes real selected-load
capacity pressure while leaving total all-candidate pressure unmeasured.

The wrapper duplicates the selected profile's exact reserveMemory predicate with
only issueAvailable removed, then includes the actual early-recovery and pending
exception gates. It also requires noOtherSerial and the parallel/othersIdle
condition before calling a denial capacity-only. Every nonreset sample checks the
duplicate against both production reserveMemory and start.valid when availability
is restored. Production reserveMemory is unchanged; generic profile-ready bits
are never used as an eligibility oracle. The duplicate is scoped by elaboration
requirements to registered memory preparation, early recovery gating and issue2.

All **10931** previously measured serial-exclusion head cycles are selected
**ordinary RAM stores**. Atomic, nonordinary/virtual and other rows have no samples.
The observer conservatively groups nonordinary or virtual accesses instead of
asserting an unproven MMIO classification; that limitation does not affect this
run's all-RAM-store result.

**Next candidate recommendation:** a separately authorized, bounded LSU-capacity
experiment is now evidence-supported. Compare end-to-end cycles and routed
frequency/resources while preserving ordered exceptions, cancelled-read draining,
store ordering and independent owner tests. The measurement does not establish
how many extra slots are useful or that a wider LSU will win. Ordinary RAM-store
serial admission is a second measured issue, but relaxing it requires separate
ordering/precise-exception proof. Do not optimize cache misses from this result or
remove register boundaries merely because their transfer counts are large.
No functional candidate was implemented in this pass.

## Ownership and conservation

Every accepted integer request carries the existing full 64-bit allocation tag
plus ROB index in an independent host ledger. Every DataRequest field is exported
losslessly as address, data and packed metadata; these are full fingerprints, not
hashes. Static scalar BoringUtils taps avoid wrapper-created dynamic vector reads.

The StoreBuffer has separate logical-response and persistent-write lineages.
Locally acknowledged writes retain their original token/fingerprint after ROB
retirement until their actual physical write response. Drain, flow-buffered,
flow-fast and direct physical arbitration are resolved from the actual handshake
class, never the current ROB head. Direct includes non-buffered writes/atomics and
MMIO as well as reads. Buffered forwarding reconstructs youngest matching bytes
and checks the observed LSU reply. Local acknowledgements, forwarded reads,
physical replies and held replies are separately validated.

Ownership is conserved through the registered virtual ingress, translation wait,
translated queue, checked queue, ordered response owners, physical outstanding
requests and relocated response buffer. Translation may change only authorized
request fields; nonvirtual identity translation must match byte-for-byte. Fault
placeholders remain ordered response owners and never enter physical outstanding
requests. The concatenated pipeline owner order must equal StoreBuffer physical
owner order; the nonfault response subsequence must equal physical outstanding
order. Reply data/error/pageFault are checked across adapter, return buffer,
StoreBuffer and LSU boundaries.

Old registered heads are captured before simultaneous mutations. Cancellation
never clears pending reads. Reset is the sole discard operation and each boundary
has explicit discard conservation. Integer versus FP/system mux source is exported,
counted and asserted; foreign traffic is not silently attributed to integer LSU.

The whole execution, including boot outside the ROI, checked:

- 1953690 nonreset samples and 4 reset samples
- 192584 FIFO enqueues/dequeues and original LSU responses
- **18313 buffered stores**, all physically accepted by flow-buffered arbitration
  and subsequently matched to physical responses
- **174130 direct physical requests/responses**
- **141 StoreBuffer-forwarded local reads**, separate from 668 LSU forwarded starts
  in the unchanged original observer
- 192443 translation-ingress, checked, physical and return-buffer transactions
- 18454 local logical acceptances/replies, including the 18313 writes and 141 reads
- 8029 simultaneous request-FIFO transfers; 7901 simultaneous return-buffer transfers
- 1587 cancelled-owner cycle observations retained until draining
- Zero foreign mux requests/responses/epochs; zero actual VM translation requests,
  translation fault placeholders, fast-store requests or delayed drain requests
- Every ledger empty at completion; no reset discarded a live request in this run

Zeros above are workload coverage limits. Identity translation, physical requests,
flow-buffered writes and local forwarding were exercised by this exact workload.
VM hits/waits/faults, fast writes, delayed draining and reset with pending requests
are covered by directed independent host scenarios, not by a claim that this
CoreMark execution exercised those hardware paths.

## Verification and pinned inputs

The new host suite passes ASan and UBSan with fatal sanitizer recovery disabled,
including **39 deliberate corruption rejections**. Directed cases cover all four
physical arbitration classes, same-cycle and delayed translation replies,
page/access/PMP fault placeholders, local immediate/held/forwarded replies,
retired-store versus reused ROB index, cancellation, simultaneous transfers,
reset at every boundary, and post-reset owner reuse. Negative cases corrupt full
tokens, two-owner order, request/reply payloads, routes, fault decisions and every
queue count. The three original backend corruption rejections also still pass.
The host fixture uses ledger state only for idle defaults; explicit expected-token,
expected-payload assertions and independently corrupted observations enforce the
directed scenarios. Leak detection uses the repository's existing detect_leaks=0;
address and undefined-behavior checking remain enabled.

Before execution, the driver verifies every prior r2 artifact hash and the complete
archived starting source manifest, including prior hardware/measurement source
fingerprints. It records current hardware sources, observer/host sources, imported
Python helpers, Mill definitions and environment script before/after the run.
All measured sources were immutable. Existing file changes are restricted to the
test wrapper, opt-in host observer and two elaboration-only references in
MappedMachineCore; no production datapath, control assignment, default or IO changes.

- Profile: staged-fetch-turnover, I-cache 32 lines / 2KiB / 2ways, issue2
- Board: RV64GC/FPU, 100MHz, UART 460800, DDR 2GiB, D-cache 2ways
- Registered load-issue forwarding: false
- Exact existing BIN: build/gsim/coremark-rvc-20261007/rv64imc/coremark_board.bin
- BIN SHA256: 05b9a01d74a03389433ef942fef7056827331be18a91e0795f6456cee51fdac5
- ROI: retired PCs 0x80200114 through 0x80200122 inclusive
- Retired-PC SHA256: 142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa

Receipt: `build/gsim/data-path-ownership-20261007-r1/receipt.json`.
Run command:

```sh
source scripts/cloud/env.sh
python3 simulator/gsim/data_path_ownership.py --out build/gsim/data-path-ownership-NEW_TAG
```

The model generated on its first attempt with standard `--threads=1`; no generator
workarounds or vendored changes were needed. One selected model was compiled and
one bounded CoreMark execution completed. No DDR/GC/NEMU rerun, full GSIM, Verilator,
Vivado, FPGA implementation, Linux simulation, push or frontend ZIP change occurred.

### Artifact hashes

- `board-model/BoardSocGsim.fir`: `abc365a03ec0d6ef31ba6b3aaac6bfaa71a9fabedfc6f8e58f9d9366d1cc1410`
- `board-model/BoardSocGsim0.cpp`: `5baa9933df0442b22967f2982e3d3934d8441c156cc123bd6f8d8e77ff425739`
- `board-model/BoardSocGsim0.o`: `1bbfc1962e4282ded9886e235e5bea5f1bcdb479815b919900f60f90a42bda6d`
- `board_coremark`: `170bb3fb71031903452dfa963c856e76359635055aef49a428b064ea2d774b76`
