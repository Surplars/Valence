# Combined bandwidth physical input contract v1

This is an independently named experimental candidate, not an extension of a
frozen qualification. Historical `prepare.py`, `validate_native`, R3 entry
points, frozen reference witnesses, and the historical ROM decoder are unchanged.
No hardware, Vivado, or physical run is performed by preparation or these tests.

Required actual construction: resident ranking ON, shared two-word fetch PMP ON,
disjoint victim/store overlap ON, split cacheable bounds OFF. The actual audit
binds the full 178-core/95-profile products and field order, one resident selector,
two shared PMP helpers, one nonblocking cache, proof3/credits2/LSU4, 512 lines/two
ways, native MAC/raw handoff, USER2/BSCAN2, RAM loader, and 76 top ports. Both MAC
physical generics remain explicitly 1. CPU/AON/UART/DDR UI are 100/50/50/250 MHz.
Nothing inherits earlier simulation, boot, CDC, timing, or board qualification.

## Fresh export, once final sources are committed

`python3 -B emit_combined.py --help` lists required explicit source/output paths,
full commit, Mill/firtool/Java executable paths, actual Mill distribution path, and exact version outputs (JVM option echo lines are excluded).
The source checkout must be clean, including untracked files, and the output
must be new and outside the checkout. Execute the wrapper from that same source
checkout. It runs only `IonSoC.test.runMain ooo.CombinedBandwidthNativeMain OUT
native`, with pinned firtool directory and Java home; it never runs a simulator
or Vivado. It hashes the complete tracked file closure before and after emission,
checks launcher, actual Mill distribution, and tool executable bytes before/after, and seals all output files. Supported Mill selection is a standalone distribution or the reviewed adjacent `mill-dist` launcher. Mill must report the explicitly selected Java home; the version probes and emission use that same JDK/firtool environment. Recorded options are allowlisted/redacted; proxy endpoints, credentials, and JVM option echoes are not retained in version receipts. Gitlinks
are separately recorded. Build/dependency version declarations are bound through
the build source files. System shared-library bytes are not independently pinned.

The emitter seals the actual variable SV/resource inventory, including the
complete, duplicate-free synthesis file list. There is no legacy SV-count guess.
`export-provenance.json` and `emission-toolchain.json` are produced only for a
successful fresh export. A direct dirty-checkout structural export is useful
experimental evidence but cannot substitute for this provenance.

## External-input gate and staging

`python3 -B prepare_combined.py --help` lists required paths. Besides the fresh
native export and final source commit, provide all of the following:

- A reviewed emission-toolchain manifest (the wrapper's file is available for
  review), exact expected `version -short` for the future Vivado run, Python mode
  and command, and explicit WSL distribution when applicable.
- A selected ROM directory containing real `bootrom.bin`, `bootrom.coe`,
  `bootrom.even.hex`, `bootrom.odd.hex`, `bootrom-contract.json`, and `bootrom.map`.
  A separate ROM manifest must contain every one of these names, each with
  `sha256` and `bytes`; provide raw and zero-padded 128 KiB hashes. COE, both banks,
  binary, and MIF must agree byte-for-byte. Contract binary hash and CPU/timebase
  clocks are checked. Map provenance is byte-bound, not semantically interpreted.
- A reviewed local IP root and manifest with portable relative paths and exact
  `sha256`/`bytes`. Require the four XCI paths, generated ROM MIF, and two board XDC
  paths listed in `combined_contract.IP_FILES`. ROM XCI must resolve to this run's
  selected COE, not an old image. No historical SoC DCP/EDIF is an input.
- If generated IP DCP/EDIF products are needed, supply `--ip-ownership`. Each
  asset path maps to `{xci, xciSha256, top, part}`. Owner XCI must be one of the
  four selected files; asset name/directory, embedded DCP Top/Part/OutOfContext
  metadata (or EDIF design/PART), and hashes are checked. Unsupported or absent
  ownership metadata fails closed rather than accepting a renamed SoC DCP.
  Supplied IP Tcl/XDC that loads additional sources requires explicit closure
  review; current staging rejects such loading commands.

The new run root must be outside the source and must not exist. Preparation
copies exact inputs, creates the existing source-bound native MAC integration
contract, checks all 76 port widths, and seals every script/input/config byte.
Resource emission bytes must equal the exact pinned firtool header plus source
resource with one final LF removed. A failed staging attempt can leave an
incomplete new directory; it is never reusable evidence. Use a fresh root after
correcting the inputs. Missing local ROM/IP inputs block staging; mock fixtures
and the historical 223453b checkpoint do not satisfy this gate.

## Explicit future tool entry points

After a separate authorized run decision, use `scripts/combined_synth.tcl ROOT`
and `scripts/combined_place.tcl ROOT FRESH_NAME`. These are the candidate entry
points. Invoking historical `r3_*.tcl` directly is not candidate execution.
Each stage verifies the exact sealed package and actual Vivado version first.
Synthesis creates exactly one `create_project -in_memory` project; no whole-SoC
checkpoint is imported. Immediately before the actual synth command, the tool's
resolved `get_files -all` inventory must be entirely sealed package inputs or
files under the detected Vivado installation. Unaccounted files abort synthesis.
Installed vendor libraries are version-checked; their individual bytes are not
pinned. Actual transitive-IP inventory audit is NOT RUN until this tool step.

A successful synthesis writes an exclusive stage receipt binding package seal,
source commit, emitted RTL inventory, emission toolchain, Vivado version, final
DCP hash, and reports. Placement checks that receipt and all recorded synthesis
artifacts before opening the DCP. Swapped checkpoints, stale PASS markers,
failures, missing receipts, and reused run directories fail closed. Placement
writes its own exclusive receipt only after checkpoint/report collection and
both selected-ROM graph reconstructions succeed. Each receipt is integrity
bookkeeping for the tool flow, not a cryptographic attestation from the tool.

Placement discovers actual hierarchy, applies existing native MAC/BSCAN/board
constraints and clock/MIG checks, and captures the selected ROM graph before and
after placement. The separate candidate decoder supports a variable **actual**
RAMB36E2 inventory, checks dump/graph agreement and every logical ROM word, rejects
missing/extra/unreachable/unsupported RAM and mismatched INIT/ports, and accounts
for every RAM. This is static INIT/address/output reconstruction only: clock
connectivity/polarity, RAM reset/sleep/write controls, temporal read behavior,
and boot/board functionality remain UNVERIFIED. It is not sufficient to authorize
boot or bitstream readiness. No route, bit generation, or programming exists in
this flow. Timing/CDC findings always require review; no timing closure is claimed.

## Tests

- `python3 -B test_tools.py`: unchanged legacy boundary tests and all Tcl syntax.
- `python3 -B test_combined_emitter.py`: launcher/distribution byte binding, changed distribution with unchanged launcher, and option-echo/environment redaction.
- `python3 -B test_combined_contract.py`: synthetic-only contract/source/ROM/IP
  ownership/stage-binding negatives, wrong flags, stale receipts, missing/extra
  RTL, changed source/toolchain, swapped DCP, and absent external inputs.
- `python3 -B test_combined_rom.py`: synthetic full-word graph and missing bit,
  changed INIT, wrong port mapping, extra/unreachable and unsupported RAM negatives.

These tests produce no real hardware or physical claims. No generated RTL, ROM,
IP, DCP, or tool outputs belong in Git.

## Open shared-MAC timing report (2026-10-16)

The user reports RX input hold -0.714 ns at all three line rates and FIFO skew
-3.991 ns in an in-order integration reusing earlier MAC sources. Exact report
and effective export provenance are being investigated. This combined entry
retains the existing tri-speed MAC; it does not fix or qualify those failures.
Passing source/packaging or synthesis checks is not MAC I/O/CDC signoff. Do not
claim board/bit readiness without the relevant routed setup/hold and bus-skew
checks under unchanged PHY/PCB budgets.

Read-only follow-up identified the report as the old uncommitted in-order build
`orbital-i1-board-zu15eg-20261016-r2`, not this candidate. Its top explicitly used
RX_DATA_DELAY_PS=0, whereas the current tri-speed top uses 1100 ps. External RX
input bounds remained +/-1.050 ns with a 2 ns virtual launch displacement.
Its FIFO skew check mixed source-domain RAM launches with destination-domain
address/feedback launches under a 3.333 ns budget; the failing bus was physical
RX ingress payload, while its Gray-pointer checks had positive slack. Current
shared helpers select reviewed RAM leaf launches separately. These source and
constraint differences do not establish updated routed setup/hold/skew closure.

## Validator-only corrections with a preserved native export

A staging-only correction does not require relabeling or regenerating unchanged
native RTL. Keep `--source-root` at the export's original clean commit and keep
`--commit` equal to that original commit (for the current native export:
`3554932ea0b1136ba9b41257385df0c1e8c5ff5c`). Run `prepare_combined.py` from a
separate clean checkout containing the reviewed validator correction and pass
its exact `--validator-commit`. The two closures must be identical outside
`fpga/next/physical_eval/`, including gitlinks. The new package records both
`sourceClosure` and `validatorClosure`; the original native receipts remain
byte-identical. This exception changes the staging validator identity only and
cannot admit changed hardware, build inputs, resources, or board integration.

Only full-line XDC/Tcl comments at syntax-proven complete command boundaries are
ignored by the external-loading scan. Quoted/bracketed and backslash-continued
content stays subject to the conservative scan. No input Tcl is evaluated.
Candidate runtime subprocess calls retain raw stderr in separate binary logs and
record exit status. Successful WSL warnings do not contaminate JSON stdout;
nonzero subprocess exits still abort. Logs live under the external run root.
Run `python3 -B test_combined_portability.py` for these focused mock regressions.
