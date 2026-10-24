#!/usr/bin/env python3
"""Read-only netboot timing breakdown. No sockets, MMIO, or board access."""
import argparse
import json
import math
from pathlib import Path
import re

FIELDS = re.compile(r'\b([A-Za-z_][A-Za-z_0-9]*)=([^\s]+)')
TICKS = ('rx_wait_ticks', 'copy_ticks', 'stream_crc_ticks', 'tx_ack_ticks',
         'ram_crc_ticks', 'ram_flush_ticks', 'ram_sweep_ticks',
         'verify_callback_ticks', 'drain_ticks', 'mac_stop_ticks', 'final_ack_ticks')
HOST_SECONDS = ('read', 'send', 'ack_wait', 'other', 'pacing', 'elapsed')

def number(value):
    try:
        v = float(value[:-1] if value.endswith('s') else value)
    except ValueError:
        return None
    return v if math.isfinite(v) and v >= 0 else None

def analyze(text):
    result = {'schema': 1, 'board_runs': [], 'host_runs': [], 'notes': [
        'User-reported A1/I1 rates need matched payload, ROM/bit/source hashes and actual clock profiles.',
        'Host ACK completion is not final RAM verification or successful boot.',
        'Host mean_acked_payload_mib_s includes wait/pacing and the VLD header, not Ethernet wire line rate.',
        'Board RX wait includes DMA/MMIO/descriptor handling, not just wire wait.',
        'Board timing fields overlap (final ACK/drain/verify); do not add them to infer total time.',
        'Pending-final-verify ROM prints NB totals before the separate final RAM CRC; zero ram_crc_ticks is not proof verification was omitted.',
        'No inferred bottleneck is a measured CPU/DDR/PHY cause.']}
    for line in text.splitlines():
        if 'NB totals ' not in line and 'TFTP STATS ' not in line:
            continue
        pairs = FIELDS.findall(line)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError('duplicate timing field in one record')
        if 'NB totals ' in line:
            hz = number(fields.get('timebase_hz', ''))
            total = number(fields.get('transfer_ticks', ''))
            size = number(fields.get('length', ''))
            if hz is None or hz <= 0 or total is None or size is None:
                raise ValueError('NB totals requires finite positive timebase and nonnegative transfer_ticks/length')
            seconds = total / hz
            row = {'raw': fields, 'transfer_seconds': seconds,
                   'payload_mib_per_second': size / (1024*1024) / seconds if seconds else None,
                   'phases_seconds': {}, 'shares_of_transfer': {}}
            for key in TICKS:
                if key not in fields:
                    continue
                ticks = number(fields[key])
                if ticks is None:
                    raise ValueError('invalid board timing '+key)
                row['phases_seconds'][key] = ticks / hz
                row['shares_of_transfer'][key] = ticks / total if total else None
            # Only these four directly account for receive-loop services.
            candidates = {k: row['phases_seconds'][k] for k in
                          ('rx_wait_ticks','copy_ticks','stream_crc_ticks','tx_ack_ticks')
                          if k in row['phases_seconds']}
            row['largest_recorded_receive_service'] = max(candidates, key=candidates.get) if candidates else None
            result['board_runs'].append(row)
        elif 'TFTP STATS ' in line:
            seconds = {}
            for key in HOST_SECONDS:
                if key not in fields:
                    continue
                value = number(fields[key])
                if value is None:
                    raise ValueError('invalid host timing '+key)
                seconds[key] = value
            elapsed = seconds.get('elapsed')
            size = number(fields.get('bytes_acked',''))
            if elapsed is None or size is None:
                raise ValueError('TFTP STATS requires finite elapsed/bytes_acked')
            row = {'raw': fields, 'seconds': seconds,
                   'mean_acked_payload_mib_s': size / (1024*1024) / elapsed if elapsed else None,
                   'pacing_share': seconds['pacing'] / elapsed if elapsed and 'pacing' in seconds else None,
                   'eof_acked': None}
            if 'eof_acked' in fields:
                if fields['eof_acked'] not in ('yes','no'):
                    raise ValueError('invalid eof_acked (expected yes/no)')
                row['eof_acked'] = fields['eof_acked'] == 'yes'
            result['host_runs'].append(row)
    if not result['board_runs'] and not result['host_runs']:
        raise ValueError('no NB totals or TFTP STATS records; need complete logs, not screenshot rates')
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('logs',nargs='+',type=Path)
    ap.add_argument('--out',type=Path)
    args=ap.parse_args()
    result={'inputs': [{'path':str(p), 'analysis':analyze(p.read_text(errors='replace'))} for p in args.logs]}
    data=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if args.out:
        with args.out.open('x') as f: f.write(data)
    else:
        print(data,end='')
if __name__=='__main__':
    main()
