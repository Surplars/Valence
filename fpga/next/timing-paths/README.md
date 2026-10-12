# Timing-family report collector

This optional Tcl utility opens one existing FPGA checkpoint and writes report
files to a **new output directory**. It does not synthesize, place, route, generate
a bitstream, edit the design, or apply constraints. It closes the opened design
when collection finishes. Use a separate Vivado batch process.

## Collect reports

From the repository root, supply an existing checkpoint, a fresh output directory,
and the three exact hierarchy roots verified in that checkpoint:

```sh
vivado -mode batch -source fpga/next/timing-paths/report_timing_batch_paths.tcl \
  -tclargs "path/to/routed checkpoint.dcp" "path/to/new reports" \
  SOC_ROOT BSCAN_ENGINE_ROOT RGMII_ROOT 20
```

Replace the uppercase placeholders with literal hierarchy names. Quote arguments
containing spaces. Generated hierarchy dots are treated literally. Roots must
resolve to exactly one cell with the supplied name; wildcards and square brackets
in roots are rejected. Do not infer roots from a simulator hierarchy. The optional
last argument is `TOP_N`, default `20`, range `1..1000`.

Every family has its own independent **max and min** query/report budget:
`-max_paths TOP_N -nworst 5`. All 16 families therefore produce up to 32 detailed
reports. Each report requests `full_clock_expanded`, input pins, and nets.

## Path families

Selections are primitive cells below the supplied root. The exact regular
expressions and input-pin patterns are in the collector.

| Family | Selected region or endpoint | Input pins |
| --- | --- | --- |
| `proof` | pending store proof | D, CE, SR, R, S |
| `address` | staged memory address | D, CE, SR, R, S |
| `execution` | execution stages | D, CE, SR, R, S |
| `rank51_payload30` | historical lane 0 payload bit 30 | D, CE |
| `canonical_tracker` | canonical store tracker | D, CE, SR, R, S |
| `canonical_event` | adapter certificate valid/bits | D, CE, SR, R, S |
| `manager_we` | manager bridge slot payload banks 0–7 | WE*, WEN* |
| `rank64_slot1_bank5` | historical slot 1, bank 5 write enable | WE*, WEN* |
| `manager_data_address` | manager bridge slot payload banks 0–7 | D*, A* |
| `fetch_packet` | fetch packet | D, CE, SR, R, S |
| `fetch_window` | supplied-packet window | D, CE, SR, R, S |
| `bscan_data_control` | BSCAN engine | D, CE, SR, R, S |
| `bscan_reset` | BSCAN engine | CLR, PRE, RST |
| `mac_data_control` | RGMII wrapper | D, CE, SR, R, S |
| `mac_reset` | RGMII wrapper | CLR, PRE, RST |
| `ref500_reset` | RGMII delay-control primitive | RST |

The `rank51` and `rank64` labels identify historical endpoints, not current path
ranks. `R` is not presumed asynchronous. For reset pins, inspect the actual check
type in the report; the loaded timing model determines recovery/removal behavior.
Queries do not filter launch clocks, so unexpected launch domains remain visible.

## Interpret the output

`coverage.txt` records root matches, family cell/pin counts, the selected object
names, timed-path counts, start/end pins and clocks, slack, requirement, data-path
delay, and logic levels. Multiple matching cells are explicitly marked for review.
The output also includes timing summary with unconstrained coverage, clock
interaction, exception coverage, and detailed CDC reports.

Missing/ambiguous roots, no matching family cells or endpoint pins, no timed
paths, unavailable required properties, and report/query failures are **not a
pass**. The standalone script reports an error and retains evidence already
written. Existing output directories are rejected to avoid overwriting reports.

Even an issue-free collection reports `COLLECTED_REVIEW_REQUIRED` and
`NOT_TIMING_OR_CDC_PASS`. Patterns can become stale when synthesis changes names
or structure. A nonempty match does not prove that every intended endpoint was
selected; review the actual cell/pin counts and names. Families may overlap.
This utility does not replace global setup/hold, utilization, fanout, congestion,
active/ignored/overridden exceptions, FIFO per-bit, pulse-width, or exact MAC/BSCAN
topology checks. It neither applies their constraints nor claims those checks pass.

## Run the standalone mock

Only Tcl is required. Choose a test-output path that does not already exist:

```sh
tclsh fpga/next/timing-paths/test_report_timing_batch_paths.tcl \
  fpga/next/timing-paths/report_timing_batch_paths.tcl \
  "path/to/new mock output"
```

The nine mock cases cover successful selection/multiple matches/paths with spaces,
existing-output rejection, missing endpoint cells, changed pins, ambiguous roots,
missing roots, missing timed paths, unavailable clock properties, and redirect
errors. The positive case asserts 32 independent family/delay queries and reports;
the mock executes the Tcl `redirect` body and checks query/report arguments.

`mock-receipt.json` records the source hashes and local mock result. This is a
synthetic API contract test. **No Vivado run or qualification was performed.**
It does not validate a Vivado version, property schema, mapped hierarchy,
constraints, timing slack, resources, CDC, or board behavior.
