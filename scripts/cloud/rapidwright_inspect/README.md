# Read-only RapidWright checkpoint inspection

Loads an existing matched DCP and readable EDIF, then reports counts and selected
physical-net/EDIF endpoint placement. Does not modify the design, construct
routing, write a checkpoint, invoke Vivado, or download dependencies.

## Installed requirements

- Python 3.9+ and a Java 21 JDK (`java` and `javac`).
- An existing `scripts/cloud/prescreen` output directory containing `downloads/`
  with the locked `rapidwright-2025.1.3-standalone-lin64.jar`, and `rapidwright/`
  with installed data for `xczu15eg-ffvb1156-2-i`.
- Matched DCP, readable EDIF, reports and SHA-256 manifest. No automatic readable
  EDIF generation or device-data download is allowed; missing inputs fail closed.

```sh
mkdir -p /path/to/analysis-output
python3 scripts/cloud/rapidwright_inspect/run.py /path/to/bundle/analysis-manifest.json \
  --tool-root /path/to/prescreen-output \
  --java-home /path/to/installed-jdk \
  --output-root /path/to/analysis-output
```

`--tool-root` and `--output-root` are required. The output root must exist; every
run creates a fresh child directory. `--java-home` is optional: discovery uses
`JAVA_HOME`, then `javac` on `PATH`. It never installs or downloads a JDK.
The heap is limited to 4 GiB, active Java processors to two, checkpoint analysis
to 600 seconds and compilation to 90 seconds. These are not total OS RSS limits.

## Analysis manifest

Preserve the original export manifest. Create a separate analysis manifest in
the same bundle directory, deriving exact physical-net names from report net
rows, not clock names or guessed aliases:

```json
{
  "schema": 1,
  "run_id": "original-run-identifier",
  "part": "xczu15eg-ffvb1156-2-i",
  "matched_export": true,
  "source_manifest_sha256": "SHA-256 of original manifest.json, if present",
  "files": [
    {"path": "placed.dcp", "role": "dcp", "sha256": "actual SHA-256"},
    {"path": "export/placed.edf", "role": "edif", "sha256": "actual SHA-256"},
    {"path": "export/setup.rpt", "role": "report", "sha256": "actual SHA-256"}
  ],
  "critical_nets": [
    {"name": "exact/net/name", "report": "export/setup.rpt", "line": 80}
  ]
}
```

All paths must resolve inside the bundle. The line number is one-based; exact
name presence is checked, but the operator must establish that the cited field
is a data/reset net. `matched_export` records provenance reviewed by the
operator: hashes establish byte identity, not independent proof of lineage.
When `source_manifest_sha256` is supplied, `manifest.json` must contain `files`
entries with `path`, `bytes`, `sha256`. Every original entry is verified before
and after analysis, in addition to analysis inputs. It is copied unchanged to
`source-manifest.json` in the output. Omit the optional hash field only when no
original manifest exists; do not put a placeholder there in a real invocation.

## Results and interpretation

- `summary.tsv`: exact part, top, physical cell/net/site-instance counts.
- `nets.tsv`, `pins.tsv`, `pips.tsv`: stored physical pin/PIP records.
- `logical_endpoints.tsv`: EDIF physical endpoint queries mapped to physical
  cells, sites, BELs and tiles. No endpoints are created or connections changed.
- `site_cells.tsv`: cells in associated sites; this is **not** a claim that all
  those cells are connected to the selected net.
- `receipt.json`: success/failure, input preservation, output hashes.
- Source snapshots, command and logs retained in each run directory.

A placed DCP may have zero stored inter-site pins/PIPs despite many logical
loads. A zero stored site-pin fanout is **not** zero logical fanout. Use EDIF
endpoint counts and check that physical mappings are populated. Missing
mappings are blank, not fabricated. Absent PIPs cannot support route analysis.
Physical geometry is not delay; no WNS, hold, Fmax or timing-closure result is
computed. Failed/partial output directories are evidence, not successful
results. No generated data or real checkpoints belong in the repository.
