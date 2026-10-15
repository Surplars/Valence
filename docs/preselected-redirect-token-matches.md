# Default-off C0 redirect-token comparison experiment

Only C0 is implemented. Source baseline: `d5a04946`. The backend constructor
option `preselectRedirectTokenMatches` defaults to false; no OooParams or
FpgaNextConfig field, default/preset, bank lifecycle or frontend payload changes.
The exact comparison fixture uses core178/profile95, issue2, ROB16/PRF48,
tag64, proof3, credit2 and LSU4. C1/C2 remain design proposals with unresolved gates.

## Change and scope of the cut

The original backend selects a 68-bit local payload with headSystemAccepted,
then RedirectTokenQualification compares it against two query tokens.
The opt-in PreselectedRedirectTokenQualification compares raw local/system/trap
payloads first; accepted controls choose only Boolean results, retaining
trap > accepted system > ordinary local priority. A mismatching trap still
blocks lower matches. system request never substitutes for acceptance.
The frontend redirect payload mux and ledger/kill/commit/start/credit decisions
retain their existing semantics and timing. The immediate raw recovery veto,
PMP/context/epoch guards and complete token checks are unchanged.

Actual emitted backend IR confirms:

```text
baseline: localRedirect = mux(ledger.io.headSystem.accepted, systemCandidate, localCandidate.bits)
          redirectTokens.io.local.bits <- localRedirect.token
candidate: preselectedRedirectTokens.io.systemToken <- systemCandidate.token <- systemOwner
           preselectedRedirectTokens.io.systemAccepted <- ledger.io.headSystem.accepted
```

The component IR audit verifies all six candidate equality input cones exclude
Accepted controls. This establishes ONLY the accepted-system -> payload mux ->
equality cut. It does not establish removal of the whole cache/proof CE cone,
which still includes pause/flush/reserveSystem and other accepted-control paths.

## Reproducible focused run

Use an existing GSIM binary at pinned revision
`93b8cd23edd3228807c4f2a08c19c3936a463cb2`, Clang19+ and Mill1.1.7:

```sh
python3 -B simulator/gsim/preselected_redirect.py \
  --output build/gsim/preselected-redirect-UNIQUE_TAG \
  --gsim "$GSIM" --cxx clang++-19 --jobs 2
```

Output must be fresh. JVM processing is bounded, GSIM is single-threaded and
translation units compile serially with ASan+UBSan. The runner fingerprints
Scala inputs, drivers and the simulator, logs commands, and rejects source drift.
No toolchain rebuild, full GSIM suite, NEMU suite, Vivado, route or bit is invoked.

The retained ready-query oracle is unchanged. The runner adds only an
observer destructor to a build-directory copy for cycle/traffic counters.
The lifecycle driver includes the retained independent interpreter/memory oracle
and links to the SAME generated model objects; it does not regenerate a model
or substitute DUT authorization predicates into expectations.

## Results

Evidence identifier: `preselected-redirect-20261015-r2`, receipt SHA256
`4028fb8fed4a016341c302a2d512266e30dc56ee68523a32ee2bf6b1f934e26b`.
The ignored build directory retains FIR, generated models, objects and all logs;
generated products are not source deliverables. The earlier r1 failed only in
the audit parser's handling of `public module`, before simulation; it is retained.

- Scala no-state/schema check passed. Both arms elaborate the exact same 178-field
  product, checked against ThreeProofRowNativeProfile; candidate changes only
  the backend constructor Boolean.
- Component: 50,186 cases; 12,409 request-without-accept cases, 3,255 mismatching
  trap suppression cases, 3,342 highest-tag-bit rejection cases. Directed cases
  flip EVERY tag bit and repeat a system request with no new acceptance.
- Independent C++ oracle selects raw payload with scalar priority, then compares
  index and complete tag once; it does not repeat the candidate decomposition.
- Three verification-only mutations (request-for-accept, bit63 corruption,
  fallthrough after mismatching trap) all fail the independent oracle.
- Both real backends pass eight ready/PMP/fault cases and four lifecycle cases;
  injected bad data, bad frozen PA and killed/duplicate retirement are rejected
  in each arm. No DUT assertions were removed or relaxed.

| Scenario | Baseline cycles | Candidate cycles |
| --- | ---: | ---: |
| Fresh ready nonhead store, missing proof | 646 | 646 |
| Four byte/alias cases | 568 / 554 / 568 / 554 | 568 / 554 / 568 / 554 |
| Ready-head missing-proof veto/progress | 567 | 567 |
| Published PMP epoch requery | 776 | 776 |
| Write PMP denial / precise fault | 606 | 606 |
| Two bound stores, frozen PTE, two credits / exact store capture | 835 | 835 |
| Oldest store late fault | 774 | 774 |
| Selective branch kill, bound stores survive | 914 | 914 |
| Full branch kill, credits drain only with real responses | 668 | 668 |

Each paired case also has identical accepted, retired, physical request and
response counts. Measured cycle/throughput change is 0%, with no additional
pipeline cycle. These short decoded-backend traces include CSR setup and drain;
they are not whole-board workload, Linux or CoreMark performance measurements.

## State, resources and remaining risk

Added architectural/microarchitectural storage: **0 bits**, corroborated by
emitted combinational module IR. Two consumers change from four to six complete
68-bit equalities. Shared/compressed logic may differ after mapping; physical
area can increase. GSIM's generated graph reports 7738 -> 7736 nodes and the
same 890 supernodes; these are simulator graph metrics, NOT LUT/FF utilization.
No new FPGA resource, WNS, routed timing, Fmax or power result is available.

Default stays off. This is a simulation-verified structural candidate, not a
measured clock-speed improvement or a new physical/board qualification.
The full raw-token/valid input equivalence covers arbitrary payloads, while the
backend tests cover reachable precise fault, accepted-owner, bind/consume,
PMP transition and kill/drain behavior. They do not prove every hypothetical
future C1/C2 bind+evict collision; those candidates are not implemented here.

See [reviewed follow-up gates](r3-proof-control-decoupling-proposal.md) for rename
replacement semantics, parallel pause/flush cones, first-certificate availability,
same-edge authorization changes, bind/evict collisions and exact STORE-capture
transfer to frozen ownership. None of those contracts is changed by C0.
