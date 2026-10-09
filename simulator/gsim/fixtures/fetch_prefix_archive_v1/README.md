# Frozen fetch-prefix archive revalidation

This separate offline wrapper closes a metadata-only audit failure after
host-only commits. It does not edit any original runner, fixture, receipt,
log, executable, or model. It reuses their original terminal audit checks.

Frozen receipts:

- NEMU: `57c19170042ba3b01bb35e5a2d3f6bc8a35ed1084009804a452cb0d312dcdbaf`;
  original host `485cb85294c97433909b29ce0942bf973885e79a`, 12 positives,
  26 negatives, 50 steps and all 1,252 original input hashes.
- Fetch context: `d96ed94fe6b197294ada9993716c83ea69f6a443700717e562bd64b599aecadb`;
  original host `722a629fae1200074b363d84f431b77cda4e2560`, 4 positives,
  8 negatives and 20 steps.
- CPU/DMA plus data-PMP:
  `49031609a7461a4a0171ebc7df449948068368f2c8ad5190d1c3c517db6d542e`;
  original host `6792170a848a26c3e6469c1faa19deefc3186de5`, 4 positives,
  14 negatives and 23 steps.

The only accepted normalization is `source_binding.host_head`. Each call first
executes the unchanged, source-hash-bound `strict_validation.production_anchor`:
current production tree, complete worktree file inventory, all tracked bytes and
resources, no extra files or symlinks, and qualified-host ancestry remain checked.
It separately proves the original historical host has the identical complete
`src/main` tree and is descended from the qualified host, and that the current
host descends from the original one. The audit HEAD must stay fixed throughout.
Other binding fields must match exactly. The wrapper records both historical and
actual current audit HEADs explicitly; it never claims the historical HEAD is
current.

The original NEMU snapshot must match exactly after that single field is handled,
including its original compiler path spelling (with its recorded `../`). All
1,252 original input hashes are rechecked before and after terminal audit. The
original PC, whole-retire-edge 32-GPR, full-RAM, full-token and drain oracles remain
unchanged.

Context and DMA/PMP run their original `main --audit` paths, with reconstructed
arguments from their pinned receipts. Their exact recorded ENV_KEYS are restored
in isolated child processes, including PATH and CPATH. Their original identity,
source, model, tool, guest, command, log, artifact, negative-control and terminal
checks must pass unchanged. No environment or path equality is relaxed. A read-only
trace captures the original computed identity for independent difference reporting.

A subprocess guard permits only source identity reads, tool version/component
queries and existing ELF symbolization. It rejects linking, compilation, reference
execution, hardware execution and shell commands. All suites retain their original
coverage limits; this wrapper adds no hardware coverage or performance claim.

Run from the source root:

```sh
python3 -B simulator/gsim/fixtures/fetch_prefix_archive_v1/test_revalidate.py
python3 -B simulator/gsim/fixtures/fetch_prefix_archive_v1/revalidate.py \
  --out simulator/gsim/fixtures/fetch_prefix_archive_v1/evidence-r1
```

Output is a new independent archive receipt, three audit logs, original receipt
and runner hashes, wrapper source hashes, actual current HEAD, every historical
anchor check, exact arguments/environment, and hashes of invoked read-only tools.
No old evidence is rewritten. Approximate budget: 10–30 seconds and under 1 MB.

Source-only negatives cover non-head binding changes, old host production-tree
mismatch, both required ancestry edges, source/tool/artifact mutations, original
validator rejection, environment reproduction and a HEAD change during audit.
