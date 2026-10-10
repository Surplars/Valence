# Canonical virtual-store overlap

This option lets a younger, independently prechecked load pass an older **actually accepted** virtual store only after the store has a registered certificate for its final physical bytes. The original store remains serial and retains its real response and precise fault. The certificate grants no posted-store authority, early acknowledgement, or memory credit.

Generic core/platform/export construction remains default OFF. The performance runner selects the v3 recommendation with canonical overlap ON; `--disable-canonical-store-overlap` selects its OFF control, while existing posted-store and posted-prefetch controls keep their own meanings. Explicit export experimentation uses `--canonical-virtual-store-overlap` with all prerequisites. The separate [official entry-point gate](evidence/official-entry-result.json) passed: both actual constructor profiles and raw native exports match their corresponding qualified development-emitter sides. Its source and receipt binding is distinct from the earlier CPU runtime evidence below; no new CPU runtime is claimed by that gate.

## Authorization and ordering boundary

The core requires virtual load precheck, buffered RAM stores, registered memory requests, registered addresses, registered translation heads, and at least two LSU owners. Existing VM/PMP and registered request/response prerequisites still apply. The adapter requires registered checked authorization; platform integration requires the coherent private-cache RAM path, core data translation, and staged memory fabric.

The request-synchronous sideband carries the full ROB token and epoch through the backend request queue, direct StoreBuffer path, translation ingress, walk hold, and translated queue. A checked enqueue may certify only a completed demand translation with final write permission, no fault, cacheable aligned RAM bytes, exact lanes, unchanged epoch, and full-width bounds. The tracker records the original VA and the independently checked PA; it never treats the prepared store VA as a PA.

Every older store remains a barrier unless its exact live certificate proves physical-byte disjointness. Fault, retirement, cancellation, recovery, and context invalidation dominate certificate capture. An unissued second older store still blocks. The younger load keeps its own positive precheck and final adapter recheck. VM/PMP/SFENCE changes must drain accepted stores and adapter work; proof disposal cannot cancel irrevocable requests or leave credits outstanding.

## Qualified source identities

The 11 production files are frozen at `aaaf6d701a3b47cb610b6b8b4775487b89b7a5b9`, tree `c0b056442ae92a5083eedc0709128b431567f993`. [production-freeze-r1.sha256](evidence/production-freeze-r1.sha256) preserves every exact hash. They matched this integration worktree when this evidence was assembled.

The qualification source sets are deliberately distinct:

- Failed initial configuration fixture: `8eeab5a4c25d3aa7eb39b166fbd70de366861623`
- Passing component/configuration fixtures: `d8429b12de27a50f37350aa168bfbddebf939ea9`
- Passing matched backend models: `8665c3f78d88ced517fd70b1fe1380e32986a713`
- Host-only backend replay: `6e53dda283ddf611d79ed4b16eba292340a7fa2a`
- Actual board CPU and native development emitters: `6f975c14edd0ce01cc248b71893d85634fedf408`

[source-identities.json](evidence/source-identities.json) binds the original receipts, fixtures, model/runtime pins, independent guest, tool receipt, and the copied integration fixture bytes. Component/backend fixture hashes were also checked against the exact Git objects at their receipt commits. The backend replay's host changed while both DUT models stayed immutable. No previous candidate's runtime result is inherited.

## Component and backend results

The selected component gate passed six configuration tests, a 14,338-tick tracker run with 24 captures and 14,131 independent byte-interval comparisons, the real adapter/Sv39 fixture with 90 accepted/returned requests, and both two-owner and four-owner LSU fixtures. Each LSU witnessed four overlapping younger starts and two canceled owners. All four deliberate tracker/adapter/LSU oracle corruptions exited nonzero with the expected failure. The separate forced-undrained-flush run exited with SIGABRT and the actual production drain assertion. Compact terminal receipt extracts and original logs are in [evidence](evidence/manifest.json).

The backend fixture uses real IntegerBackend, StoreBuffer, DataTranslationAdapter, and Sv39 service with an ordered physical-response stub (`realCache=false`). It has four LSU owners, two StoreBuffer entries, 16 ROB entries, 48 physical registers, 64-bit token tags, PMP16/Sv39, registered load forwarding, and virtual load precheck. Its two full 136-field core parameter reports differ only in the canonical option. It does not have the recommended board's cache/posted-store composition.

All 23 cases have identical independent architectural trace, retired count, and trap count in OFF, ON, and the host-only replay. [backend-case-comparison.json](evidence/backend-case-comparison.json) was reparsed from all four actual logs. In the positive case, younger load `12:12` starts at 310, reaches upstream acceptance at 311 and the physical boundary at 314, before store `11:11` responds at 449; OFF has no such overlap. Different VAs mapping to identical physical bytes stay blocked. A second unissued older store stays a barrier until its own checked ownership exists.

The late-store-error case retains original store `11:11`, StoreAccessFault cause 7, and original VA/tval `0x40000000`. The replay explicitly records younger `12:12` and dependent `13:13` retired zero times, final outstanding owners zero, and all accepted upstream/physical requests returned: OFF 1/1 and ON 2/2. Both architectural-result and forbidden-younger-retirement corruptions failed on both sides. The late overlapping load-error case also retains its precise fault and drain. Do not use the inherited `unresolved_store_stall` bucket as a causal alias/uncanonical/unissued-store decomposition.

## Actual CPU measurements

All six singleton executions passed with the original guest, full byte/result checks, fault/CSR/drain/AXI checks, and a deliberately poisoned-trap negative control. [cpu-case-summary.json](evidence/cpu-case-summary.json) points to the exact terminal receipts. Every artifact recorded by those receipts, including the large original event traces, was rehashed locally before assembling this directory.

| Actual case | OFF ROI cycles | ON ROI cycles | OFF drain tail | ON drain tail |
| --- | ---: | ---: | ---: | ---: |
| 21, Sv39 COPY | 497,144 | 431,622 | 5,584 | 5,580 |
| 19, Bare COPY | 365,235 | 365,235 | 5,618 | 5,618 |
| 0, warm READ | 16,530 | 16,530 | 0 | 0 |

Warm READ's checksum is `6863348401280905216` on both sides. Sv39 COPY saves 65,522 measured ROI cycles (13.1797% fewer; 1.1518x OFF/ON cycle ratio). Drain tails are separate and are not included in that speedup.

The exact case21 ROI observer records 16,351 ON younger-load start-overlap tokens and 202 upstream-overlap tokens; physical/cache acceptance overlap remains zero, and zero tokens overlap at all three boundaries. Both sides classify 16,351 store hits and 33 store misses. The observed load/cache relationships include loads after the parent miss barrier, not during it. Event counts and occupancy durations use explicitly different offer/accepted clocks and must not be added together as saved cycles. The full matched causal report is preserved at [causal.json](evidence/originals/cpu-case21/causal.json).

These measurements establish a shorter checked-store-to-next-load handoff in this workload. They do not establish simultaneous consecutive COPY read misses across an unissued intervening store. Cache store-miss fencing and DDR write/read ordering still constrain overlap.

## Native state and OFF comparison

The development-emitter native exports have reachable literal storage totals:

| Export | Scalar register bits | Array register bits |
| --- | ---: | ---: |
| OFF and published baseline | 91,947 | 708,155 |
| ON | 92,636 | 709,879 |
| ON minus OFF | +689 | +1,724 |

The total increase is 2,413 literal bits. These are declarations after native CIRCT lowering, not mapped flip-flops, LUTs, BRAMs, PPA, or STA. Fixed memory groups and external paths compare equal in the saved census.

The OFF export has 269 compared files: 268 are raw-byte identical to the published baseline. `IntegerBackend.sv` differs only by the exact internal identifier substitution `_physicalStoreConflict_T_203` → `_physicalStoreConflict_T_171` (one declaration, 16 references). Raw whole-export equality is false. The original checker rejects width, logic, and identifier-collision mutations; a separate independent audit rejects width, logic, and extra-net mutations. Both receipts are preserved. This is an exact single-name check, not broad normalization or formal equivalence.

The [profile correspondence](evidence/originals/native/profile-correspondence.json) proves the development native profile's full published-baseline projection. The subsequent [official entry-point/native gate](evidence/official-entry-result.json) also passed: all 27 entry-profile and 136 core fields agree with the corresponding qualified CPU/native side, including six actual core, three cache, two DDR, and two cache-TileLink instances. Official OFF matches all 269 donor files and official ON all 272 donor files byte for byte, with no identifier normalization; FIR correspondence removes source locators only. These official-to-donor comparisons are separate from the older donor-OFF-to-published-baseline single-wire-name comparison above. The focused integration Scala gate passed all 46 tests.

## Preserved failures

The first component attempt compiled production/test Scala but its new configuration fixture omitted the existing translation-head dependencies: four of five tests failed. Its remaining constructor rejection is not counted as the intended integration test. The subsequent fixture used the legal staged profile and checked exact rejection messages; production guards and the 11 frozen files stayed unchanged.

CPU host preflight r5 also failed to compile because newly used cache/barrier observer fields were missing from its host `Store` record. The compiler log and failed receipt extract remain present. Host preflight r8 is the terminal host-only pass bound into the actual runtime pins; it is not itself DUT execution. Earlier preparation text marked case21 running and native work pending; the actual terminal receipts above supersede those status snapshots.

## Official public-entry reproduction

The [official_entry_gate.py](official_entry_gate.py) preflight binds the complete
public `performance.py` command expansion, immutable CPU/native references and
all source/audit inputs. `--emit --slot-granted` additionally emits the actual
production `FpgaNextSocTop` twice (v3 ON and independent v2 fallback OFF), audits
its instantiated parameters and compares raw lowered file sets. It builds no
GSIM model. The final host-only strengthening also checks every donor RTL hash
against the pinned native receipt before emission; the same independent check
was performed before the successful recorded emission.

```sh
python -B simulator/gsim/canonical_virtual_store/official_entry_gate.py \
  --output /absolute/fresh/official-entry \
  --native-reference /absolute/canonical-store-overlap-native-r1 \
  --cpu-reference /absolute/canonical-store-overlap-cpu-prep-r1 \
  --mill /absolute/verified/mill --firtool /absolute/verified/firtool \
  --emit --slot-granted
```

Remove the last two flags for a host-only source/reference preflight. A source
locator may change; any other FIR character or any raw RTL byte difference
fails. The gate's independent controls reject altered logic, instances, profile
fields and JSON types. A newly recorded preflight alone never substitutes for
the recorded actual parameter/emit result.

## Reproduction and archive boundary

[archive-index.json](evidence/archive-index.json) contains confirmed existing Library archive IDs, their recomputed local SHA256 values, and saved successful upload-receipt identities. The original component/backend archives carry exact complete receipts, source, and reusable models. CPU preparation r2 contains the source/model preparation checkpoint, not later CPU runtime results. The final compact and raw CPU result packages are also confirmed Library uploads; the raw package retains all large event sidecars. Native r2 contains its separate exports and analysis. No binaries, models, generated RTL, or large event traces are added to Git here.

Use the existing [run_components.py](run_components.py) in a clean frozen checkout with the pinned tool receipt and recovered toolchain activation. It requires an explicitly granted serial heavy slot and fresh output directory. Selected component/configuration reproduction:

```sh
python -B simulator/gsim/canonical_virtual_store/run_components.py \
  --output /absolute/fresh/components --tool-receipt /absolute/tool-receipt.json \
  --models tracker adapter lsu2 lsu4 --slot-granted
```

Matched backend reproduction uses the same runner with `--skip-config --models backendoff backendon`. [replay_backend_host.py](replay_backend_host.py) accepts `--models /absolute/qualified/backend-r1 --output /absolute/fresh/replay --tool-receipt /absolute/tool-receipt.json --slot-granted`; it verifies every original non-host input and model artifact. Run historical replay from the exact archived source checkout, because unrelated integration changes correctly fail its input checks.

The archived CPU flow is `model.py` (strict source/tool/model binding, then fresh OFF/ON model construction), `run.py preflight`, `run.py bind` with exact model receipt hashes, and `run.py run --pins ... --sha256 ... --side off|on --case 0|19|21 --out /absolute/fresh/case --slot-granted`. Its `verify` and `pair` actions inspect recorded singleton runs. Use the exact commands in the terminal receipts and fresh destinations; old prepared command text is not a new authorization to occupy the build/runtime slot. Source copies and the original guest must match their pins; no bootstrap-source reproducibility is claimed where that source was unavailable.

[cpu-observer-controls](evidence/cpu-observer-controls/source-provenance.json) preserves the final passive observer, trace parser, independent observer control, and direct local dependency as byte-identical sources. It is a compact audit/control subset; the full archive supplies the runtime host, model adapter, independent checks, and orchestration. Native reproduction likewise uses its archived frozen `run.py`/plan and pinned firtool export; there is no synthesis/STA step.

No mapped PPA, routed timing, physical-board execution, full Linux qualification, full regression, or broad workload win follows from these focused results. Final integration configuration/CLI and native correspondence are recorded by the separate [official gate receipt](evidence/official-entry-result.json); the CPU results remain bound to their original qualified runtime source.
