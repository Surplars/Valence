# Immutable head-drain classification

The optional `predecodedHeadDrain` flag defaults to false. When enabled, an accepted rename saves one immutable classification bit per ROB row. Existing pending/system, readiness, recovery and full-token rules still authorize its use. Reuse overwrites stale bits on the same edge and with the same lane priority as the instruction payload.

The classification preserves the existing broad PMP, return, virtual-memory and FENCE.I predicates, including original/expanded instruction selection. It does not add an ISA legality filter.

The independent decode gate checked 366,590 vectors and 1,466,360 outputs; 21 mutations were rejected. The actual default52 OFF/ON backend pair checked dual acceptance, head movement, wrap/reuse, real internal fault kills and stale-bit masking; both observed-output mutations were rejected. ASan and UBSan passed.

Pure production native output adds 16 declared one-bit registers for 16 ROB rows. All other 96 modules, prior register declarations, top ports and PRF/payload bindings remain unchanged. The drainFetch consumer uses the saved bit; other consumers still read the head instruction. Two rename decoders and an indexed-bit lookup are added. This is a native structural result, not a synthesized resource or timing result.

The only whole-CPU tested combination is original default52 plus this flag. Sv39 and Bare remain 191,618 and 194,153 inclusive cycles. Their full stdout and supply/AXI traces match the retained default52 bytes exactly. The original three fault controls passed. The same generated objects also passed the original two short NEMU inputs at 1,847 and 958 cycles and their three negative controls, without reference resynchronization. These NEMU cases cover physical integer M-mode execution only.

Future-home/LRU54 plus this flag has no whole-CPU qualification. No timing, frequency or speedup is claimed. [head-drain-results.json](head-drain-results.json) records the tested production hashes and relative result identities; subsequent public CLI/configuration checks must be identified separately from these runs.

## Public source entrypoints

The public source adds strict `--predecoded-head-drain` parsing to `fpga/next/export.py` and the native/GSIM option validator. The flag remains absent from `board_final` and the unchanged default52 manifest. Native export fingerprints include `HeadDrainClass.scala` and the current constructor audit. `actual-head-drain.json` reports the requested flag and actual production row presence/width; it adds no hardware observations.

The current profile serializer and actual audits accept only the reviewed appended fields (profile 73, core 160, unchanged cache 23 and DDR 9) and retain complete actual/requested product equality. These source bridges do not change archived results or historical 151-field qualifications. The old historical source-identity bridges are intentionally unchanged and do not qualify this new source.

The retained narrow GSIM runner is `python3 simulator/gsim/head_drain_class.py` (use `--help` for the explicit stages and tool paths). Focused checks are `ooo.HeadDrainClassSpec`, `ooo.HeadDrainConfigSpec`, and `python3 simulator/gsim/test_head_drain_cli.py`. The configuration test checks complete independent default52 rollback for the single flag and optional future-home/LRU54 plus the flag, with eager-prefix disabled. The 54+flag combination remains UNTESTED as hardware. Public-entry checks belong to this source version separately from the prior narrow/native/CPU evidence above.

Public-source validation passed after the entrypoint bridges: all 200 production and 351 test Scala sources compiled, six focused Scala tests passed, and four Python CLI/fingerprint tests passed. The generic ON constructor also checked actual backend parameters and sixteen one-bit rows. Its CHIRRTL differs from the tested ON file only in exactly 10,460 source-location suffixes: two test-wrapper files move by one source line with unchanged columns. Every functional IR line, port and state declaration is otherwise identical. This is an elaboration bridge, not another CPU execution; raw FIR byte equality is explicitly false.
