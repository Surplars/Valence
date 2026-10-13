# Near-term A: exact64 CPU locality and selected-half MAC

Base: `8e9a36c18a699e8b64830a97bb197f9fc52458bf` (tree `d498b36d8da24d06e9143428a0b7c042c88dff66`). All four new CPU fields default OFF. Existing two-issue/full-tag capacity, memory service, ISA and protection settings stay byte-for-data equal.

## Explicit entries

- `python3 fpga/next/board_timing64.py --output <fresh-directory>` validates the exact64 rollback, retaining existing T1 ON and selected-half OFF.
- `python3 fpga/next/board_near_term_a.py --output <fresh-directory>` validates A with 68 CPU options plus the separate physical T1 and selected-half generics.
- Add `--emit` only to request a native RTL export. Neither entry runs synthesis or implementation.

The four CPU additions are `fetchAcceptedPrefixValidation`, `alignedFetchSinglePage`, `factorCheckedNextAllowed` and `localTaggedResponseReady`. A has 172 core fields and 88 profile fields. The strict constructor bridge permits projecting only those four named false fields from rollback, then compares every original field against the hash-bound exact64 snapshot. `ooo.NearTermAProfileMain <fresh-directory> rollback|on` emits constructor reports. `ooo.NearTermAFullCpuMain` requires the exact ordered 68-option vector from `fpga/next/near-term-a-profile.json`; physical generics are never CPU options.

## Verified CPU scope

All active Scala source/test files compile. Seven affected suites pass 21 checks; this does not claim the unrelated historical test suite. Native construction reads the real DTA, LSU, packet and instruction-translation flags. Its 290 modules retain all other state/memory declarations and instance identities; exactly 130 second-page fetch register bits disappear. Only two qualified internal ports disappear, without changing affected external interfaces.

One new ON model was compared against the retained original exact64 model, without a new OFF build. Sv39 191,618 and Bare 198,642 inclusive cycles, all 105 original functional fields, complete metrics/stdout, AXI and supply streams, and final memory are equal at original phase zero. The same 36 ON model objects pass the existing hot/compressed NEMU and two PMP guests plus original negative controls. This establishes correctness/service parity for those bounded workloads, not an IPC or physical timing gain.

The compact receipt at `docs/evidence/near-term-a-qualified-r1.json` binds source and qualification identities and lists the immutable recovery packages. Source entry manifests remain preflight contracts; a fresh export does not inherit a qualified model or checkpoint. Original component sources, independent hosts, negative controls, native exports, and retained FAIL logs remain in their separately frozen recovery packages. Their ON constructor fixtures are not claimed runnable unchanged in the integrated tree: DTA/LSU now require the matching unified OooParams flag. No held-ALU B or manager routeWindow work is included.

## Affected checks and replay

From the repository root, `mill -i -j 1 IonSoC.test.testOnly ooo.NearTermAConfigSpec ooo.PlacedTimingConfigSpec ooo.HeadDrainClassSpec ooo.AddressLocalityConfigSpec ooo.FetchReadyDataClearSpec ooo.RetirementSlotSpec ooo.RetirementIntentBoardConfigSpec` runs the seven checked suites. The preexisting 151/61 and 159/71/72 historical constructor snapshots were not migrated or qualified; compiling their source is not a claim that those suites pass.

`python3 -m unittest discover -s fpga/next/native_mac_tests -v`, `python3 fpga/next/test_mac_netlist_review.py BindingTests -v` and `python3 fpga/next/test_timing64_export.py` exercise the host-only bridge, typed graph/session negatives, collector binding and exact64 entry. The two bundled lowered encoder files are complete, hash-matched source-lemma fixtures, not mapped checkpoints.

The qualified CPU recovery package includes the exact 616-file CPU closure, 295-file native view, generated 36-TU model and objects, actual hosts/guests/NEMU library, strict runners and retained raw/failure evidence. Its recovery instructions distinguish compatible binary replay, same-object relinking, and fresh recompilation with the original external compiler/header/baseline inputs. Do not weaken old-baseline validation to label a relocated run qualified.

## Physical MAC boundary

The source adapter and top wrapper retain default-OFF selected-half parameters. The explicit A entry requests both T1 and selected-half, separately from the CPU profile. The source/consumer bridge, fresh semantic mapped-role audit and exact export binding are required before any implementation claim. Host-only tool tests and matching emitted encoder hashes cannot establish that real synthesis consumed these generics or that a live mapped topology passed.

The generated `board/native-mac-mode.tcl` requires explicit Python execution setup before its synthesis/optimization/checkpoint wrappers: on Unix, `valence_native_mac_configure_python native [list /usr/bin/python3]`; on Windows Vivado, `valence_native_mac_configure_python wsl Ubuntu-24.04 [list wsl.exe] <Windows-stderr-directory>`. WSL paths and exit status are checked; stderr is retained. A consumed session is bound to one export identity and live design lifecycle. The host tests use mocked tools, so neither platform is live-qualified here.

Live Vivado/DCP/API qualification and setup/hold, reset recovery/removal, fastest-rate CDC and external PHY budgets remain outstanding. Raw125 managed-gate hold, REF500 terminal calibration recovery and RDY partial-pulse PHY qualification are not solved by this change. Historical source/checkpoint or dead-fall/CE-shape certificates do not qualify the new mapping.
