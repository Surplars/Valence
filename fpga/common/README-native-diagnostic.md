# Native-only physical diagnostics

`native_diagnostic.py` is a separate measurement entry point, not a production
gate, qualification receipt, or replacement for historical `resume_diagnostic`.
It does not import those recovery seals, regenerate IP, run a custom collect,
write a bitstream, or assert that timing/DRC/CDC/functional checks passed.

## Input spec

Create a JSON spec with these fields. All file paths resolve relative to `root`.

- `root`: source/export directory; `origin`: human-readable source commit and
  any working-tree/export changes (do not call a dirty export a clean commit).
- `part`, `top`, `vivado_version`, `threads` (at least 8; actual worker count is
  unmeasured, and synthesis can have a lower effective maximum).
- `sources`: explicit source inventory, including source Scala, ROM inputs,
  included headers and every helper sourced by constraint scripts.
- `rtl`: ordered SystemVerilog input files; `defines`, `include_dirs`: lists.
- `ips`: list of `{ "xci": "...", "dcp": "...", "product_dirs": ["..."] }`.
  List all generated-product directories used by each XCI, including relevant
  `.gen` and `.srcs` trees. All files in those directories are hashed, and newly
  added files invalidate the manifest. DCPs must already exist. The native
  runner verifies that `read_ip` actually registered each expected DCP path;
  it never trusts a copied project's run STATUS or NEEDS_REFRESH.
- `pre_synth_xdc`: board/DDR/pin XDC files; `late_synth_xdc`: timing-target XDC
  files loaded with LATE processing order (e.g. dynamic CPU300/fabric250 targets).
- `post_synth`, `post_opt`, `preplace`, `pre_route`: explicit ordered constraint lists of
  `{ "kind": "xdc" or "tcl", "path": "..." }`. The last three lists may be
  empty only if no additional constraints are intended. A Tcl wrapper should
  source its helper and call its function explicitly. Required endpoint
  cardinality/matching failures must throw an error, not print a PASS marker.
- `phys_opt`: optional boolean, defaults to false. If true, run native physical
  optimization after saving placement and save `physical-unqualified.dcp`.
- `clock_requirements`: nonempty list of
  `{ "pin": "u_soc/cpuClock", "period_ns": 3.333333333333 }` and corresponding
  fabric 4.0 ns requirement for the dynamic CPU300/fabric250 diagnostic.

The inventory is explicit provenance, **not an automatic source-closure proof**.
Keep ROM mapping and all existing required clock/CDC/delay/skew constraints.
An exported historical XDC is only an explicitly selected diagnostic input:
loading it does not prove complete coverage of newly generated RTL. This runner
does not silently supply old XDC, omit failed constraints, weaken clocks, or
claim a mapped-netlist audit. Production qualification remains separately gated.

## Run

```sh
python fpga/common/native_diagnostic.py prepare native-spec.json native-inputs.json
python fpga/common/native_diagnostic.py check native-inputs.json
python fpga/common/native_diagnostic.py run native-inputs.json NEW_OUTPUT --vivado /path/to/vivado
```

Use a fresh output directory each time. The manifest is checked both before and
after native work; it records actual source/IP/constraint hashes, not a fabricated
old producer identity. Native order is:

1. In-memory `read_ip`, fresh RTL/macros, base/late XDC, `synth_design`.
2. Immediately save `raw-unqualified.dcp`, then post-synth constraints and clock
   checks, then `synthesized-unqualified.dcp`.
3. `opt_design`, immediately save `optimized-raw-unqualified.dcp`, then post-opt
   constraints and clock checks, then `optimized-unqualified.dcp`.
4. Preplace constraints and clock checks, `place_design`, save `placed-unqualified.dcp`.
5. Optional explicit `phys_opt_design`, immediately save `physical-unqualified.dcp`.
6. Explicit pre-route constraints (e.g. a reviewed placement-dependent MAC helper),
   clock checks, `route_design`, save `routed-unqualified.dcp`, then native reports.

Neither physical optimization nor placement-dependent MAC repair is implicit.
Select the option/hook explicitly; neither is a qualification or waiver.
Checkpoint saves precede expensive reports and downstream checks. Failed work
retains the earlier checkpoints; `failure.json` is not a completion receipt.

## Resume without re-synthesis

```sh
python fpga/common/native_diagnostic.py run native-inputs.json NEW_OUTPUT \
  --checkpoint /path/to/raw-unqualified.dcp --stage raw --sha256 OBSERVED_SHA256
```

Stages: `raw`, `synthesized`, `optimized-raw`, `optimized`, `placed`, `physical`, `routed`.
Select the stage actually completed by that checkpoint, not its hoped-for state.
Raw stages apply their required constraint phase; later stages preserve saved
constraints and never rerun synthesis/opt/placement already completed. `physical` skips physical optimization already completed; `placed` applies it only
when requested by the spec. The pre-route hook runs after either entry. `routed`
is report-only. SHA and explicit stage identify an unqualified diagnostic input,
not proof that a foreign checkpoint was produced by this manifest. `invocation.json`
records that limitation. Keep the original producer evidence alongside it.

`outputs.json` means the native commands returned and reports exist, **not a
timing pass**. Review coverage, DRC, CDC, routing, bus skew and min/max timing
reports. Negative slack and missing coverage remain findings, never waivers.
No result from this entry can substitute for production signoff or board testing.

The control-flow tests use Tcl/Python mocks only. Actual Vivado execution of this
new entry point is still required before describing it as native-validated.

Vivado 2025.2 verification is pending for this runner, particularly the
`get_files -all -filter {FILE_TYPE == "Design Checkpoint"}` registration lookup.
The separately observed in-memory `read_ip` flow is supporting evidence, not
native validation of this new entry point. Official command reference:
https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/read_ip
