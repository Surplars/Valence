# Corrected-source native storage cost

Fresh native OFF and ON exports from model source
`0658f2d4a543ba5849498af626eec0a248363540`, tree
`cc1d50b223fc0b6ebec448292ce8964986b56af2`, passed the strict literal hierarchy
census. These are production FpgaNextMain exports with no lineage probes.
The complete profile and original tool/dependency hashes were bound before export.
Only the posted selector differs between OFF and ON.

| Reachable production state | OFF | ON | Difference |
|---|---:|---:|---:|
| Scalar declared bits | 85417 | 91947 | 6530 |
| Array declared bits | 705223 | 708155 | 2932 |
| Total additional bits | — | — | 9462 |

The translated request queue grows from 8×185 to 8×429 bits (1952 additional
bits), and the four-entry proof queue adds 4×245=980 bits. Together these account
for the array delta. Scalar additions comprise the owner (3065), cache wrapper
(619), acquire observation (136), and CPU/translation transport (2710) bits.
These categories sum to 6530; cross-cutting proof/token/epoch fields must not
be added again. The same-source export includes all reachable production
instances; separately reported definition totals are not substituted for it.

Compared with the preceding source `afe85a27`, every OFF emitted module is
byte-identical. ON changes only the IntegerBackend module; scalar and array
state, RAM helper bytes and ports have zero additional change. This is a fresh
measurement of the corrected source, not reassignment of the earlier result.
Raw equality and zero storage delta do not establish behavioral equivalence.

The native export disables verification logic, so assertion-only state is
removed; retained functional state is counted. External blk_mem_gen_0 and
BUFGCE state is excluded with their exact instance paths checked. Literal
state bits do not predict mapped flip-flops, LUTs, BRAM use, routed timing,
clock frequency or board performance.

OFF emission completed in 91.46 seconds, ON in 15.06 seconds. The first OFF
host post-processing attempt rejected two tracked source resource files as
unrecognized external classpath dependencies. Its failed receipt remains
preserved. A separately hash-bound host correction verifies those resources
against the frozen source inventory, with no source/tool/profile change and
no repeated OFF emission. Every saved census was independently recomputed,
and both the original evidence and frozen source remained unchanged.

[Machine-readable summary](posted-store-native-cost.json).

- Native plan SHA256: `6ddd1bae82e1185fa601c80cc07f3fa456642ef362d79b4b185bea098fba9a06`
- Summary SHA256: `4e8d5acfb578e73d3234fa83870702960ba94e2ec116955900b50981242208e5`
- Saved-artifact recheck SHA256: `6f98885ed6eeaed36c227fad11b7c22305d9af5b70839d8052f6ef9819e1df53`
- OFF export receipt SHA256: `ee2bf1d1b62038b2ba61545d7031dacdb52d7bbfc7c9e6debe6055b743cabbc4`
- ON export receipt SHA256: `caf2af5dbf85486f1971bea29d082eaef295c30088438052e4cc8e7fb0900d9f`

Full declarations, hierarchy maps, per-instance differences, source and tool
inventories, export logs, failed/recovered post-processing receipts and checker
sources are retained in the separate posted-seal-native-cost-r1 evidence packet.
