#!/usr/bin/env python3
"""Post-run analysis only. Never generates, compiles, or executes a DUT."""
import collections, hashlib, json, pathlib, statistics
if not __debug__:
    raise SystemExit("Qualification gates require Python assertions; optimized Python is forbidden")
HERE = pathlib.Path(__file__).resolve().parent
state = json.loads((HERE / 'receipt.json').read_text())
assert all(m['status'] == 'COPY_TWO_MODES_AND_NEGATIVE_CONTROLS_PASS' for m in state['modes'].values())

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write(p, value):
    p.write_text(json.dumps(value, indent=2) + '\n')

def stats(values):
    return {'count': len(values), 'min': min(values), 'max': max(values), 'median': statistics.median(values),
            'sum': sum(values)} if values else {'count': 0, 'min': None, 'max': None, 'median': None, 'sum': 0}

def histories(work):
    lines = {}
    for text in (work / 'axi-events.tsv').read_text().splitlines():
        word = text.split('\t')
        assert word[0] == 'AXI'
        cycle, channel, *payload = map(int, word[1:])
        offset = payload[0] if channel in (0, 1) else payload[-1]
        assert 0 <= offset < 2147483648
        pa = 0x80200000 + offset
        line = lines.setdefault(hex(pa & ~63), {'ar': [], 'aw': [], 'r': [], 'w': [], 'b': []})
        kind = ['ar', 'aw', 'r', 'w', 'b'][channel]
        line[kind].append([cycle, *payload])
    write(work / 'axi-full-pa-data-histories.json', lines)
    return lines

summary = {'schema': 'adoption-cpu-analysis-v1', 'baseline_identity': state['baseline'], 'cases': {},
           'limitations': ['Full CPU E-handshake cycle is UNKNOWN; component hold-E qualification remains distinct.',
                           'Zero known-error owners means that condition was NOT_EXERCISED by this CPU guest.',
                           'No native resource, synthesis, routed timing, physical DDR, CDC, or board result is established.']}
for case in ['bare', 'sv39']:
    modes = {}
    histories_by_mode = {}
    for mode in ['off', 'on']:
        work = HERE / mode / case
        row = state['modes'][mode]['cases'][case]
        for name, expected in row['raw'].items():
            assert sha(work / name) == expected
        h = histories(work)
        histories_by_mode[mode] = h
        attachments = {}
        successors = []
        origins = collections.Counter()
        lines = {}
        first_r = {}
        for text in (work / 'supply-events.tsv').read_text().splitlines():
            kind, *words = text.split('\t')
            v = list(map(int, words))
            if kind == 'DEMAND_ATTACH':
                cycle, region, ident, slot, generation, address, pa, ticket, word, lo, hi, live, known = v
                assert ident not in attachments and (address & ~63) == pa and ((address >> 3) & 7) == word
                attachments[ident] = {'id': ident, 'cycle': cycle, 'region': region, 'slot': slot, 'generation': generation,
                    'word_address': address, 'full_pa': pa, 'word_offset': word, 'ticket': ticket, 'tag_lo': lo, 'tag_hi': hi,
                    'refill_cycle': None, 'actual_cpu_response_cycle': None, 'successors': []}
            elif kind == 'ATTACH_REFILL':
                cycle, region, ident, slot, generation, address, ticket, lo, hi, error = v
                a = attachments[ident]
                assert [slot, generation, address, ticket, lo, hi] == [a[k] for k in ['slot', 'generation', 'word_address', 'ticket', 'tag_lo', 'tag_hi']]
                assert a['refill_cycle'] is None
                a['refill_cycle'] = cycle
                a['error'] = error
            elif kind == 'ATTACH_CPU_RESPONSE':
                cycle, region, ident, generation, address, ticket, lo, hi, data, flags = v
                a = attachments[ident]
                assert [generation, address, ticket, lo, hi] == [a[k] for k in ['generation', 'word_address', 'ticket', 'tag_lo', 'tag_hi']]
                assert a['actual_cpu_response_cycle'] is None and a['refill_cycle'] is not None and cycle > a['refill_cycle']
                a.update(actual_cpu_response_cycle=cycle, response_data=data, response_flags=flags)
            elif kind in ('ATTACH_SUCCESSOR_ALLOC', 'ATTACH_SUCCESSOR_ISSUED'):
                cycle, region, ident, generation, pa, next_generation, next_pa, live, first = v
                a = attachments[ident]
                assert a['generation'] == generation and a['full_pa'] == pa and pa != next_pa
                successors.append({'kind': kind, 'cycle': cycle, 'region': region, 'attachment': ident,
                    'next_generation': next_generation, 'next_pa': next_pa, 'adjacent_next_line': next_pa == pa + 64,
                    'pre_edge_live_mask': live, 'old_first_r_known_at_event': first or None})
            elif kind == 'OWNER_FIRST_R':
                cycle, region, generation, pa, ident, source = v
                assert generation not in first_r
                first_r[generation] = cycle
            elif kind in ('ALLOC', 'WB_CAPTURE'):
                cycle, region, slot, generation, pa, pf, store, *rest = v
                origin = ('store' if store else 'read') if pf else 'demand'
                origins[f'{region}:{origin}:{kind}'] += 1
                key = f'{region}:{origin}:{pa:#x}'
                lines.setdefault(key, {}).setdefault(kind, 0)
                lines[key][kind] += 1
            elif kind == 'CONSUME':
                cycle, region, store, pa, *rest = v
                origins[f'{region}:{"store" if store else "read"}:RESIDENT_USEFUL'] += 1
        for a in attachments.values():
            assert a['refill_cycle'] is not None and a['actual_cpu_response_cycle'] is not None
            a['first_external_r_cycle'] = first_r.get(a['generation'])
        for successor in successors:
            a = attachments[successor['attachment']]
            successor['refill_lead_cycles'] = a['refill_cycle'] - successor['cycle']
            successor['actual_cpu_response_lead_cycles'] = a['actual_cpu_response_cycle'] - successor['cycle']
            first = a['first_external_r_cycle']
            successor['first_external_r_lead_cycles'] = None if first is None else first - successor['cycle']
            assert successor['refill_lead_cycles'] > 0
            if successor['kind'] == 'ATTACH_SUCCESSOR_ISSUED':
                assert successor['pre_edge_live_mask'] == 3
            a['successors'].append(successor)
        write(work / 'attachment-histories.json', list(attachments.values()))
        write(work / 'origin-full-pa-counts.json', lines)
        assert len(attachments) == int(row['adoption']['attached']) == int(row['adoption']['actual_cpu_response'])
        result = row['result']
        roi = int(result['cycles'])
        tail = int(result['clean_tail'])
        payload = int(result['bytes']) * int(result['reps'])
        successor_stats = {}
        for kind in ['ATTACH_SUCCESSOR_ALLOC', 'ATTACH_SUCCESSOR_ISSUED']:
            selected = [s for s in successors if s['kind'] == kind and s['adjacent_next_line']]
            successor_stats[kind] = {metric: stats([s[metric] for s in selected if s[metric] is not None]) for metric in
                ['refill_lead_cycles', 'actual_cpu_response_lead_cycles', 'first_external_r_lead_cycles']}
        modes[mode] = {'roi_cycles': roi, 'flush_cycles': tail, 'roi_plus_flush_cycles': roi + tail,
            'payload_bytes': payload, 'roi_payload_MiBps_at_100MHz': payload * 100000000 / roi / 1048576,
            'inclusive_payload_MiBps_at_100MHz': payload * 100000000 / (roi + tail) / 1048576,
            'traffic_regions': row['traffic_regions'], 'adoption_regions': row['adoption_regions'],
            'resident_useful_roi': int(result['pf_useful']), 'attachment_total_all_phases': len(attachments),
            'origins': dict(sorted(origins.items())), 'successor_leads': successor_stats,
            'oracle': row['oracle'], 'known_error_path': row['adoption']['known_error_path'],
            'artifacts': {name: sha(work / name) for name in ['axi-full-pa-data-histories.json', 'attachment-histories.json', 'origin-full-pa-counts.json']}}
    assert modes['off']['attachment_total_all_phases'] == 0
    assert state['modes']['off']['cases'][case]['calibration'] == 'EXACT_105_FIELDS_AND_COMPLETE_AXI_TRACE'
    off, on = modes['off'], modes['on']
    source_reload = []
    traffic_delta = []
    before, after = histories_by_mode['off'], histories_by_mode['on']
    for pa in sorted(set(before) | set(after), key=lambda x: int(x, 16)):
        old = before.get(pa, {k: [] for k in ['ar', 'aw', 'r', 'w', 'b']})
        new = after.get(pa, {k: [] for k in ['ar', 'aw', 'r', 'w', 'b']})
        delta = {k: len(new[k]) - len(old[k]) for k in old}
        if any(delta.values()):
            traffic_delta.append({'full_pa': pa, 'off': {k: len(old[k]) for k in old}, 'on': {k: len(new[k]) for k in new}, 'delta': delta})
        if 0x80400000 <= int(pa, 16) < 0x80410000 and delta['ar'] > 0:
            source_reload.append({'full_pa': pa, 'off_ar': len(old['ar']), 'on_ar': len(new['ar'])})
    write(HERE / (case + '-per-full-pa-traffic-deltas.json'), traffic_delta)
    assert not source_reload, ('ON adds source reloads', source_reload[:8])
    ratio = on['roi_plus_flush_cycles'] / off['roi_plus_flush_cycles']
    summary['cases'][case] = {'modes': modes, 'actual_off_calibration': 'EXACT_105_FIELDS_AND_COMPLETE_AXI_TRACE',
        'inclusive_cycles_delta': on['roi_plus_flush_cycles'] - off['roi_plus_flush_cycles'],
        'inclusive_cycle_reduction_pct': (1 - ratio) * 100,
        'inclusive_throughput_change_pct': (1 / ratio - 1) * 100,
        'source_lines_with_extra_AR': source_reload,
        'per_full_pa_traffic_delta_sha256': sha(HERE / (case + '-per-full-pa-traffic-deltas.json'))}
write(HERE / 'performance-summary.json', summary)
print('ANALYSIS_PASS both COPY cases, original OFF calibration, complete traffic histories and distinct attachment semantics')
