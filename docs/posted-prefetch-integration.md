# Posted/PF integration and scoped qualification

This source-only integration starts from the exact published dev tree
`f8d771eff0bb282fc0ea1d362f608873a349ced5` at
`f1f1519b42a43773df8d407aedb0c6e48bebacc0`. Its local recovered Git base is a
surrogate root, not remote history. All published paths, native/seal reports and
return-flow work are retained. All 194 production `src/main` blobs and modes are
identical to qualified candidate `6f1e8c4fb1064f6d4fdd0b5ccbc4d5d595b5de94`.

## Selection and compatibility

- Generic native export and Board defaults leave posted merging, posted/PF
  coexistence and PF-only initial head offer OFF.
- The user-selected `fpga/next/performance.py` v2 recommendation enables posted
  merging, coexistence and head offer. `--disable-posted-prefetch` restores the
  original posted-only recommendation; `--disable-posted` disables all three.
  The controls are mutually exclusive. Translated-response empty flow and
  prechecked request flow remain OFF in every selection.
- The published callable `export.main(argv=None, expected_profile_sha256=None)`
  API and complete preflight `configuration` and `command` are preserved.
- The complete preset profile is frozen in `fpga/next/performance-profile.json`.
  All three selections contain 65 fields. Explicit canonical digests bind the
  complete profile, including both new controls. Fresh actual reports compare
  all 26 FPGA, 135 core and 10 cache fields to their qualified references.
- `--posted-prefetch-coexistence` requires `--posted-store-merge`.
  `--posted-prefetch-head-offer` requires both. The independent generic exporter
  and `simulator/gsim/fpga_next_board.py` accept these explicit experiment flags;
  the fixed performance recommendation rejects hardware overrides.

## Separate Board experiments

Existing `simulator/gsim/posted_board_lineage/run_board.py` and
`ooo.PostedStoreBoardLineageGsimMain` keep OFF/ON as posted merging OFF/ON. The
existing raw guest, host, old-only control, independent oracles and five-case
layout are retained. Added constructor fields are explicitly false.

New independent launchers share that unchanged guest and stable host/oracle:

- `simulator/gsim/posted_prefetch_board/coexistence.py`: both sides posted ON;
  OFF/ON toggles only cache/profile coexistence.
- `simulator/gsim/posted_prefetch_board/head_offer.py`: both sides posted and
  coexistence ON; OFF/ON toggles only core/profile initial head offer.
- The corresponding `coexistence_audit.py` and `head_offer_audit.py` launchers
  select separate read-only actual-constructor audit entry points.

The new model/runtime launchers use the same `bind`, `models`, and `run`
arguments as the existing runner, including explicit source head/tree and tool
receipt, fresh output namespaces, and parent-granted heavy slot. Bindings record
experiment and launcher identity and reject cross-experiment reuse. Each new
pair uses six runs: normal/token-negative/byte-negative on each side. The full
frozen constructor profile checks every field and rejects unknown or misplaced
fields, even when both sides share the same mutation.

Direct Scala emitter names are `ooo.PostedPrefetchCoexistBoardGsimMain` and
`ooo.PostedPrefetchHeadOfferBoardGsimMain`, each taking `FRESH_OUTPUT off|on`.
They use `PostedPrefetchBoardProfiles`, whose explicit native flags are checked
against complete constructors. New paths have not been dynamically qualified.

## Evidence boundary

Historical source `6f1` and Board helper `e9af6a49e73f6606be233086fc1f57a4b86acb73`
retain their original evidence identities. Their exact historical helper bytes
are separately archived in the integration packet, not described as runs of the
new launchers. Recorded historical qualification includes configuration,
focused host groups, fresh OFF/ON Board models and six functional runs, actual
constructor/FIR equality, and a minimal genuine core/cache/home hot/cold PF-A-held
old-fail/new-pass witness. Native OFF matched all 269 historical coexistence-ON
RTL files; ON changed only the IntegerBackend combination with literal-state
delta 0/0. These are scoped historical results, not a full integration PASS.

The scoped extended gate is now complete: 13 fresh genuine CPU/cache/home
runs cover hot/cold PF A-held, E/ReleaseAck tails, request/response hold,
FENCE/SATP drain, PF AXI error and a separate generation-two fallback model.
Candidate cancellation with an eligible producer and concurrent non-PF accepted
owner with an otherwise eligible initial head remain UNREACHED. Broader producer
fault/recovery injection remains previous component/source evidence. The exact
unchanged consumer gate retains 49 final-byte cases and 12 expected assertions;
it is not fresh combined CPU coverage. `full_qualification=false` is retained.

The complete original case18/19 S-mode Bare physical COPY/WRITE Board A/B passed
under the historical
qualified helper identity. COPY is 457,146 + 5,620 kernel/flush cycles with head
OFF and 365,235 + 5,618 with head ON; WRITE is 112,826 + 10,646 on both sides.
The historical posted-only reference is COPY 452,641 + 5,666 and WRITE
112,826 + 10,647. The prior coexistence-only COPY regression remains explicit.
No-posted COPY 383,603 + 5,618 from the published seal performance record is a
separate historical reference, not a fresh A/B control; head-offer ON throughput
is 5.029% higher for the kernel and 4.953% higher including flush. Full results and retained limits are in
[the current preset record](posted-performance-preset.md).

Fresh integration recommendation source `996d998275624e7527ce278dc0bc9157ef3ab3d1`
passed complete actual profiles for all three controls. Recommended ON matches
all 269 qualified head-offer ON raw native files; full OFF matches all 266 prior
integration OFF files. Legacy posted-only has a fresh pure profile and prior
same-production native binding. The original integration-to-f1 raw native FAIL
is retained: one cache module differs. A separately reviewed narrow structural
proof allows only documented typed internal renames and exactly three uses of
one scalar alias, with complete token equality and 12 rejected nonzero mutations.
This is not a general equivalence or physical timing claim.

The new Board experiment entry points have host/configuration contract checks,
but have not run fresh GSIM models; their historical wrappers remain distinct
archived evidence. The Board `reserveWithoutCapacity` diagnostic copy omits
`postedLaunchAllowed`, so bit 35 is not reliable capacity-stall evidence. No
passing performance, AXI or direct-assertion gate depends on it. The older full 54-case/Sv39 runs used different source; this combination has not
run the full 54 or Linux. No FPGA, STA or mapped PPA claim is made.
