#!/usr/bin/env python3
"""Structural and wire-codec checks only; not HDL elaboration or CDC simulation."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / 'src/main/resources/debug/ValenceBscanDebugPort.sv'


def begin_blocks(text):
    """Find explicit always/begin blocks in this source, not an HDL elaborator."""
    for match in re.finditer(r'always\s*@\(([^)]*)\)\s*(?=begin\b)', text):
        depth = 0
        for token in re.finditer(r'\b(begin|end)\b', text[match.end():]):
            depth += 1 if token.group() == 'begin' else -1
            if depth == 0:
                yield match.group(1), text[match.end():match.end() + token.end()]
                break
        else:
            raise AssertionError('Unbalanced source always block')


def check_fault_phase(clean):
    blocks = list(begin_blocks(clean))
    sampled = [(edge, body) for edge, body in blocks if re.search(r'\bfault_sample\s*<=', body)]
    assert len(sampled) == 1, 'Fault sample must have exactly one clocked owner'
    edge, body = sampled[0]
    assert edge == 'posedge bscan_tck or negedge source_reset_n', 'Fault sample phase/reset mismatch'
    # Exact source topology is intentional: a gated sample, stale retained bit,
    # extra fault writer, or a different reset epoch requires explicit review.
    fault_body = re.sub(r'\bhandoff_(?:frame|length_ok|toggle)\s*<=\s*[^;]+;', '', body)
    assert ' '.join(fault_body.split()) == (
        'begin if (!source_reset_n) begin fault_sample <= 0; end else begin '
        'fault_sample <= update_overrun; end end'), 'Fault sample must capture raw sticky fault every positive TCK'
    assert len(re.findall(r'\bfault_sample\s*<=', clean)) == 2, 'Extra fault sample writer'

    # All raw-overrun references have a closed whitelist. Thus no continuous
    # alias, condition (CE), or RHS (D) can reconnect it to any negative-TCK
    # consumer, including hard-reset and bridge admission, through source logic.
    residual = re.sub(r'\breg update_length_ok, update_toggle, update_overrun;', '', clean)
    residual = re.sub(r'\bupdate_overrun\s*<=\s*[01]\s*;', '', residual)
    residual = re.sub(r'\bfault_sample\s*<=\s*update_overrun\s*;', '', residual)
    assert not re.search(r'\bupdate_overrun\b', residual), 'Raw UPDATE overrun outside its island and positive sample'
    assert len(re.findall(r'\bupdate_overrun\s*<=', clean)) == 2, 'Sticky UPDATE fault ownership changed'
    assert re.search(r'wire\s+accept_dmi\s*=\s*consume_update\s*&&\s*frame_ok\s*&&\s*request_is_dmi\s*&&\s*'
                     r'!protocol_error\s*&&\s*!fault_sample\s*&&\s*source_ready\s*;', clean), 'DMI fault admission guard changed'
    assert re.search(r'wire\s+visible_error\s*=\s*protocol_error\s*;', clean), 'Visible error must use negative-TCK sticky error'
    assert re.search(r'else\s+if\s*\(visible_error\s*\|\|\s*fault_sample\s*\|\|\s*!source_ready\)', clean), 'Capability fault admission guard changed'
    consumer = [body for edge, body in blocks
                if edge == 'negedge bscan_tck or negedge source_reset_n' and 'protocol_error' in body]
    assert len(consumer) == 1, 'Missing negative-TCK sticky fault owner'
    consumer = consumer[0]
    merge = re.search(r'if\s*\(fault_sample\s*&&\s*!hard_reset_command\)\s*protocol_error\s*<=\s*1\s*;\s*end\s*end\s*$', consumer)
    assert merge, 'Sampled fault must merge after CLEAR, with hard-reset priority'
    prefix = consumer[:merge.start()]
    depth = sum(1 if word == 'begin' else -1 for word in re.findall(r'\b(begin|end)\b', prefix))
    assert depth == 2, 'Sticky fault merge must be independent of command consumption'


def check_structure(text):
    clean = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    assert 'module ValenceBscanUserTransport (' in clean
    assert 'module ValenceBscanDebugPort #(' in clean
    assert 'parameter integer ENABLE = 0' in clean
    assert 'parameter integer JTAG_CHAIN = 0' in clean
    assert not re.search(r'\bValenceJtagTap\b', clean), 'A USER DR must not directly wrap a standalone TAP'
    assert len(re.findall(r'\bValenceDmiCdc\s*#', clean)) == 1
    assert 'always @(posedge bscan_drck or negedge source_reset_n)' in clean
    assert 'always @(posedge bscan_update or negedge update_reset_n)' in clean
    assert 'always @(posedge bscan_tck or negedge work_reset_n)' in clean
    assert 'always @(posedge bscan_tck or negedge update_reset_n)' in clean
    assert 'always @(negedge bscan_tck or negedge source_reset_n)' in clean
    assert "assign bscan_tdo = bscan_sel ? shift_frame[0] : 1'b0;" in clean
    assert 'if (shift_count < 65)' in clean and 'shift_count == 64' in clean
    assert 'update_toggle == update_ack' in clean and 'update_overrun <= 1' in clean
    assert 'update_selected <= bscan_sel && source_reset_n;' in clean
    assert 'update_ack <= update_seen;' in clean
    update = clean.split('always @(posedge bscan_update', 1)[1].split('reg [63:0] handoff_frame;', 1)[0]
    assert not re.search(r'\b(bscan_sel|source_reset_n|update_seen|work_reset_n)\b', update)
    assert 'wire update_reset_n = update_release[2];' in clean
    assert 'always @(posedge bscan_tck or negedge raw_reset_n)' in clean
    assert 'always @(negedge bscan_tck or negedge hard_reset_n)' in clean
    assert 'wire hard_reset_n = hard_release[2];' in clean
    assert '.s_req_payload(handoff_frame[40:0])' in clean
    assert 'update_sync <= {update_sync[0], handoff_toggle};' in clean
    assert 'handoff_frame <= update_frame;' in clean
    assert 'handoff_length_ok <= update_length_ok;' in clean
    assert 'handoff_toggle <= update_toggle;' in clean
    check_fault_phase(clean)
    assert 'SHREG_EXTRACT = "NO"' in clean
    for pin in ('CAPTURE', 'DRCK', 'RESET', 'SEL', 'SHIFT', 'TCK', 'TDI', 'UPDATE', 'TDO'):
        assert f'.{pin}(' in clean, f'Missing real primitive {pin} interface'
    disabled = clean.split('if (ENABLE == 0) begin: disabled', 1)[1].split('end else begin: enabled', 1)[0]
    assert 'always' not in disabled and 'BSCANE2' not in disabled
    assert all(f'assign {port} = 0;' in disabled for port in
               ('dmi_reset_n', 'dmi_req_valid', 'dmi_req_op', 'dmi_req_address', 'dmi_req_data', 'dmi_rsp_ready'))
    wrapper = clean.split('module ValenceBscanDebugPort #(', 1)[1].split('generate', 1)[0]
    assert not any(f'input wire {pin}' in wrapper for pin in ('tck', 'tms', 'tdi', 'trst_n'))


def main():
    check_structure(RTL.read_text())
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
