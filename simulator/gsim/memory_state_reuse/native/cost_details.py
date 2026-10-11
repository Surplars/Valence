#!/usr/bin/env python3
"""Exact field removal and emitted writer alternatives, no technology mapping."""
import json, re
from pathlib import Path
import run_native as b

analysis = b.HERE/'analysis'
summary = b.read(analysis/'summary.json')
baseline = b.read(analysis/'off-off-census.json')
backend_bits = baseline['modules']['IntegerBackend']['scalar_reg_bits']
total_bits = baseline['production_reachable_totals']['scalar_reg_bits']
rows = {}
for mode, values in b.MODES.items():
    census = b.read(analysis/(mode+'-census.json'))
    records = census['modules']['IntegerBackend']['scalar_registers']
    removed = []
    if mode != 'off-off':
        differences = b.read(analysis/(mode+'-comparison.json'))['reachable_path_differences']
        b.require(len(differences) == 1 and differences[0]['path'].endswith('/backend'), 'unexpected state owner change')
        removed = differences[0]['scalar_register_differences']
        b.require(all(row['before_width'] > 0 and row['after_width'] == 0 for row in removed), 'unexpected added or resized scalar state')
        expected = {}
        for slot in range(64):
            if values[0]:
                expected[f'queue_{slot}_renamed_token_index'] = 6
            if values[1]:
                expected[f'loadBeat_{slot}'] = 61
                expected[f'loadLanes_{slot}'] = 8
        b.require({row['name']:row['before_width'] for row in removed} == expected, 'removed field set differs from exact intended groups')
    text = (b.OUT/mode/'rtl/IntegerBackend.sv').read_text()
    assignments = {}
    for group in ['storeAddress', 'storeByteLanes', 'loadBeat', 'loadLanes']:
        counts = [len(re.findall(r'\b'+group+'_'+str(slot)+r'\s*<=', text)) for slot in range(64)]
        assignments[group] = dict(per_row_counts=counts, total=sum(counts))
    for group in ['storeAddress', 'storeByteLanes']:
        b.require(assignments[group]['per_row_counts'] == [3 if values[1] else 2]*64, 'shared writer alternatives changed unexpectedly')
    delta = summary['table'][mode]['scalar_delta']
    rows[mode] = dict(backend_scalar_declarations=len(records), removed_scalar_declarations=len(removed), added_scalar_declarations=0,
                     removed_scalar_registers=removed, backend_scalar_reduction_percent=-100*delta/backend_bits,
                     production_scalar_reduction_percent=-100*delta/total_bits,
                     nonblocking_writer_statements=assignments,
                     backend_sv_bytes=summary['structure_indicators'][mode]['raw_sv_bytes'],
                     backend_sv_byte_delta=summary['structure_indicators'][mode]['raw_sv_bytes']-summary['structure_indicators']['off-off']['raw_sv_bytes'])
result = dict(status='PASS_EXACT_REMOVED_FIELD_AND_WRITER_CENSUS', modes=rows,
              interpretation=['Address reuse adds one ordinary-load writer alternative to every existing storeAddress/storeByteLanes row: two emitted writer branches become three.',
                              'The two preexisting preparation writers remain higher-priority emitted branches; the load writer is gated by the final LSU store/atomic class.',
                              'No RAM helper, address/data port, latency, geometry, or source hierarchy instance changes.',
                              'Address-only IntegerBackend SV grows by 11,730 bytes despite removing 4,416 scalar bits. Byte size and statement counts are structural proxies, not LUT estimates.',
                              'Unchanged global ternary count/dependency depth does not prove unchanged physical mux cost or critical-path timing.'])
b.save(analysis/'cost-details.json', result)
print(json.dumps({mode:{key:value for key,value in row.items() if key not in ['removed_scalar_registers','nonblocking_writer_statements']} for mode,row in rows.items()}, indent=2))
