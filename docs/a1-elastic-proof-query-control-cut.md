# Elastic load-proof query-control cut

Status: unified compilation, nine focused configuration tests, the updated tiny module and four
fresh actual-CPU guest executions passed. All original CPU metric fields and 544 load-owner trace
rows are unchanged. No frequency, resource, routed timing, board or DDR qualification is implied.
The saved `6c2bf82ff1b26132dbc774a95f9d531648903e4c` CPU evidence and SV export remain unchanged.

## Exact scope

The existing default-off `elasticLoadProofSupply` profile is unchanged. No new feature flag,
register, queue slot, TLB port, issue width or memory credit is introduced. The sole functional
edit removes `!descriptorInconsistent` from the registered-D query selector in
`ElasticVirtualRamLoadPreparation`. All inconsistency detection, current-owner matching,
selected-next-owner cancellation and lookup/PMP register boundaries remain.

The previous expression allowed the live second-rank VA to affect `descriptorInconsistent`,
which selected the current/D query mux. Consequently, an already registered D payload did not
fully isolate the existing rank-two PRF/AGU from the query mux and DTLB lookup. This edit removes
that particular combinational dependency. It does not remove the current/D 64-bit query mux,
full-key comparisons, indexed owner checks or lookahead-to-next-valid cancellation paths.
Physical timing benefit is an unmeasured hypothesis, not an Fmax result.

The existing backend dispatch-reservation bound receives the stable diagnostic text
`dispatch reservations must not exceed issue width`. Its arithmetic, predicate, clock and
assertion enable are unchanged. A disabled-control comparison may accept only the precisely
reviewed complete old/new diagnostic substitution, not broad string or assertion normalization.

## Revised conflict contract

An inconsistent live lookahead may allow one query of the **old registered D snapshot**. This is
not acceptance of the inconsistent lookahead as a new owner. `descriptorBad` still contains the
conflict, and `cancelled(next)` compares the complete token against every selected next owner.
Thus the queried D's next D/T/R copies must all be invalid at the edge; no valid translated or
permission proof may later emerge from that query. A new assertion checks precisely these
same-token next-state copies and does not reject an unrelated valid owner.

For example, bad D owner A may be queried while old T owner B advances into R. The new T copy of A
must be discarded while B remains valid. Conversely, a bad old T owner B must not survive its
advance, but it must not kill a different good D owner A replacing T. Existing R publication is
not combinationally withdrawn merely because a live lookahead is inconsistent; the discarded
query guarantee must not be confused with revoking an unrelated current R proof.

Current-owner VA/size conflicts still block direct retry. Raw D/R occupancy still determines
credit: no issue, negative expiry, conflict cleanup or D transfer creates same-edge refill
credit. Flush/unstable contexts still suppress query offers. Response-epoch checking and exact
issued-token cancellation still cover incoming as well as retained owners.

`SvTranslationService.lookup` and `loadPeek` only read existing TLB entries and reconstruct the
physical address. Peek does not start the walker, update a replacement/LRU state, refill a TLB,
probe the optional miss cache or create a demand-response owner. Those actions are driven by
demand requests and walker completion. This is a source-level dependency finding; the standalone
tiny fixture injects lookup responses and cannot independently prove integration side effects.
The extra conflicting query can cause combinational switching and observation-count changes.

## Focused validation contract

The updated independent tiny oracle must allow the disposable D-conflict peek without weakening
the full-token cancellation or byte-level PMP oracle. It covers hit, miss, stale response epoch,
coincident issue, bad-D/good-T advancement and good-D/bad-T replacement. Current-key conflicts
remain rejected. The existing 48-owner ideal trace must still issue exactly 48 distinct queries
and 48 owners with a steady interval of two cycles. No one-load-per-cycle claim is made.

The actual CPU comparison uses one newly generated DUT and the two unchanged saved hosts for
four original guests. All ordinary-traffic metrics, proof observations, stage histograms and
traffic fields must match the prior elastic revision exactly. Old PASS receipts do not certify
the modified source. Initial evidence locations are:

- `build/elastic-proof-control-cut-20261024-r1/`
- `build/gsim/elastic-proof-control-cut-component-20261024-r1/`
- `build/gsim/elastic-proof-control-cut-cpu-20261024-r1/`

## Results and evidence identity

One unified Scala compilation and all nine focused configuration tests passed. The standalone
production-module test passed in 770 cycles with 203 accepted queries. Its unchanged ideal-supply
case issued 48 unique queries and 48 owners, with 47 steady gaps of two cycles. New directed
coverage observed four discarded D hits, two discarded misses, two stale-response offers and
three coincident issued-token cancellations. Both distinct-owner transfer cases occurred once.
All 59 byte-level PMP cases and the existing cancellation, raw-credit and epoch checks remained.
Three sampled-observation negative controls were newly executed and precisely rejected; these
are oracle checks, not RTL mutants.

Component receipt:
`build/gsim/elastic-proof-control-cut-component-20261024-r1/receipt.json`, SHA-256
`900bb97c30689d5a1ff4b6de5f8936f1b60558adf72ba89c8ced8203f1996806`.

The one fresh actual-tile DUT was linked to the two unchanged hosts and executed the four original
guests. Comparison was against sealed historical results, without rerunning an old DUT:

| Guest | Previous work / ROI cycles | New work / ROI cycles |
| --- | ---: | ---: |
| VM stream, 233 retirements | 681 / 513 | 681 / 513 |
| VM dependency, 233 retirements | 1018 / 850 | 1018 / 850 |
| Independent hot loads | 1253 / 531 | 1253 / 531 |
| Delayed cold loads | 906 / 360 | 906 / 360 |

All nine comparison groups were exactly equal: CPU cases, translation stages, forwarding,
checked-flow metrics, prepared-store metrics, per-owner latency records, latency summaries,
load-case metrics and proof metrics. The separate 544-line load-owner trace was also identical.
This includes traffic, service and local latency histograms, not just total cycle counts. Each VM
case retains 48 real completed-store forwards and 49 actual store requests/replies/completions.
The hot/cold guests retain their prior genuine hit/miss, occupancy and whole-line service bounds.
The immutable CPU hosts' earlier negative-control evidence is referenced only; no CPU negative
was rerun or counted as new coverage in this patch.

CPU receipt:
`build/gsim/elastic-proof-control-cut-cpu-20261024-r2/receipt.json`, SHA-256
`b0eb81853983dbedf468a350cfd8b9cf171457bf19ba83cdce9dc60405e09150`.

The first CPU attempt correctly failed the disabled-control FIR gate before building a candidate:
source-annotation removal still left exactly one diagnostic difference, from
`Assertion failed at IntegerBackend.scala:3520` to
`Assertion failed: dispatch reservations must not exceed issue width`. The same predicate,
clock, `_T_1330`, `_T_1332` and assertion label were independently reviewed. Only that complete
diagnostic string, occurring exactly once, was approved for substitution. After it, the two
source-normalized control FIRs have SHA-256
`2cb0c84a5a3d3923397810334432876a59118fb3231832c04eabdde242017601` and an empty diff.
Neither raw FIR nor source-only normalization was equal. This gate applies only to the
**disabled-elastic control**, not equivalence of the intentionally changed active module.

The original failed receipt and diff remain under
`build/gsim/elastic-proof-control-cut-cpu-20261024-r1/`; receipt SHA-256 is
`74e2a3eb1f69cbe6d8894f1bf378f8d635474e9bfeff17e95c8a9216aa916a58`.
The second attempt reused only that control elaboration with pinned hashes, then freshly
generated and compiled the candidate. Historical source leaves changed by this approved patch
were checked against their exact bytes in the sealed old input archive rather than against the
new working-tree bytes. All remaining old artifacts, immutable hosts and tool identities were
checked directly. Source/tool drift checks passed.

## Interpretation and remaining physical risk

This patch removes an unnecessary combinational control dependency while preserving the measured
ordinary-traffic behavior. It demonstrates **no cycle-speed improvement** and supplies no measured
STA or PPA improvement. The same 167 additional descriptor bits from the original elastic design
remain; this patch adds no state. Lookahead VA/token/size still reaches inconsistency detection,
selected-next-owner cancellation and valid-register inputs. The current/D query mux, full-key
comparisons and owner-liveness fanout remain. In the overall profile, raw demand TLB hit to
PMP/epoch/shape to checked-register logic also remains combinational because the separate M2
registered-translation option is not enabled. None of these paths is declared to meet 300 MHz.

No production or firmware changes beyond the two explicitly described Scala edits are included.
The previous BootROM M/Bare host-only comparison is separate evidence, not qualification of this
new revision. No old SV export or old PASS receipt was overwritten or relabeled as this revision.
