# Timing batch r2 qualification

The r2 candidate combines qualified query selection (A), aligned fetch permission
and bounded request frontier (B), and canonical store event registration with
matching lifecycle handling (C). Generic defaults are false. Both explicit
profiles retain every option from the prior 43-option maxperf configuration:
100 MHz, proof rows 2, early-load credits 2, tagged store returns, LSU 4, DTLB 16,
DMA line entries 4, trispeed MAC, USER2, and all three memory overlap options.
A+C has B off; A+B+C has B on. Neither profile is promoted as the physical winner.

## Source identity and scope

- Base commit: `1e90af966c15d871d2544469174acba78473113b`.
- Qualified complete source tree: `3dfac0c63332c60c3ebe5d63b3e9c0d1fe282bb4`.
- Complete patch SHA256: `162dd7789927706037390582e5cdc52eba13911ca31de1445ce5e2870491dd6a`.
- The readonly A constructor getter in r2 enables an actual-instance audit. The
  backend FIR is byte-identical to the executed r1 backend FIR, SHA256
  `c31ed27e4ffdcc6ed40a4d129922b4b16f326dfa9fe04a09a8ad9deec5f2f6ba`.

Final constructor arities are OooParams 154, FpgaNextConfig 64, and cache 22.
Actual reports read the constructed A bank mode, both C endpoints, both B
endpoints, and B optional-port presence. Five focused configuration tests reject
both C half-enabled directions, both actual A bank/parameter mismatch directions,
and missing B ports. The C producer registration, headDone exclusion, and
consumed-result disposal share one configuration flag. Existing unrelated
historical arity guards were inventoried rather than broadly rewritten.

The qualified source includes the reconstructed tagged CLI intent and known
MAC/BSCAN Tcl collection and inversion compatibility corrections. The user's
actual eight-file local script diff was not available in this cloud checkout.
Preserve that local diff and compare it explicitly before later integration;
this candidate does not claim to import or byte-preserve those eight files.

## Executed gates

| Gate | Evidence and result | Boundary |
|---|---|---|
| Source/host checks | Existing A 43/44-option tests, five combined CLI checks, six MAC collector checks, BSCAN checks, Python syntax and diff checks passed | Light checks only |
| Actual combined Scala/configuration | Production/test compilation and five focused constructor tests passed | Historical source tree above |
| A+C real backend | Two proof rows/two credits, LSU4; 13 official generated units passed ASan+UBSan; positive execution and five actual-corruption negatives passed | Real decoded backend lifecycle; distinct from whole-board qualification |
| r2 getter bridge | Incremental config/emit passed; emitted backend FIR byte-for-byte equals r1 | No normalized or inferred FIR equality |
| Fresh pristine baseline | 37 official units; Sv39/Bare and three original negative controls passed | Fresh exact 1e90 source, all 43 options |
| A+C matching CPU | 37 official units; Sv39/Bare and three original negative controls passed | A/C on, B off |
| A+B+C matching CPU | 36 official units; Sv39/Bare and three original negative controls passed | All three stages on |
| Same-model NEMU | Baseline/AC/ABC each passed two short inputs and PC/GPR/memory negative controls | Physical integer M-mode only; separate correctness ROM |
| Native emitted structure | Strict retained-declaration census and exact hierarchy comparison | Emitted syntax; not mapped resources or timing |

Each CPU run used the same original COPY guest, host, physical service law, and
independent 105-field architectural, byte, and owner checks. The three memory
options remain on in every profile. Baseline cycle totals were measured afresh;
historical totals were never used as acceptance criteria. Every compiler job was
serial. Both candidate source freezes were rechecked after execution.

| Profile | Sv39 inclusive cycles | Bare inclusive cycles | Sv39 MiB/s | Bare MiB/s |
|---|---:|---:|---:|---:|
| Fresh pristine 1e90 | 196,524 | 197,722 | 63.605463 | 63.220077 |
| A+C | 191,618 | 197,722 | 65.233955 | 63.220077 |
| A+B+C | 191,618 | 194,153 | 65.233955 | 64.382214 |

AC and ABC improve this Sv39 case by 4,906 cycles; ABC improves the Bare case by
3,569 cycles. Architectural retirement count is 40,984 with the same PC hash.
All cases preserve the independent byte/owner checks; traffic may change with
scheduling. These two bandwidth inputs do not establish the best control-flow
configuration. The separate NEMU inputs show ABC takes 5 and 8 more cycles than
baseline/AC, respectively, including correctness boot/service work.

B also has a larger isolated taken-branch cost: its frozen C.J microbenchmark
takes 34 cycles with the stage off and 48 with it on, an increase of 14 cycles
(about 41.2%). The measured prefix contains 14 taken C.J instructions, matching
one added cycle per taken instruction; both variants accept the same two packets.
This component result remains part of qualification. Neither COPY input regresses
when B is enabled in the combined candidate, but those bandwidth results do not
erase or bound the C.J/control-flow penalty.

The NEMU checker reuses the exact 37/37/36 generated-object inventories and
unchanged reference client. It checks 108 hot-input and 24 compressed/control-flow
guest PCs, all 32 GPRs after each entire retirement edge, and 4,194,368 final
memory bytes per case. The compressed input includes C.JALR/C.JR, mixed 2/4-byte
instruction boundaries, integer branches, and an explicit store/load/fence tail.
Nine corruption controls fail for the intended PC/GPR/memory mismatch. Its
five-instruction correctness ROM replaces an old UART store with NOP while
preserving the independently initialized GPR/link state. This ROM differs from
the unchanged two-instruction COPY ROM. Original timer and strict-service failures
are retained. No reference resynchronization or speculative NEMU step is used.

Native lowering of the same matching-board BoardSocGsim FIR with pinned firtool
1.135.0 and identical options retains 179 additional scalar
register bits in A and 240 in C, or 419 for AC. B adds 147, making 566 for ABC.
Retained array bits are unchanged. C's size MSB is constant-fed; declared state
is not equivalent to mapped flip-flop count. Exact hierarchy checks and parser
negative controls support the census, not a physical resource or timing claim.
The census covers 239 definitions and 383 explicit instances; all 118 array
instances have unchanged geometry and helper bytes. It is not the managed-native
complete-board export; the separate BSCAN change and MAC Tcl collectors are not
included as physical resource deltas.
The manual emitted-FIR audit confirms intended A/C register cuts and also records
remaining live cancellation, consume, context, shape, and translated-PA cones.

BSCAN is a separate qualified source/script component with an estimated 69
additional source-level flip-flops. This is not a mapped FF result and is not
included in the matching-board native scalar census. Raw sticky UPDATE overrun
to negative-TCK acceptance, immediate status UPDATE-to-DRCK behavior, and related
clock min/max payload/control paths remain live timing obligations. No exception
or source-stage result makes those paths physically qualified.

The MAC change in this batch only repairs collection of FIFO leaf constraints.
Known TX/IDELAY reset recovery issues remain unfixed here. The subsequent T1 reset
release design is a separate candidate and is excluded from this frozen source,
its tests, and all counts in this report.

## Reproduction and remaining limits

The review overlay is separate from the qualified source. Its plan-only
preparation helper reconstructs the historical pinned-base-plus-patch tree in a
new directory and checks the full tree identity. The helper's light validation
includes an actual replay and rejection of existing destinations, dirty input,
nested output, and modified patch bytes. It does not run or qualify hardware.

The existing combined backend and CPU runners, guest, service host, and oracles
are tracked in the replayed tree. Independent A/B/C component wrappers and oracles
are source-bound in the Library archives indexed by `components.json`; historical
cache/tool/absolute-path bindings require explicit validation when relocated.
The NEMU adapter likewise requires an audited same-hash dependency remap on a
different machine. No automatic cross-machine remap or new-HEAD one-click full
gate is claimed.

No Sv39/CSR/privilege/permission NEMU coverage, exhaustive B context/flush
reachability proof, floating-point workload, concurrent CPU/DMA acceptance,
physical CDC, FPGA implementation, LUT/FF mapping, routed slack, Fmax, bitstream,
or full regression follows from these gates. Native production-board export and
physical qualification remain separate tasks. No source or flags were changed
to prepare this report.
