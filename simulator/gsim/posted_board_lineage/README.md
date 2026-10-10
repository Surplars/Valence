# Passive AXI accounting host checks

This directory's ledger consumes edge samples. It does not drive ready, valid,
latency, ordering, memory data, or guest inputs. The wrapper must pass its actual
driven inputs and evaluated DUT outputs from the same tick before calling the
memory model's `sample` method. Call the ledger on every tick, including outside
the kernel and flush measurement windows; call `finish()` after actual drain.

`AxiSample` covers AR/AW ID, length and size; R ID/LAST; W LAST/strobes; B ID; and
all channel handshakes. Held metadata is checked only for fields present in that
sample. The ledger does **not** check missing address, data or RESP fields, nor
replace the original instruction, byte-memory, or bus protocol oracles.

Outstanding counts are **pre-edge accepted transaction owners**. Reads remain
owned through accepted RLAST, and writes through accepted B, including clocks
after WLAST. Window transitions record the ownership entering the new edge;
completions outside the ROI must still drain the same original owners. Channel
`no_offer` counts `!VALID` regardless of READY. It is not an inferred stall cause.

Byte metrics on this fixed 64-bit bus are distinct:

- `rWireBytes` / `accepted_r_wire_bytes`: accepted R beats times eight
- `rBytes` / `accepted_r_requested_payload_bytes`: the original accepted ARSIZE
  byte count for each accepted R beat
- `wWireBytes` / `accepted_w_wire_bytes`: accepted W beats times eight
- `wBytes` / `accepted_w_strobe_bytes`: population count of accepted WSTRB

JSON also emits `outstanding_sample: "pre_edge_accepted_owners"`. The earlier
ambiguous `accepted_r_bytes` and channel `not_valid` JSON keys are replaced by
the explicit names above. The existing C++ `rBytes`, `wBytes`, histogram and
channel counter member names remain available to the wrapper.

BVALID must name an AW whose complete W burst was accepted on an earlier edge,
even when BREADY is low. New AW+W+B and final W+B on the same edge are rejected.
An old completed owner may return B while the same ID is reused by a new AW/W
on that edge; the B belongs to the old owner. This is consistent with the actual
`harness/board_ddr_multiid.h` model, which schedules B three clocks after WLAST.
The existing same-edge AR/R accounting allowance is preserved; it is not a
claim about actual DDR minimum latency. W may be offered before AW acceptance,
but an accepted W beat requires an accepted AW owner in AW order. Live IDs
cannot be reused until the ledger observes the old owner's completion.

## Bounded host test

From the repository root:

```sh
g++ -std=c++20 -O0 -g -Wall -Wextra -Werror -pedantic \
  -fsanitize=address,undefined -fno-sanitize-recover=all \
  simulator/gsim/posted_board_lineage/axi_accounting_test.cpp \
  -o /tmp/posted-axi-accounting-host
ASAN_OPTIONS=detect_leaks=0 /tmp/posted-axi-accounting-host
```

The independent test authors manual samples and literal expected counts. Its
four positive scenarios check exact bytes, all channel partitions, means,
histograms, pre-edge occupancy, carry-in/out, zero strobes, narrow reads,
different-ID read return order, same-ID turnover, and outside-window drain.
Thirty-one negative samples must reject with the intended diagnostic: orphan
R/W/B, early and same-edge B, premature/missing LAST, held ID/LAST/strobe changes,
live-ID reuse, invalid strobes, undrained owners and incomplete/reentered windows.

These are standalone C++ host checks. They do not compile Scala, emit a model,
invoke GSIM, run a board guest, measure hardware throughput, or qualify a real
DDR controller, PHY, or clock crossing.
