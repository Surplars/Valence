# Explicit A1 CPU selection in the common SoC

2026-10-24. This entry connects the `full-r1` and `full-r1-m3` CPU experiments to
the real `CommonMachinePlatform`. Both are labelled
`EXPERIMENTAL_NOT_TIMING_QUALIFIED`. The public `a1` choice still selects the
original Selected configuration. This is an integration and identity change,
not another CPU pipeline optimization or a 300 MHz qualification.

## Selection and unchanged platform

`CommonA1ExperimentalSelection` is a typed, default-absent selector. Only the A1
tile receives its chosen `config` and `memoryProfile`; the existing validator
checks the final inputs. Fabric, Home, DDR, managed peripherals, CMU and JTAG
continue to use the original `CommonCpuProfile` values. No old board-factory
guard is removed. I1, unknown candidates, changed clock tuples and changed common
transport geometry are rejected rather than selecting a fallback CPU.

| Setting | Public A1 | full-r1 | full-r1-m3 |
|---|---|---|---|
| Completion / branch | legacy / writeback-coupled | dual-owner / execution-mailbox | same as full-r1 |
| Fetch owners / reservoir | 1 / compacting | 2 / circular | same as full-r1 |
| LSU / data TLB | 2 / 8 | 4 / 16 | 4 / 16 |
| Completed canonical store forwarding | off | off | on |
| Registered M2 data translation | off | off | off |

All retain RV64GC, U/S/M, Sv39, AIA, 16 PMP entries, two-wide
rename/completion/retirement, ROB16/PRF48, 32 KiB two-way I/D caches, L1
read-MSHR/response/writeback credits 2/2/2, and the existing memory map. Shared
Home remains two clients, 1024 lines/four ways and acquire2/writeback2. DDR
remains four outstanding/two write credits. More LSU owners do not grant more
Home credits. CPU replies remain ordered without a new external return tag.

The common CPU/fabric boundary remains depth-16 Held-response CDC, coherent
source3/sink1, independent instruction source4, complete A/B/C/D/E and lineGrant,
and two scalar owner lanes. A1 coherent client0 remains inactive; data uses
client1. FENCE.I still waits for actual private/fetch/PTW/transport/Home/DDR drain.
Neither FIFO emptiness nor request acceptance substitutes for completion.

## Clock and runtime limits

The selector accepts only the existing A1 production tuple
CPU100/fabric250/TIME250 MHz or static boot50 tuple CPU50/fabric50/TIME250 MHz.
It does not create a board CPU300 profile, relax a timing target or run STA.
The existing `performance300-static` and production `boot50-dynamic` choices
remain I1-only. AON/UART50, DDR UI250 and network clocks are unchanged.

The already existing `CommonA1DynamicFixture` can explicitly receive the same
selector. It retains all experimental A1 runtime prerequisites, including real
debug/network/fixed-domain/maintenance/rate/telemetry ownership. Its behavioral
clock/PHY models and test rate bank are not production clock qualification.
The reused bank's CMU/network parameters are checked equal to A1 boot50; its
historical I1 name does not select an I1 CPU.

CMU's seven-resource ABI, CPU resource1 and independent TIME resource2 remain.
Telemetry retains both A1 retirement lanes, scalar0 MMIO accounting and client1
lineGrant refill accounting. The public DMI7/USER2 download path and its
arm/write/CRC/claim protocol remain; this does not add a general CPU debugger.

## Export and cache identity

The existing production exporter accepts the optional
`--experimental-a1-profile=full-r1|full-r1-m3`. Its positional CPU family remains
`a1` for firmware compatibility. Without the option, it remains public Selected.
It also accepts explicit `--emit-chirrtl-only` for real-platform structure
inspection. Such output is labelled `rtlFormat=CHIRRTL` and is rejected by board
admission. Normal output remains SystemVerilog.

Example invocation shape (the concrete validated paths are below):

```
platform.CommonMachinePlatformMain FRESH_OUTPUT a1 --vivado-memories \
  --compile-receipt=SUCCESSFUL_COMPILE.json --emit-chirrtl-only \
  --experimental-a1-profile=full-r1-m3
```

The runtime fixture exporter retains its original three arguments. An explicit
candidate additionally requires its selector and bound compile receipt:

```
platform.CommonA1DynamicMain FRESH_OUTPUT BANK0_HEX BANK1_HEX \
  --experimental-a1-profile=full-r1-m3 --compile-receipt=SUCCESSFUL_COMPILE.json
```

Both emit `microarchitecture-identity.json`. Production emission embeds the
same object as `cpuMicroarchitecture`, alongside actual TLB geometry and an
explicit selector/qualification label. The identity binds full effective
configuration/core parameters, memory policy, boundary, shared fabric
configuration, clock profile, actual nominal CPU/fabric/TIME/DDR_UI/AON/UART
tuple and static/experimental runtime mode. Candidate runtime mode must match
all three boundary capability flags. The template FPGA configuration's CPU rate
is not substituted for the actual SoC clock tuple. Configuration
leaves are strings, absent options are null; SHA256 covers recursively sorted,
compact UTF-8 JSON excluding only its own `identitySha256` field.

The Python gate checks this digest and the selector's actual required fields.
It permits only the named CPU-private differences from the shared configuration.
Model reuse must match the complete identity, not just `cpu=a1` or source SHA:
the same source contains both old and new CPU constructors. Output directories
must be fresh; existing output is neither overwritten nor silently cleaned.

Candidate exports require a `valence-scala-compile-v1` receipt, not merely an old
`exit=0`. Before and after emission they re-enumerate all main/test/HardFloat
Scala sources, resource roots and build inputs, verify the source manifest and
commit, and bind the complete ordered runtime classpath and every file's hash.
The bounded runner repeats these checks around external commands. Public
legacy export compatibility does not authorize candidate reuse.

Legacy records without identity can describe only the public CPU, never an
explicit candidate. New board configuration binds the identity profile/digest.
Board freeze/preflight still rejects both experimental candidates, regardless
of a CPU-leaf PASS receipt. This batch provides no bypass for physical admission.

## Bounded verification results

The shared compile and four pure Scala selection/identity tests passed after
one necessary compile repair. The first attempt failed only in the exporter:
an `Option.getOrElse` expression inferred `Object` rather than `ujson.Value`.
An explicit `ujson.Str` fixed it without changing hardware. The failed attempt
is retained at `build/a1-soc-integration-20261024-r1/compile.log`; successful
compile/spec/bound-input evidence is in `build/a1-soc-integration-20261024-r2/`.
All 51 synthetic Python identity/manifest/board tests also passed; their final
source-bound result is `build/a1-soc-selection-python-preflight-r2/`.

Two real production-platform CHIRRTL exports passed. The public A1 contains
two LSU slots and none of the three candidate-specific modules. The explicit
`full-r1-m3` contains four slots plus the circular fetch storage, branch mailbox
and completed-store forwarding modules. Both graphs retain reachable Home,
Held-response CDC and floating-point hardware, with equal shared fabric and
static boundary identities. Complete actual Java classpath/source binding
matched without relaxing the new receipt gate. Cross-selector cache reuse was
rejected even though both were emitted from the same compiled source.

One fresh `full-r1-m3` complete experimental-runtime SystemVerilog model was
then built. The pinned sv2v conversion retained all 797 `$fatal` and 797
`$error` sites; Icarus compiled the full model without diagnostics. The same
binary passed the unchanged bounded `telemetry_smoke` guest/service: one actual
DDR line/eight beats and Bare-M telemetry MMIO. Its one negative corrupts data
on actual DDR `R.fire`, observes the injection marker and reaches the unchanged
guest-failure PC `0x800000dc` with exit 1. It does not accept an arbitrary host
failure as a successful negative. No old public model was relabelled or rebuilt
as a second behavioral baseline.

The three immutable leaf receipts are under
`build/gsim/a1-experimental-soc-20261024-r1/`:

| Phase | Receipt | Status |
|---|---|---|
| Two actual SoC structures | `structures/receipt.json` | PASS_REAL_PLATFORM_STRUCTURES |
| One complete runtime model | `model/receipt.json` | PASS_REAL_PLATFORM_MODEL_BUILD |
| Same-model positive/data negative | `run/receipt.json` | PASS_EXPERIMENTAL_A1_SOC_BOUNDED_SMOKE |

Final run receipt SHA256:
`d1721610d9020187daf86eeadc5e525fac7c56d43ac254e1c54a33ece39fdc6a`.
It binds the model receipt, which binds the structural receipt and source/tool/
identity/RTL/binary artifacts. `full-r1` is covered by pure selection contracts,
not a separate whole-SoC model in this bounded batch.

The new `simulator/gsim/common/a1_experimental_soc_native.py` separates immutable
`structures`, `build` and `run` phases with fresh output and explicit previous
receipts, so a narrow repair cannot overwrite earlier evidence.

The Bare DDR/MMIO guest proves this assembled SoC executes the selected CPU.
It does not exercise M3 virtual-address forwarding, dynamic frequency changes,
full drain/network/PHY behavior, Linux, physical CDC/metastability, routed timing,
or board startup. Existing M3 CPU-level evidence remains separately scoped.
There is no matched-cycle SoC performance comparison here; the positive run's
75.52 microseconds of simulated time is not a speedup or frequency result.
Public defaults remain unchanged, and candidate board admission remains closed.
