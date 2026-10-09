#!/usr/bin/env python3
"""Structural and wire-codec checks only; not HDL elaboration or CDC simulation."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / 'src/main/resources/debug/ValenceBscanDebugPort.sv'


def main():
    text = RTL.read_text()
    clean = re.sub(r'//[^\n]*', '', text)
    assert 'module ValenceBscanUserTransport (' in clean
    assert 'module ValenceBscanDebugPort #(' in clean
    assert 'parameter integer ENABLE = 0' in clean
    assert 'parameter integer JTAG_CHAIN = 0' in clean
    assert not re.search(r'\bValenceJtagTap\b', clean), 'A USER DR must not directly wrap a standalone TAP'
    assert len(re.findall(r'\bValenceDmiCdc\s*#', clean)) == 1
    assert 'always @(posedge bscan_drck or negedge work_reset_n)' in clean
    assert 'always @(posedge bscan_update or negedge work_reset_n)' in clean
    assert 'always @(negedge bscan_tck or negedge source_reset_n)' in clean
    assert "assign bscan_tdo = bscan_sel ? shift_frame[0] : 1'b0;" in clean
    assert 'if (shift_count < 65)' in clean and 'shift_count == 64' in clean
    assert 'update_toggle == update_seen' in clean and 'update_overrun <= 1' in clean
    for pin in ('CAPTURE', 'DRCK', 'RESET', 'SEL', 'SHIFT', 'TCK', 'TDI', 'UPDATE', 'TDO'):
        assert f'.{pin}(' in clean, f'Missing real primitive {pin} interface'
    disabled = clean.split('if (ENABLE == 0) begin: disabled', 1)[1].split('end else begin: enabled', 1)[0]
    assert 'always' not in disabled and 'BSCANE2' not in disabled
    assert all(f'assign {port} = 0;' in disabled for port in
               ('dmi_reset_n', 'dmi_req_valid', 'dmi_req_op', 'dmi_req_address', 'dmi_req_data', 'dmi_rsp_ready'))
    wrapper = clean.split('module ValenceBscanDebugPort #(', 1)[1].split('generate', 1)[0]
    assert not any(f'input wire {pin}' in wrapper for pin in ('tck', 'tms', 'tdi', 'trst_n'))

    # Independent fixed-wire format exercise, including >32-bit Tcl field split.
    vectors = 0
    for op in range(4):
        for address in (0, 1, 2, 0x10, 0x25, 0x7f):
            for data in (0, 1, 0x80000000, 0x89abcdef, 0xffffffff):
                frame = (0x5642 << 48) | (1 << 44) | (address << 34) | (data << 2) | op
                fields = [op, data, address, 0, 1, 0x5642]
                serial = [bit for value, size in zip(fields, (2, 32, 7, 3, 4, 16))
                          for bit in [(value >> index) & 1 for index in range(size)]]
                rebuilt = sum(bit << index for index, bit in enumerate(serial))
                assert len(serial) == 64 and rebuilt == frame
                # Right-shifting, injecting serial bits at the MSB, yields the
                # same 64-bit frame after exactly 64 clocks.
                shifted = 0
                for bit in serial:
                    shifted = (shifted >> 1) | (bit << 63)
                assert shifted == frame
                vectors += 1
    report = {'status': 'passed_structure_and_codec_only', 'codec_vectors': vectors,
              'rtl_sha256': hashlib.sha256(RTL.read_bytes()).hexdigest(),
              'hdl_elaboration_verified': False, 'native_multiclock_verified': False,
              'amd_unisim_verified': False, 'physical_cdc_signoff': False, 'board_verified': False}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
