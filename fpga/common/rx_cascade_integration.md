# Default-off RX cascade integration

The common top now exposes RX_CASCADE_STAGE_DELAY_PS, default -1. The default
retains the original single TIME/FIXED1100 input delay. No PHY, board constraint,
clock/reset/calibration or serializer behavior is changed. input_delay and
input_ddr keep their exact original receive[n] hierarchy names; only enabled
cascades add receive[n].extra_delay.output_delay (ODELAYE3, SLAVE_END).

The two delay stages use the SAME explicit parameter. The IDELAY becomes MASTER
when enabled. Both share VALENCE_RGMII, ref500, reset and EN_VTC=1. Because the
master must retain its exact native path, integration is inline, not an instance
of a standalone characterization wrapper. No new production source-list member
is required. Characterization wrappers and test stubs are not dependencies of
this inline integration and are not included in the minimal source delivery.

## Recorded whole-SoC route, explicit 475/475 candidate

The r35n3 whole-SoC run used the explicit top-level override
RX_CASCADE_STAGE_DELAY_PS=475. It completed routing with 189542/189542 nets
routed and zero reported routing errors. The CPU300 and fabric250 timing
requirements were unchanged; no clock relaxation or false-path waiver is
introduced by this change. This result applies to the explicit candidate, not
to the default single1100 configuration. A 550/550 probe was legal but added
too much delay; tiny-probe clock latency/slack is not substituted for SoC timing.

Recorded native timing results:

- Global hold WHS: +0.010 ns, zero failing hold endpoints.
- RX worst hold slack: +0.210 ns; RX worst setup slack: +0.039 ns.
- Global setup WNS: -2.869 ns; setup TNS: -42420.566 ns.
- CPU setup WNS: -2.869 ns; fabric setup WNS: -2.665 ns.
- Asynchronous recovery worst slack: -2.038 ns, still failing.

The native routed checkpoint was saved on 2026-10-23 at 12:01:26 UTC+8:

- Path: `E:\VM\Share\Valence-rtl\r35n3\routed.dcp`
- Size: 77,784,590 bytes.
- SHA256: `5bd16c730d016ed649ba1b1505fde8c8ca59cbdb18bd5610f53942f64201bb1c`

This checksum identifies the DCP, not a timing report. The checkpoint and raw
native reports are not included in this source-only delivery. Positive hold
slack does not establish timing closure: setup and asynchronous recovery still
fail. No maximum-frequency qualification, bitstream generation, board validation
or signoff is claimed. Original rate/reset/CDC qualification remains required.
The production/default parameter remains -1; 475 is not made the default.

Tests:
- python3 fpga/common/test_rx_cascade_integration.py
  Independent pre-change hashes prove TX, IDELAYCTRL, IDDRE and the rest of the
  common shell unchanged; actual changed pad hash is checked against admission.
- The common_trispeed_pad_tb on the new r35 emitted TriSpeedRgmiiTx passed with
  default-off configuration: 6 frames, 774 bytes, 32474 half checks, 1036 duplicate
  checks, 2 reset epochs. Behavioral substitutes are NOT vendor timing proof.

The source SHA admission changed only to the actual reviewed pad bytes. Baseline
manifests/checkpoints are not rewritten and remain historical artifacts.
