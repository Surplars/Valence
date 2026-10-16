# Local RapidWright primitive timing reference

This bounded runner compares selected primitive arcs against an existing matched
Vivado timing report. It does not calculate WNS, Fmax, hold/recovery slack, or a
qualified full-path delay. No router, Vivado, dependency download, or checkpoint
write is invoked. Selected net pin metadata may be reconstructed in memory;
every addition is logged and all raw net-model outputs remain explicitly invalid.

## Run

Supply existing local inputs, installed tools, a Java 21 JDK, and an existing
output directory outside the input bundle:

```sh
python3 scripts/cloud/rapidwright_timing_reference/run.py \
  --bundle-root /path/to/matched-bundle \
  --dcp placed.dcp \
  --edif read-only-export-r2/placed.edf \
  --report read-only-export-r2/setup_paths.rpt \
  --paths scripts/cloud/rapidwright_timing_reference/historical-paths.json \
  --tool-root /path/to/prescreen-output \
  --java-home /path/to/jdk21 \
  --output-root /path/to/evidence
```

Python 3.9+ is required. The explicit tool root contains `downloads/` and
`rapidwright/` as produced by the existing prescreen setup. The runner pins the
actual 2025.1.3 standalone JAR and both UltraScale+ timing-data hashes. Device
files and JDK executables are also hashed into the receipt. Missing or changed
locked tools fail before execution; nothing is downloaded. Only the previously
validated xczu15eg-ffvb1156-2-i part is accepted.

`--dcp`, `--edif`, and `--report` are exact relative bundle paths. The path-selection
JSON contains a list of objects with `label`, exact `source` and `destination`
cell/pin names, and expected `logic_arcs`. Labels must be unique. Optional
`report_block_sha256` disambiguates paths with identical endpoints (e.g. different
edge transitions): hash the entire Slack block after normalizing CRLF to LF,
including its trailing whitespace. The historical CPU selection pins that block. The parser
requires exactly one matching report block, a complete connected FF/LUT path,
and agreement with the report's logic subtotal. It fails on ambiguous duplicates,
unsupported formats or incomplete paths instead of selecting the first slack block.
The included selection describes only the historical 223453b report, not the
current in-order RX failure or a new implementation.

Every run creates a fresh output child, snapshots DCP/EDIF/report/selection and
Python/Java source, and compiles only that Java snapshot into the output child.
Input snapshots are read-only. All bundle files and input snapshots are hashed
before/after; any integrity change sets FAILED_INPUT_INTEGRITY and exits nonzero.
Compilation is limited to 90 seconds, the model process to 600 seconds, Java heap
to 4 GiB and active processors to two. The heap limit is not an OS RSS limit.

A primitive subtotal is emitted only when every selected arc has a supported
nonnegative result. `logic-results.tsv` includes logical-to-physical pin mappings
and observed differences. `net-results.tsv` retains raw diagnostic values but
always marks `valid_net_estimate=false`; they are never summed. Even a future
routed input is not automatically qualified by this deliberately conservative
runner. `intrasite-results.tsv` separately marks supported direct same-site
lookups; it is not an inter-site estimator. `check-arcs.tsv` does not establish
valid setup/recovery checks, even when a table entry exists.

`receipt.json` records status, complete original-input hashes, source/tool/device
hashes, command outputs and integrity results. Failed runs retain their evidence;
no earlier run directory is overwritten. The original bundle's existing checksum
manifest should also be validated independently to establish export provenance.
Hash equality alone does not establish that a DCP, EDIF and report came from the
same implementation.

See [historical results](../../../docs/recovery/historical-timing-reference.md).

Pure fail-closed parser tests: `python3 -B scripts/cloud/rapidwright_timing_reference/test_parse.py`.
