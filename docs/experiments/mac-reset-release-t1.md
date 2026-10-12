# Optional native MAC local PAD reset release

The generic top and native wrapper defaults remain OFF. The three qualified T1
production files retain their exact checkpoint bytes. T1 adds one falling-PAD
asynchronously preset logical state bit when explicitly enabled; this is not a
mapped FF count or a claim that the prior recovery failure is closed.

## Explicit export and consumption

`fpga/next/export.py --output OUT --experimental-trispeed-ethernet
--native-mac-local-pad-reset-release` selects the physical mode in a source-only
preflight. The exact T1 flag is accepted once, takes no value, and requires
tri-speed. Omission selects mode 0. `--emit` uses the existing native export path;
no native emit was performed to qualify this new Python/Tcl bridge.

`fpga/next/board_t1.py --output OUT` is the separate explicit T1/media preset.
It binds the published ABC manifest SHA256 and inherits all 46 native options,
including USER2, all three timing stages, proof2 and credit2; its only addition is
the physical T1 flag. For another independently selected configuration, add the
exact T1 flag to that configuration's export invocation.
It is not a new Scala argument and does not change the CPU configuration hash.
No published CPU or board preset is silently changed to T1 ON.

A completed tri-speed export carries `native_mac_mode` in its receipt and writes:

- `board/native-mac-mode.json`: selected mode, exact top/generic, source hashes and
  staged file hashes. `applied_to_synthesized_design` is false.
- `board/native-mac-mode.tcl`: explicit consumer for the matched physical top.
  Sourcing it does not synthesize or change the open design.
- `valence_native_mac_synth_design`: when explicitly invoked after the caller has
  loaded the correct sources and IPs, forwards exactly
  `-top soc_top_fpga_next_ddr -generic NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=0|1` to
  `synth_design`. Caller-supplied top/generic overrides are rejected.
- `valence_native_mac_assert_mode u_rgmii`: a read-only post-synthesis call to the
  real quarter-serializer topology audit with expected mode 0 or 1. It must pass
  on the actual design; a recorded generic alone is not mapped-topology proof.

`python3 fpga/next/board_t1.py --verify-export OUT` checks the receipt choice,
manifest, wrapper and staged source/consumer bytes without invoking FPGA tools.
This verifies export bindings only. It does not establish that any implementation
script consumed the setting or that actual topology/timing passed.

The repository's legacy `fpga/zu15eg/build_native_board.tcl` targets
`soc_top_gmac_ddr` and does not consume this contract. It was not modified. Any
user-local custom `run_route` must explicitly use the new consumer, or reproduce
its exact top/generic and run the mode audit. No local script was inspected or
changed, and export alone does not enable T1 in a local physical build.

Host verification is `python3 fpga/next/test_board_t1.py`. Its emitter and
`synth_design` are mocks. It covers OFF/ON with and without BSCAN, rejected missing
media/duplicate/valued/abbreviated flags, identical Scala argv/configuration,
explicit generic consumption and top/generic override rejection, and stale or
mismatched export bindings. Existing media/export, CLI and real Tcl host fixtures
remain separate gates.

## Reproduction boundary and minimum T1 fixture closure

The original T1 behavioral runner, benches, frozen native codec and logs are in
the separate qualified `mac-reset-release-t1` evidence package. They are not
repository-resident tests in this source patch. The original final run is
`validation/results/run-20261012T180220.065454Z`; its receipt is reused by exact
input identity, not relabelled as a new run.

For portable behavioral reproduction, retain the following relative closure:

1. `validation/run_oracle.py`, `structural_oracle.py`, `prepare_freeze.py`,
   `startup_tb.sv`, `codec_tb.sv`, `oddr_reset_tb.sv`,
   `ODDRE1_reset_dominant.sv`, `SOURCE_BINDING.md`, and `REVISION_LOG.md`.
2. `validation/frozen/manifest.json` and every one of its 38 named inputs,
   including the exact candidate/baseline/reset-helper/codec SV, original and
   reset-dominant behavioral primitives, model diff, negative controls and all
   frozen fault SV/patches. Preserve paths and bytes.
3. The exact qualified source binding and emit ancestry:
   `source-identity-manifest.json`, `emit-input-identity.json`,
   `qualification-receipt.json`, and the final run's manifest, summary and command
   receipts. Keep the original native emission files/receipts when auditing
   provenance; do not regenerate or hand-edit codec RTL.
4. The existing reviewed Icarus activation/toolchain at sibling
   `../tool-input/restored/iverilog-toolchain/activate.sh` relative to the T1
   package root. The original runner computes this relative location. Create a
   fresh `validation/results` output, and record any relocated tool binding.

No new Scala emit is needed to rerun frozen inputs. A new source tree must first
be compared to `frozen/candidate.sv`, the helper, and all 61 emitted-source inputs;
otherwise the frozen run says nothing about changed production source. To change
frozen inputs, re-review and refreeze explicitly instead of editing historical
receipts. `prepare_freeze.py` additionally references the exact 1e90 baseline Git
checkout and `native-codec-iverilog`; frozen-only replay does not need to execute
that preparer. The complete minimum input map is retained with this integration's
`portable-t1-inputs.json` handoff artifact.

## Retained qualification limits

T1 behavioral startup/codec checks retain common-divider epoch assumptions and
independent first-slot checks. Original 10/100 Mb/s partial first TXC high pulses
were observed only with TX_CTL=0 and no frame owned on the pins. They do not prove
PHY acceptance, a full-width first pulse, vendor ODDRE1/OSERDESE3 startup/relock,
or physical recovery/removal. RAW-to-local PRE and every local-to-serializer reset
arc, same-edge removal, pulse width and PHY budgets remain to be qualified.

The companion BSCAN fault phase adds one logical state bit relative to published
12beb29, requires eligible resumed TCK edges, and preserves the old
immediate-revoke counterexample as a negative contract rather than a new PASS.
Raw-toggle BUSY to positive DRCK remains timed. The prior batch's +69 source bits
are already in that base and are not added again. This integration makes no STA,
mapped-resource, routed, board or vendor-primitive claim.
