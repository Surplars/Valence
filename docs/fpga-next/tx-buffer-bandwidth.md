# Opt-in two-bank TX bandwidth

Fixed source: the post-bb48 TX candidate. This is measured single-clock simulation with independent Ethernet byte/FCS oracles; it is not routed timing or board/network-stack throughput.

## Architecture and unchanged defaults

`QueuedGmiiFrameTx` has two complete-frame banks in one 1024×32 synchronous RAM, one write port and one read port. Collection overlaps serialization; the next complete packet is prefetched during the existing 12-byte IFG. Aborts retire stored owners one per cycle and separately drain an admitted partial producer through LAST, without resetting a packet/DMA pointer. The same logic scales byte-enable timing at 10/100/1000.
`TriSpeedManagedGmac(..., txFrameSlots = 2)` is explicit. Its default remains 1. The newly exported single-bank `GmiiFrameTx.sv` is byte-identical to the prior tri-speed freeze. The test is an architecture choice, not four parallel TX engines.

## Saturated native 32 input

Both profiles receive continuously asserted native data across 16 consecutive frames, with only DUT ready applying backpressure. The candidate reaches exactly body bytes + 24 byte-times between wire-frame starts (8 preamble/SFD,4 FCS,12 IFG) at all three speeds. Startup/drain are excluded from the steady interval measurement.
| MAC body bytes | Single-bank 125MHz cycles/frame | Two-bank cycles/frame | Throughput gain |
|---:|---:|---:|---:|
| 60 | 101 | 84 | 20.24% |
| 1514 | 1919 | 1538 | 24.77% |
| 2048 | 2586 | 2072 | 24.81% |

## Actual packet DMA and posted descriptor ownership

Both profiles instantiate the real production `EthernetPacketDma`, native adapter and frame transmitter with four posted descriptors. Each body size sends 24 frames, measures 20 steady intervals, and uses the identical ready memory model with 7-cycle responses and four memory credits. Descriptor addresses/results are checked before every POP; a DDR buffer is reused only after completion relinquishes its DMA owner.
| MAC body bytes | Single-bank cycles/frame | Two-bank cycles/frame | Throughput gain | DMA-stream/wire overlap cycles, old→new |
|---:|---:|---:|---:|---:|
| 60 | 115 | 84 | 36.90% | 0→219 |
| 1514 | 2297 | 1538 | 49.35% | 0→8591 |
| 2048 | 3096 | 2072 | 49.42% | 0→11650 |

The DMA benchmark gains more than the unlimited-native-input case because it also removes serialization of the DMA’s narrow local-RAM stream readout with wire transmission. DDR reads already overlap some wire activity in the baseline; this change does not invent additional memory credits or independent DMA engines. Read-beat counts remain 192/4560/6144 for 60/1514/2048-byte bodies and peak outstanding credits remain 4.
At 1 Gb/s the candidate’s active-wire utilization is 72/84=85.71% for minimum frames and 2060/2072=99.42% for 2048-byte bodies. These fractions include preamble/FCS but exclude mandatory IFG. MAC-body goodput is 714.29 and 988.42 Mb/s respectively; they are protocol-model limits, not measured IP/TFTP goodput.

For the actual posted-DMA baseline, active-wire duty is 72/115=62.61% for 60-byte bodies and 2060/3096=66.54% for 2048-byte bodies, increasing to 85.71% and 99.42% with two banks. The unlimited-native-input baseline instead measures 72/101=71.29% and 2060/2586=79.66%; these are different producer models and must not be mixed in a speedup claim. All duty measurements use the observed steady wire-start interval, not input acceptance or startup/drain duration.

## Correctness and resource evidence

- 239 tri-speed frame cases pass with 15 TX aborts and all six directed rate changes.
- 21 additional bank-ownership cases cancel 36 active/queued/partial owners, target each prefetch stage and verify exact packet reuse afterward.
- 56 actual-DMA functional cases pass per profile, including posted completion identity, randomized memory backpressure/read/write faults, bad FCS rejection and partial tail masks.
- Every independent mismatch injection fails as expected.
- Both production SystemVerilog exports pass. The candidate adds 2048 packet-storage bytes: 512×32 becomes 1024×32, still exactly one synchronous read and one write port. Synthesis BRAM mapping/count, LUT/FF timing and routed clock/I/O timing are not established by the RTL census.

## Reproduction

From the repository root, select an existing verified tool cache and run:

```bash
export VALENCE_CLOUD_ENV=/path/to/verified/tool-cache
export VALENCE_GSIM_SOURCE=/path/to/verified/gsim-source
source scripts/cloud/env.sh
python3 simulator/gsim/tri_speed_tx_buffers.py --tag NEW_UNIQUE_TAG
```

The runner does not rely on the historical cloud checkout path. The runner records source/harness hashes before/after, model/executable hashes, positive/negative logs, both exports and measured comparisons. Saved passing receipt: `build/gsim/tri-speed-tx-buffers-double-r1/receipt.json`.
