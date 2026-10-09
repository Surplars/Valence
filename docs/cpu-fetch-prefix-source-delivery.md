# CPU fetch-history / older-prefix source candidate

This source delivery adds an explicitly selected, bounded CPU candidate to the
existing dev tree. It preserves the existing V4/stage2-pacing-v2 firmware tools,
MAC/JTAG sources and published default profile. It does not replace an existing
FPGA implementation, board image or timing qualification.

## Select the candidate explicitly

The default Selected profile keeps two LSU entries. Physical load ingress,
previous fetch packet and older-prefix retirement remain OFF. The candidate
uses LSU4, physical load ingress, both frontend/retirement options, and coherent
line DMA with four owners and zero yield. Virtual precheck/prechecked flow,
tri-speed media and JTAG are not enabled by this selection; the existing full
legacy MAC remains in the board shell.

From the repository root, this command validates the intended profile without
building a model, elaborating RTL or invoking Vivado:

```sh
python3 -B fpga/next/export.py --output build/fpga-next/cpu-fetch-prefix-candidate \
  --lsu-entries 4 --physical-load-ingress-flow \
  --fetch-previous-packet --load-order-older-retire \
  --dma-line-transfers --dma-line-entries 4 --dma-line-yield-cycles 0
```

Adding `--emit` requests a new native export after configuring the existing
repository toolchain. It does not run synthesis or qualify the resulting board.
Do not reuse an old implementation checkpoint or ROM identity as proof for a
changed candidate. No new local implementation task is implied by publication.

The original same-source simulation result is documented in
[fetch-history-retire-bandwidth.md](fetch-history-retire-bandwidth.md): hot 8 KiB
read takes 2191 versus 3210 ticks at a nominal 100 MHz parameter (+46.51%
throughput). History alone did not improve it. The combination adds 197 literal
scalar declaration bits (133 history + 64 complete older-prefix token), with no
array-bit change. These are simulation and native-source counts, not mapped
area, routed timing, Windows transfer performance, or measured board throughput.
The original diagnostic is archived GCC14.2, not the unavailable board GCC13.2
binary. Store-owner merging is a separate experiment and is absent here.

## Exact qualification and integration boundary

The immutable compact [proof index](evidence/cpu-fetch-prefix-qualified-20261009.json)
is copied byte-for-byte from the qualified package:

- Source commit: `f23aed8ed367b168c0a7a4baf17ac5e2913bc3c6`
- Production anchor: `2288c7f008e9d6440e8a28e339da28152b54892a`
- Their identical complete `src/main` tree: `c6e69b6b539bc36285b602a39fae32cb76ea012c`
- PROOF_INDEX SHA256: `aa551eae11e13ecdc6a69f426025cd7798d608e8cd9126a45b332bd1ca000c5c`

This delivery overlays the full delta from `66c06d7` onto public dev
`9791cde13481b610fef3843b7e13e3b1e7b4ce3d`, baseline tree
`ed50662447e5494e8401bc3e879cd0e74aeb3f84`. Every qualified production path retains
its exact bytes. Existing public `src/main/scala/ip/debug/HartDebugContract.scala`
is additionally preserved; it is an unattached contract/adapter source and no
other production source references its declared types/modules. Thus the merged
complete production tree is different from the frozen qualification tree.
Existing MAC/JTAG exporter integration is also preserved alongside the new CPU
options. The final publication manifest binds the exact merged bytes and modes.

The archived simulations and native exports qualify their recorded f23/2288
source, not a new full hardware run of this merged tree. No integration hardware
rerun, mapped PPA, STA, routed timing, CDC or board result is claimed here. Active
CPU/DMA coverage is functional, not a throughput comparison; data-PMP negatives
cover loads, not every store/AMO fault. Linux performance, same-binary short
CoreMark performance and exhaustive ISA/interrupt schedules remain outside this
checkpoint. All new switches stay OFF by default.

## Fresh host checks and external proof inputs

The tracked Python/C++/assembly/linker/schema sources include the reusable
fixture inputs. These small examples use synthetic source-only data and do not
need a compiled GSIM model:

```sh
python3 -B simulator/gsim/fixtures/cpu_order_replay_history_v1/test_validation.py
python3 -B simulator/gsim/fixtures/cpu_order_replay_history_v1/test_lineage.py
python3 -B simulator/gsim/fixtures/fetch_context_qualification_v1/test_validation.py
python3 -B simulator/gsim/fixtures/fetch_prefix_dma_pmp_v1/test_validation.py
python3 -B simulator/gsim/fixtures/fetch_prefix_nemu_v1/test_fixture.py
python3 -B simulator/gsim/fixtures/fetch_prefix_archive_v1/test_revalidate.py
python3 -B simulator/gsim/fixtures/monitor_bandwidth_fetch_prefix_v2/test_profile.py
```

Full original-ELF replay and execution-proof audits require separate archived
models, executables, receipts, original diagnostic ELF and reference/tool caches.
The `monitor_bandwidth_*` `test_compare.py` tests also read an archived positive
trace; they are not advertised as fresh-checkout tests. The optional real-hot
closure group in `test_cpu_retire_prefix_provenance.py` skips if its original
receipt is unavailable. Source-only tests do not substitute for execution proof.

The preserved fixture READMEs include hash-bound historical commands and original
workspace/tool-cache paths. Treat those code blocks as archive reconstruction
records, not portable commands for an ordinary published checkout. In particular,
this applies to fetch_context_qualification_v1, fetch_prefix_dma_pmp_v1,
monitor_bandwidth_fetch_history_v1 and monitor_bandwidth_fetch_prefix_v2. Their
source hashes are deliberately unchanged; this guide supplies the current
publication entry point. Configure tool locations explicitly for any new build
with the repository's scripts/cloud/env.sh and its supported cache variables.

## Strict historical revalidation

External package: `Valence-cpu-fetch-prefix-qualified-20261009-r1`.

- `evidence.tar.gz`: 235389072 bytes; SHA256
  `c4c4430329673088ff3dfeee5ddd502d46151aa0c5507602843e411816523cc0`
- `source.bundle`: SHA256
  `1acee4c821f5fb68219f53d98c2e72792da93156364adcb8a469a81c0f177b63`

These archives are not in Git. The bundle preserves the full local historical
commit chain; the public source-only commit intentionally has different ancestry.
Revalidating the frozen executions requires the bundle's historical checkout,
matching original archive layout and exact fingerprinted tools/reference caches.
Those caches are external prerequisites, not included installations. Restoring
files to arbitrary new locations is not promised to pass the strict path and
environment checks.

The original direct audits rejected later host HEAD metadata. Their failed logs
are preserved. The separate fetch_prefix_archive_v1 wrapper first proves complete
production-tree equality, historical/current ancestry and all original source,
artifact, command and environment hashes. Only historical `host_head` metadata
may then be normalized, with both original and actual audit HEAD recorded.
No original receipt, validator or terminal oracle is rewritten. The wrapper
correctly rejects this merged public checkout: its complete production tree and
ancestry differ. Do not bypass those checks or present this metadata revalidation
as a fresh hardware execution.
