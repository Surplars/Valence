# Timing batch historical replay

This directory carries a small review report, exact source patch, and a source
preparation helper. It does not change any production flag or automatically run
hardware tools. The qualified source is the historical working tree in
`source.json`, based on commit `1e90af966c15d871d2544469174acba78473113b`.
Committing this review directory creates a different HEAD; no test result is
transferred to that HEAD by implication.

`prepare.py` defaults to a read-only plan. Supply a clean local repository that
contains the pinned base, and a nonexistent destination outside that repository:

```sh
python3 simulator/gsim/timing_batch_review/prepare.py \
  --repository /path/to/clean/repository \
  --destination /path/to/new-r2-checkout
```

Add `--execute` to create the checkout. It copies Git objects locally, checks out
the pinned base, verifies the complete patch SHA, applies it to the index, and
verifies the complete resulting tree and all 61 changed-source hashes. It rejects
dirty input repositories, existing destinations, and destinations inside either
input or overlay checkout. It never resets, cleans, stashes, or writes the input
repository. Failed new checkouts are retained for inspection. No Java, Scala,
GSIM, compiler, simulator, installation, or network command is invoked.

Use `--variant baseline` with another nonexistent destination to prepare the
pristine base. The helper does not configure toolchains. Consult the existing
`simulator/gsim/README.md` and pinned tool contracts; the tested environment used
Mill/Java, firtool 1.135.0, GSIM official splitting, Clang 19, and RISC-V GCC 14.2.

The replayed r2 tree already contains `timing_batch_backend.py`,
`timing_batch_cpu.py`, the original guest, service host, and independent oracles.
Its CPU runner also defaults to plan-only. Example after source preparation:

```sh
python3 /path/to/new-r2-checkout/simulator/gsim/timing_batch_cpu.py \
  --source-root /path/to/new-baseline-checkout \
  --output /path/to/new-baseline-checkout/build/gsim/fresh-baseline \
  --profiles baseline --jobs 1
```

Only a separately authorized `--execute` performs the hardware build/runtime.
After a fresh baseline completes, select `--profiles ac` or `--profiles abc`,
point `--source-root` and `--output` into the replayed r2 tree, and supply its
actual `--baseline-receipt`. Historical receipts bind original source and
dependency paths; copying them to another machine is not a supported substitute
for a fresh baseline or an explicitly audited same-hash remap.

The backend runner stages are `freeze`, `config`, `emit`, `generate`, and
`sanitized`, with explicit source/tool paths shown by its `--help`. Each stage
must use the same fresh output directory and frozen tool/source identities.
It retains the original two-row/two-credit host and five corruption controls.

Independent A/B/C component fixtures remain in their small, separately published
source-bound archives. `components.json` identifies Library file IDs, archive
hashes, exact fixture/host/oracle member hashes, and replay limitations. They are
not silently added to the combined Scala test tree. In particular, the C
standalone fixture predates the unified parameter equality guard; importing it
directly into the combined tree is not a valid qualification shortcut. Cached
class bindings and historical grant records need fresh source/tool validation.
This package makes no clean-checkout one-command independent-component claim.

See `docs/experiments/timing-batch-r2-qualification.md` for the qualification
boundaries. `results/` contains small immutable derived receipts; absolute paths
inside those receipts are historical provenance, not executable defaults.
