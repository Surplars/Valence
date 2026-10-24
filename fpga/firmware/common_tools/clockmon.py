#!/usr/bin/python3
"""Read-only coherent Valence telemetry. Window averages, never instant/peak rates."""
import argparse
import json
from pathlib import Path
import sys
import time

EVENTS = {
    'cpu': ['edges', 'retire_lane0', 'scalar_lane1_request_fire', 'coherent_A_fire',
            'coherent_A_stall', 'complete_64byte_lineGrant', 'lineGrant_stall', 'no_retire'],
    'fabric': ['edges', 'AXI_AR_fire', 'AR_stall', 'AXI_AW_fire', 'AW_stall',
               'AXI_R_beats', 'AXI_W_beats', 'R_stall'],
}
SNAPSHOT_PROFILES = {
    'i1': {'cpu_abi': 1, 'retirement_lanes': 1, 'scalar_request_lane': 1},
    'a1-runtime': {'cpu_abi': 2, 'retirement_lanes': 2, 'scalar_request_lane': 0},
    'fabric_abi': 1,
}
CPU_PROFILE_FIELDS = {'retirement_lanes', 'scalar_request_lane'}


def integer(value, limit=(1 << 64) - 1):
    if not isinstance(value, str) or not value or value.startswith(('-', '+')):
        raise ValueError('invalid unsigned integer')
    result = int(value, 16 if value.startswith('0x') else 10)
    if not 0 <= result <= limit:
        raise ValueError('integer out of range')
    return result


def parse_snapshot(text):
    result = {}
    required = {'sequence', 'flags', 'valid', 'counter_bits', 'reference_hz', 'window',
                'timestamp', 'measured_hz'} | {f'{kind}{i}' for kind in ('delta', 'total') for i in range(8)}
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        domain = words.pop(0)
        if domain not in EVENTS or domain in result:
            raise ValueError('unknown or duplicate domain')
        raw = {}
        for word in words:
            key, value = word.split('=', 1)
            if key in raw:
                raise ValueError('duplicate field')
            raw[key] = value
        # Only the CPU row has these two driver-validated descriptor labels.
        # An older I1 driver has neither. Never accept only one or infer A1
        # from counter values, a machine name, or an unknown field.
        explicit_profile = domain == 'cpu' and bool(set(raw) & CPU_PROFILE_FIELDS)
        expected = required | CPU_PROFILE_FIELDS if explicit_profile else required
        if set(raw) != expected:
            raise ValueError('snapshot fields differ from the reviewed profile text')
        data = {k: integer(v) for k, v in raw.items() if k != 'measured_hz'}
        lanes = 1
        if domain == 'cpu':
            pair = (data['retirement_lanes'], data['scalar_request_lane']) if explicit_profile else (1, 1)
            if pair not in ((1, 1), (2, 0)):
                raise ValueError('unsupported retirement/scalar request lane pairing')
            lanes, scalar_lane = pair
            data.update(retirement_lanes=lanes, scalar_request_lane=scalar_lane,
                        snapshot_profile=('i1' if lanes == 1 else 'a1-runtime'),
                        profile_source=('explicit_driver_fields' if explicit_profile else 'legacy_i1_text'),
                        meter_abi=lanes)
        else:
            data['meter_abi'] = 1
        bits, window, ref = data['counter_bits'], data['window'], data['reference_hz']
        if not 4 <= bits <= 32 or ref != 50000000 or not 0 < window <= 0xffffffff:
            raise ValueError('invalid counter width/reference/window')
        mask = (1 << bits) - 1
        # Same conservative no-ambiguous-wrap limit as the reviewed driver.
        if window * (6 * lanes if domain == 'cpu' else 5) > mask or data['flags'] & ~7:
            raise ValueError('ambiguous counter-wrap window or unknown flags')
        for i in range(8):
            if data[f'delta{i}'] > mask or data[f'total{i}'] > mask:
                raise ValueError('counter exceeds width')
        valid = (data['flags'] & 5) == 1
        if data['valid'] != int(valid):
            raise ValueError('valid field disagrees with flags')
        if bool(data['flags'] & 2) != (data['delta0'] == 0):
            raise ValueError('edge-stopped flag disagrees with delta0')
        expected_hz = data['delta0'] * ref // window
        if valid:
            if integer(raw['measured_hz']) != expected_hz:
                raise ValueError('measured_hz disagrees with exact counter/window ratio')
        elif raw['measured_hz'] != 'unavailable':
            raise ValueError('invalid window must not advertise a measured frequency')
        data['measured_hz'] = expected_hz if valid else None
        data['window_seconds'] = window / ref
        data['valid'] = valid
        events = list(EVENTS[domain])
        if domain == 'cpu' and lanes == 2:
            events[1], events[2], events[7] = ('retire_total_two_lanes',
                                              'scalar_lane0_request_fire', 'neither_lane_retired')
        data['events'] = {name: {'window_count': data[f'delta{i}'],
                                'average_per_second': data[f'delta{i}'] * ref / window if valid else None,
                                'raw_total_modulo': data[f'total{i}']}
                          for i, name in enumerate(events)}
        if domain == 'cpu':
            metric = 'retire_lane0_per_cycle' if lanes == 1 else 'retire_total_two_lanes_per_cycle'
            data[metric] = data['delta1'] / data['delta0'] if valid and data['delta0'] else None
            data['line_refill_mib_s'] = data['delta5'] * 64 * ref / window / 1048576 if valid else None
        result[domain] = data
    if set(result) != set(EVENTS):
        raise ValueError('both CPU and fabric snapshots are required')
    for field in ('sequence', 'timestamp', 'window'):
        if result['cpu'][field] != result['fabric'][field]:
            raise ValueError('two banks are not one coherent publication')
    return result


def discover():
    candidates = [p for p in Path('/sys/bus/platform/drivers/valence-clockmon').glob('*/snapshot') if p.is_file()]
    if len(candidates) != 1:
        raise RuntimeError('Exactly one enabled clockmon device required; legacy A1 lacks this hardware. Check DT/module/profile status.')
    return candidates[0]


def render(snapshot, previous=None):
    seq = snapshot['cpu']['sequence']
    return {'schema': 1, 'publication_sequence': seq,
            'new_publication': previous is None or seq != previous,
            'sequence_state': ('first' if previous is None else 'repeated' if seq == previous else
                               'advanced' if seq > previous else 'reset_or_wrap'),
            'sample_semantics': 'latest coherent hardware window average, not instantaneous or time since last poll',
            'total_semantics': 'raw modulo counters, never subtracted across unbounded polling gaps',
            'flags_semantics': 'bit0 published-valid; bit1 no measured edges; bit2 currently invalidating, not an overflow indicator',
            'axi_semantics': 'handshake beat counts, not byte strobes, useful payload bytes or DDR peak bandwidth',
            'ipc_semantics': ('CPU retire_lane0 only; scalar_lane1_request_fire is not a second retirement lane'
                              if snapshot['cpu']['retirement_lanes'] == 1 else
                              'CPU retirement sum of two independently synchronized lanes, modulo counter width; '
                              'scalar_lane0_request_fire is a request, not retirement'),
            'domains': snapshot}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--file', type=Path, help='Decode saved snapshot text instead of accessing hardware')
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 100000 or not 0.05 <= args.interval <= 3600:
        parser.error('count1..100000 and finite interval0.05..3600 required')
    path, previous = args.file or discover(), None
    for index in range(args.count):
        snapshot = parse_snapshot(path.read_text())
        print(json.dumps(render(snapshot, previous), sort_keys=True), flush=True)
        previous = snapshot['cpu']['sequence']
        if index + 1 < args.count:
            time.sleep(args.interval)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f'CLOCKMON_UNAVAILABLE: {error}', file=sys.stderr)
        raise SystemExit(1)
