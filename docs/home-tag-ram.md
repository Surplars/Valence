# Banked concurrent-home tag RAM candidate

This batch changes `MixedCoherentLineHome` and `NonBlockingCoherentLineHome`.
The serialized legacy home remains unchanged. No MSHR/writeback counts, issue
width, default options, coherence ordering or pipeline latency are changed.

## Storage and port contract

Directory slots already encode the cache set, so storing those bits again in
the tag is redundant. The tag starts at `6 + setBits` rather than bit 6. A new
GrantAck assertion checks that the reserved directory slot still names the
set of the acquisition address. Full physical addresses and compact-tag
aperture qualification remain intact.

At the selected 512-line/two-way geometry and 33 retained address bits, logical
tag capacity falls from 512×27=13,824 to 512×19=9,728 bits. The candidate uses
two 256×19 asynchronous-read memories, each with one explicit write port.
Only E/GrantAck installs a tag. Ownership remains a separately resettable FF
array; tag memory does not need an initialization/reset sweep.

The logical read clients are explicit:

1. Live upstream request, or saved maintenance address when registered
   `maintenance == mProbeSend`.
2. The first Release C beat, independent of the maintenance lookup.
3. An assertion-only Acquire A lookup, retaining the independent duplicate
   ownership check without inserting A.ready/fire into a functional RAM
   address path.

The functional clients must not be replaced with a single C-priority lookup:
an unrelated release could otherwise change the saved probe recheck and let
maintenance proceed without its required probe. Sharing upstream and saved
maintenance is safe because their results are consumed in disjoint registered
states. There is no new arbitration stall or read pipeline register.

CHIRRTL has three reads and one write per way. Native SystemVerilog emitted
with verification layers disabled prunes the assertion-only cone: way 0 retains
two read addresses and way 1 retains one. The latter needs no separate release
tag comparison because the valid protocol's second way is selected when the
first way misses. The GSIM version retains the independent assertions.

These are emitted logic/memory-port facts, not FPGA mapping results. Vivado
must establish actual LUTRAM replication, primitive shape, INIT behavior,
register fallbacks and routing cost. The state-selected address mux and RAM
outputs remain part of the 100MHz timing review; the current narrow margin is
not assumed to survive this refactor.

## Bounded independent acceptance

`simulator/gsim/home_tag_ram.py` passed six baseline and six candidate GSIM
models under ASan/UBSan, with byte-identical public protocol/cycle transcripts:
both homes, full and compact 16-line geometries, and compact 512-line/two-way
geometries. The fixture aperture crosses 4 GiB to test retained physical bit 32.

Directed coverage includes same-set aliases/replacement, E+disjoint first C
while upstream is held, both same-victim and unrelated ReleaseC racing a saved
probe recheck, dirty/clean release, held Grant/probe, denied Grant, reset and
high-bit/out-of-aperture traffic. Four independent negatives per model reject
bad data, an already-owned acquisition, an out-of-aperture acquisition and an
out-of-aperture release:48 expected rejections across the A/B pair.

The independent integer relation check covers 348,160 indexed-tag comparisons
over 20 geometries, including high 64-bit endpoints. It rejects omitted-range
qualification and dropped-tag-bit mutations. This host check supplements,
rather than replaces, the hardware protocol oracle.

Receipts and original logs/FIR:
`build/gsim/home-tag-ram-cloud-r1/{baseline,candidate}`.
Selected 512-line native SV A/B inputs and hashes:
`build/fpga/home-tag-ram-cloud-r1`.
No Vivado, board programming or physical-performance result is included.
