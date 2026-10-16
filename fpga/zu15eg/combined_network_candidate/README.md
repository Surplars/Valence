# Coherent source-only network candidate

Default OFF. This entry composes the reviewed PAD-domain reset and RX capture
sibling/falling-pair adapters against **one original 3554932 board**, whose exact
SHA256 is pinned. The CPU source is untouched. Each adapter is evaluated in a
separate temporary directory against the original; their nonoverlapping,
baseline-relative line edits are merged once. Overlap is an error. This avoids
the destructive sequential-adapter overwrite described in RX INTEGRATION.md.

## Commands / four modes

From the repository root, use a fresh output directory:

```
python fpga/zu15eg/combined_network_candidate/export_board.py OUT
python fpga/zu15eg/combined_network_candidate/export_board.py OUT --enable-pad-domain-reset --serializer-profile t1-selected
python fpga/zu15eg/combined_network_candidate/export_board.py OUT --enable-rx-capture-sibling
python fpga/zu15eg/combined_network_candidate/export_board.py OUT --enable-pad-domain-reset --enable-rx-capture-sibling --serializer-profile t1-selected
python fpga/zu15eg/combined_network_candidate/export_board.py OUT --audit
python fpga/zu15eg/combined_network_candidate/test_candidate.py
```

OFF is byte-identical to original board. Each single mode is byte-identical to
its reviewed adapter. BOTH retains every disjoint edit and includes both new
modules. PAD requires explicit T1/selected profile, sets both board defaults to
1, and retains the elaboration guard rejecting incompatible overrides. The
complete ANSI port declaration bytes are compared unchanged; this is not a
fresh elaborated 76-port native SoC check.

The source receipt binds the board and all zu15eg SV, Tcl, XDC and Python source
bytes before/after reconstruction. Audit independently rebuilds expected bytes,
checks exact receipt contents, rejects missing/extra outputs and symlink RTL,
and requires the current source closure to equal the receipt. Receipts must be
regenerated after any bound script change. They do not authenticate an unrelated
checkout or substitute for the full native emitter's clean source/tool closure.

## Ownership and integration gate

* Original package-pin ownership remains in native_gmac_pins.xdc, board_ddr.xdc
  and pl_ddr4_pins.xdc; every existing XDC is unchanged and source-bound.
* Original tri-speed input/output timing truth belongs to
  trispeed_board_constraints.tcl and trispeed_quarter_constraints.tcl with their
  native quarter-clock/CDC helpers. These files are bound, **not applied** by
  this exporter. No new exception, pin location or delay assumption is added.
* Enabled topology needs a fresh combined clock/reset/pin-ownership audit. The
  legacy topology gates are not compatible and must not be silently bypassed.
  Keep RAW/PAD/REF ratios and common lock/reset source checks, T1 mode ownership,
  RX sibling input ownership, five IDDRE1 capture clocks, ten atomic pair bits,
  fabric decoder clock, and distinct dedicated clock routes in that audit.
* RX capture and fabric are related clocks. Check both half-cycle paths,
  all data/control pins and edges, and all three rates; no async groups or
  false paths. PAD recovery/removal remains real timing. Preserve original
  PHY/PCB input constraints rather than making a failing path disappear.
* A future combined CPU/network build must re-export a fresh full native source
  inventory with explicit two flags and serializer mode. Do not overlay this
  output into an already sealed physical package or inherit its qualification.

## Evidence and limits

Five focused test methods cover all four modes, exact single equivalence, BOTH
markers and port bytes, bad profile/type, conflicting edits, stale flags/source,
changed sources during export, corrupted RTL, and missing/extra output. Existing
PAD/RX formal evidence remains scoped to those reviewed modules and assumptions;
this source composition does not establish analog clock behavior or a whole-MAC
proof. See sibling PAD README and RX README/INTEGRATION.md for precise proof
bounds, retained arbitrary-stall timeout, old/current timing budgets, and
conditional downstream composition. Separate IDELAY readiness-loss integration,
physical timing, vendor primitive routing/placement, and full-board qualification
remain open. No physical pass, bit readiness, or new routed margin is claimed.
