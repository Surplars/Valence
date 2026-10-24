# A1 M3: completed canonical store forwarding

Status: experimental; focused component and actual-CPU checks passed. Selected,
FullCandidate and FullR1 defaults are unchanged. No new timing, area, Fmax, 300 MHz,
board, shared-DDR bandwidth or ISA-completeness claim.

## Measured motivation, not a projected speedup

An observation-only host copy reused the published FullR1 CPU object and ran only
the two unchanged short VM guests. Original retirement, memory and final-register
oracles passed; all 108 reported CPU/stage metric fields exactly matched the
published run. The generated model, original host and historical receipt were
unchanged. Evidence is under `build/gsim/m3-hot-store-analysis-20261024-r1/`
(`manifest.json`, `trace.log`, `analysis.json`). The model's source identity remains
that of the original M2/R1 receipt, not the later repository HEAD.

For all 48 warm stores in each guest:

| Boundary | Cycles |
| --- | ---: |
| Adapter upstream acceptance to DTLB request | 1 |
| Warm DTLB request/hit to checked descriptor | 0 |
| Checked descriptor to physical request | 1 |
| Physical request to actual physical reply | 1 |
| Physical reply to store retirement | 2 |
| Upstream acceptance to store retirement | 5 |

Consecutive warm-store admissions are 17 cycles apart in `vm_store_stream` and
20 in `vm_dependency`. The next same-address load is admitted two cycles after
store retirement and retires eight cycles after it. During the measured warm
windows the fetch packet reservoir is never empty; ROB occupancy is 14–16 or
15–16. Only the cold line requires an external line acquisition. These workloads
therefore expose CPU ordering/preparation/dependency latency, not a measured
shared-DDR throughput limit. The stream still contains a same-address load after
each store; its name does not imply an independent-store II benchmark.

The successful-done forwarding window could avoid some of that load round trip.
The observed eight-cycle store-to-load retirement gap is only a motivation and
an upper bound on a possible local saving, not a candidate speedup measurement.

## Narrow production contract

`completedCanonicalStoreForwarding` defaults to false. The explicit
`full-r1-m3` profile differs from `full-r1` only in that flag. The flag requires
ordered dual-owner completion, strict virtual load preparation, the live
canonical head-store tracker, and the existing registered memory-address and load-replay boundaries.
It rejects pending-store proof, proof-frontier, tagged/posted ownership and the
registered canonical-event experiment. Legacy board construction rejects the
new flag rather than silently dropping it.

`CompletedCanonicalStoreForwarding` is a separate combinational predicate:
latency zero, initiation interval one, no request queue or additional MSHR/source
credit. It joins:

1. The existing selected LSU `done && store && !exception` source, after its
   actual response, with the live canonical certificate by full token, original
   VA and size. The source remains the protected current head store.
2. The strictly matching prepared load certificate: full load token, original
   VA/size, read permission, ordinary RAM/PBMT, stable current epoch and flush.
   The source write certificate does not substitute for load read permission.
3. Source-certificate epoch = load-proof epoch = current authorization epoch,
   naturally aligned complete RAM ranges, preserved page offsets, exact source
   byte mask and full PA byte coverage. Different VAs mapping to the same PA may
   qualify; equal VAs mapping to different PAs do not.
4. A strictly older source and no other pending older store. All existing
   system, interrupt, recovery, context, atomic and older-memory final admission
   gates remain in place.

The optional `MemoryOperation.canonicalForward` sidecar accompanies the existing
start payload and has no separate handshake. On actual acceptance the slot
asserts that its own old successful store completes in that same cycle, with
matching token, VA, size, saved epoch and shifted data. The forwarded load uses
the existing extraction/sign-extension logic and completes under its own token.
The store's actual response and precise retirement are unchanged.

ParallelLSU's ordinary-prechecked `!forward` exclusion is unchanged. Thus a held
store completion plus an empty slot does not grant forwarding credit. The new
load must replace the exact store slot through existing `completion.fire`
turnover. No completion-ready, completion-fire or tracker-invalidate signal is
fed back into the predicate's eligibility.

### Authorization boundary

Normal prechecked loads traverse the adapter's second PMP/epoch check. A
forwarded load does not. Its authorization instead requires the strict prepared
read certificate plus the still-protected current head-store owner, the existing
CSR/VM/PMP drain contract, current stable epoch and unchanged final admission
vetoes. This does **not** authorize arbitrary in-flight PMP/context mutation in a
standalone component environment.

### Structural cost

The new join adds full-token, VA/size, epoch and PA/mask comparisons to issue
qualification. It adds no pipeline edge, but this may lengthen a combinational
control path. The experiment-only proof sidecar enlarges the elaborated payload;
whether unused saved fields are removed is a lowered-structure/PPA question, not
a promised free implementation. No frequency conclusion follows from cycle
simulation. The default-false legacy equations and assertion branches are kept
explicitly for an independent normalized-FIR equivalence gate.

## Focused verification plan

- Predicate: independent per-byte oracle for all source/load B/H/W/D sizes and
  beat offsets; exact owner/generation, current epoch, permission/stability,
  malformed mask/range/offset, PA aliasing and pending-older-store rejection.
  Store source/certificate full-token matching is tested here. Load candidate to
  prepared-proof full-token matching remains a backend integration obligation;
  the helper has no second load-candidate token input. Its strict load-valid and
  permission inputs are premises, not a substitute PMP decoder or backend test.
- Actual four-slot ParallelLSU: real store request/reply, failed and page-fault
  replies, held completion with empty slots, exact same-slot turnover, signed
  and unsigned subword results, cancellation and reused ROB indices/full tags.
  Both two/four-slot parameter constructions receive focused elaboration checks.
- Negative controls must match their explicit injection marker and exact oracle
  or hardware-assertion diagnostic; a generic nonzero exit is insufficient.
- Actual CPU: reuse the original FullR1 baseline only if the new default-false
  wrapper FIR matches after source-location removal. Build one M3 candidate,
  retain the two original VM payloads/service/oracles, and add one short alias
  correctness guest. Count actual forwarded starts, same-slot completions,
  physical load reduction and all real store replies/retirements separately.
- Existing unrelated A2/P1/M2 matrices are reused, not rerun. Functional results
  and cycle deltas will be recorded below after the coordinated freeze/run.

## Results

Coordinated Scala compilation and five focused configuration/elaboration tests
passed. The two component models and four exact-marker negative controls passed
on the first attempt, without a production or fixture repair. Component receipt:
`build/gsim/m3-completed-forward-20261024-r1/receipt.json`, SHA-256
`8393e8d4f154f7b4c909914f9f54a511ae1a7272c09dabd5d8756b4d26543e34`.

- Predicate: 1,057 cases, 56 allowed, 1,001 denied; 54 allowed VA aliases.
- Actual four-slot LSU: 13 width/offset cases, 39 blocked held-completion offers
  with empty slots and 52 blocked offers before actual reply. Exact same-slot
  turnover and next-cycle load completion passed, with no added physical load
  request. Access-error/page-fault sources, cancellation and full-tag reuse also
  passed the independent owner/data ledger.
- Predicate result and sampled result-data corruptions were rejected by their
  exact independent-oracle diagnostics. Source high-tag and forwarded-data
  corruptions triggered the exact hardware source/epoch/byte assertion. A host
  fallback or unrelated nonzero exit does not qualify as a negative-control pass.

### Actual CPU result

The one new actual CommonA1 M3 tile model passed both unchanged VM guests and a
separate short VA-alias functional guest. CPU receipt:
`build/gsim/m3-common-cpu-20261024-r2/receipt.json`, SHA-256
`045aea52acdd12813b491d6327a7492aa38b83dba9c791001e7458461122d371`.
The independent retirement/data oracle, fixed memory service law and original
program bytes are retained. The final CPU comparison reuses the old baseline
results without regenerating or rerunning that model; the earlier host-only
diagnostic replay is documented above.

| Identical guest, 233 retired instructions | FullR1 | FullR1M3 | Change |
| --- | ---: | ---: | ---: |
| Store-stream work cycles | 1024 | 736 | −288 (−28.125%) |
| Store-stream ROI cycles | 856 | 568 | −288 |
| Dependency work cycles | 1173 | 1120 | −53 (−4.518%) |
| Dependency ROI cycles | 1005 | 952 | −53 |
| Store-stream physical load requests/replies | 57 | 9 | −48 |
| Dependency physical load requests/replies | 105 | 57 | −48 |
| Actual physical store requests/replies, each guest | 49 | 49 | unchanged |

Each matched guest has exactly 48 forwarded loads, 48 corresponding forwarded
retirements and 49 actual store completions. The CPU witness checks the prior
actual store reply, current certificate/stable epoch, full owner tokens,
same-slot store completion/new-load start, returned data and eventual retirement.
The separate alias guest retires 72 instructions in 316 work cycles and performs
8 genuine distinct-VA/same-PA forwards, 9 actual stores and 10 physical loads; it
has no preexisting matched performance control and is a correctness witness.
Two CPU observation-corruption negative controls fail with their exact markers,
independent-oracle diagnostics and exit code 1.

This improves effective CPU work per cycle in these two short workloads by
avoiding redundant **CPU-to-L1D internal load requests**. It is not a claim that
higher bus occupancy is always better. Both matched guests retain one cold data
line acquisition/grant/ack and 136 instruction-side requests/beats. External
traffic is unchanged, not a measured shared-DDR bandwidth increase. The two
workloads have the same 48 forwards but different cycle savings; the result must
not be generalized to a fixed saving per forwarded load or arbitrary programs.

### Default-false structural gate and preserved rejection

The first baseline gate rejected literal FIR comparison after removing ordinary
`@[source locators]`. Its receipt and raw diff remain at
`build/gsim/m3-common-cpu-20261024-r1/`; receipt SHA-256
`aa7f6981713b68e6f3da137480880f6a13bf56d549f382bc5d96e8b26e3dd7a3`.
There was no production repair. Independent inspection found exactly six
compiler-generated assertion diagnostic locations: five
`LoadStoreUnit.scala:315` → `:352`, and one
`IntegerBackend.scala:3406` → `:3454`. A separately approved gate normalizes only
these two exact strings with those exact occurrence counts, in addition to
ordinary source locators. Every other FIR byte then matches; normalized SHA-256
is `2a2d55cec4b41e1b40ff96111876e71df69fae3f4ecc3027551fd123a958c60c`
for both controls. Raw FIR equality is explicitly false. This evidence permits
reuse of the old FullR1 model, not a blanket allowance to discard assertion or
logic differences.

Source/tool hashes and all historical baseline artifacts remained unchanged
through the final checks. M3 remains an explicitly selected experiment; no
Selected/FullCandidate/FullR1 default changes, broad GSIM/Linux regressions,
new Vivado run, physical timing or board qualification are included.
