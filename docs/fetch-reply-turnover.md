# Registered fetch owner turnover and identity capture

`staged-fetch-turnover` is an opt-in candidate based exactly on
`staged-fetch-feedback`, with `fetchReplyTurnover` and
`fetchIdentityTranslation` enabled. It does not enable the separate
`staged-load-issue` experiment. Existing profiles and defaults are unchanged.

## Contract

The registered translation adapter remains single-owner. A new request may be
accepted while the prior registered reply is consumed; a held reply never
permits replacement. The prior response data, error mask and page-fault mask
remain stable through that handshake. New-owner initialization wins over old
reply cleanup. `idle` remains true only in the actual idle state, preserving
fetch-drain and CSR serialization.

At acceptance, PC, requested mask, privilege, SATP, SUM and MXR are captured
atomically. Machine privilege or SATP Bare means architectural identity
translation: capture the PC and modulo-64-bit PC+4 as physical addresses, then
use the existing registered physical-send/PMP stage. A zero requested mask
returns an empty reply without a physical access. Nonidentity modes retain the
existing translation sequence, including cross-page fault priority. No TLB-hit
bypass, live-context selection, or late frontend consume-credit path is added.

PMP still samples at the first physical offer, whether or not that offer is
accepted, and the saved allowed/error/page masks remain locked under
backpressure. PA capture, physical request, physical response and virtual
reply boundaries remain registered. Capacity is unchanged; the turnover
optimization removes the idle admission bubble, while identity capture removes
translation-only cycles for Bare/M-mode requests. Neither bypasses physical
memory latency.

## Verification and interpretation

The two flags can be enabled separately on the existing registered-head
configuration for independent tests. The permission test wrapper accepts
`turnover` and `identity`; its original default fixture remains unchanged.
Architectural identity-mode tests must supply identity addresses, unlike the
original isolation fixture, which intentionally injects arbitrary translations.

`frontend_perf.py --profile staged-fetch-turnover --firmware-dir <baseline-firmware>`
selects the candidate for same-BIN board comparison, and `rv64gc_board.py`
accepts the profile for its bounded RV64GC smoke. Use 100 MHz, UART 460800,
two issue, RV64GC/FPU and 2 GiB DDR for production-profile evidence. No timing,
FPGA, Linux, or broad application speedup is implied by this source change.
Bare/M-mode gains must be distinguished from general Sv39 owner-turnover gains.

## Final bounded owner-stream evidence

The 20-owner mixed stream was checked in aligned and unaligned modes for both
baseline and candidate under ASan/UBSan. The candidate performs 19 simultaneous
old-reply/new-request replacements in each stream. Independent instruction,
error, page-fault, context/PMP capture, held-reply and reset/drain checks pass;
all four injected-corruption controls fail as required. Receipts are under
`build/gsim/fetch-stream-candidate-20261007/` and
`build/gsim/fetch-stream-baseline-tightened-20261007/`.
`ooo.FetchTurnoverTimingSpec` passes its three configuration checks.

The same-BIN turnover-only CoreMark experiment reduces ticks 834653→790688
(5.267%). Its short pointer-chase control regresses 3998→4014 ticks (0.400%).
Do not extrapolate Bare-mode translation removal to Sv39: translated-mode
correctness has focused oracle coverage, but no Sv39 workload speedup is claimed.

Reproduce the four stream cases in a fresh tag (from the repository root):

```sh
PYTHONPATH=simulator/gsim python3 - <<'PY'
from run import setup, test, BUILD
from control_stage import negative
gsim, cxx = setup(False)
for candidate in (0, 1):
    for aligned in (0, 1):
        name = f'fetch-stream-NEW_TAG-c{candidate}-a{aligned}'
        assert not (BUILD / name).exists()
        params = ['2', 'retimed']
        if aligned:
            params.append('aligned')
        if candidate:
            params += ['turnover', 'identity']
        output = test(gsim, cxx, name, 'ooo.InstructionPermissionGsimMain',
            'InstructionPermissionGsim', 'instruction_permission_stream.cpp',
            parameters=tuple(params), defines={'PACKET_WORDS': 2,
                'RETIMED_PERMISSIONS': 1, 'ALIGNED_PACKET': aligned,
                'FETCH_REPLY_TURNOVER': candidate,
                'FETCH_IDENTITY_TRANSLATION': candidate})
        negative(output / 'run', (),
            'independent multi-owner response oracle mismatch',
            output / 'negative.log')
PY
```
