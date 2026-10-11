#!/usr/bin/env python3
"""Literal four-way state/RAM/hierarchy audit; never mapped area or timing."""
import collections, copy, json, re, subprocess, sys
from pathlib import Path
import run_native as b

HERE = b.HERE
OUT = b.OUT
ANALYSIS = HERE/'analysis'
require, read, save, sha = b.require, b.read, b.save, b.sha

def selected_registers(census):
    records = census['modules']['IntegerBackend']['scalar_registers']
    patterns = dict(queue_token_index=r'queue_\d+_renamed_token_index', queue_token_tag=r'queue_\d+_renamed_token_tag',
                    loadBeat=r'loadBeat(?:_REG)?_\d+', loadLanes=r'loadLanes(?:_REG)?_\d+',
                    storeAddress=r'storeAddress_\d+', storeByteLanes=r'storeByteLanes_\d+')
    return {name: dict(bits=sum(row['width'] for row in records if re.fullmatch(pattern, row['name'])),
                       registers=[row for row in records if re.fullmatch(pattern, row['name'])])
            for name, pattern in patterns.items()}

def verify_actual(plan):
    actual = {mode: b.audit_profile(mode, plan) for mode in b.MODES}
    for mode, values in b.MODES.items():
        expected = copy.deepcopy(actual['off-off'])
        for group in ['entryProfile', 'expectedCore']:
            expected[group].update(dict(zip(b.FLAGS, values)))
        for row in expected['coreParameters']:
            row['values'].update(dict(zip(b.FLAGS, values)))
        expected['experiment'] = 'memory-state-reuse-' + mode
        expected['canonicalOptions'] = plan['canonical_flags'][mode]
        require(expected == actual[mode], 'unexpected all-field actual construction difference ' + mode)
    return dict(status='PASS_FULL_ACTUAL_CONSTRUCTOR_BINDING', modes=list(b.MODES),
                profile_fields=34, core_fields=142, cache_fields=11, constructors=dict(core=6, cache=3, ddr=2),
                allowed_differences=b.FLAGS + ['experiment', 'canonicalOptions'])

def structural_indicators(path, graph, census):
    body = census.c.strip(path.read_text())
    tokens = dict(assignments=len(re.findall(r'\bassign\b', body)), ternary_marks=body.count('?'),
                  equalities=len(re.findall(r'===|!==|(?<![=<>!])==(?!=)|(?<![=<>!])!=(?!=)', body)),
                  procedural_blocks=len(re.findall(r'\balways\b', body)),
                  automatic_logic_declarations=len(re.findall(r'\bautomatic\s+logic\b', body)),
                  raw_sv_bytes=path.stat().st_size, local_equation_nodes=graph['equations'])
    cutpoints = set(graph['register_cutpoints'])
    dependencies = graph['all_equation_dependencies']
    depths = {}
    def depth(name):
        if name in cutpoints or name not in dependencies:
            return 0
        if name not in depths:
            depths[name] = 1 + max((depth(child) for child in dependencies[name]), default=0)
        return depths[name]
    tokens['bounded_assignment_dependency_depth'] = max((depth(name) for name in dependencies), default=0)
    tokens['limits'] = ['Textual emitted-RTL structure, not cells, LUTs, timing, or logical equivalence.',
                        'Assignment depth treats child outputs and registers as leaves; no technology delays.']
    return tokens

def negatives(census):
    failures = []
    cases = [
        ('unsupported_logic_state', lambda: census.c.declarations('logic [63:0] silently_omitted;')),
        ('unparsed_reg', lambda: census.c.declarations('reg [N:0] state;')),
        ('unknown_module_alias', lambda: census.c.structural_instances('module X(); MadeUpAlias child(); endmodule', {'X'})),
        ('conditional_generate', lambda: census.c.structural_instances('module X(); if (1) begin Y child(); end endmodule', {'X','Y'})),
        ('unsupported_memory_ports', lambda: census.memory_geometry({'arrays':[{'name':'Memory','width':64,'depth':32}]}, 'module M(input wrong); reg [63:0] Memory[0:31]; endmodule')),
    ]
    for name, function in cases:
        try:
            function()
        except (RuntimeError, AssertionError) as error:
            failures.append(dict(name=name, correctly_rejected=True, reason=str(error)))
        else:
            raise RuntimeError('negative control unexpectedly accepted ' + name)
    return failures

def audit():
    plan = read(HERE/'plan.json')
    b.source_guard(plan)
    execution = read(OUT/'receipt.json')
    require(execution['status'] == 'PASS_FOUR_FRESH_NATIVE_EXPORTS_ONLY', 'native exports incomplete')
    require(len(execution['steps']) == 10 and all(row['exit'] == 0 and row['guard'] is None for row in execution['steps']), 'stage failures')
    b.runtime_guard(read(OUT/'runtime-binding.json'))
    require(not ANALYSIS.exists(), 'fresh analysis destination required')
    ANALYSIS.mkdir()
    census = b.load('reuse_reachable', HERE/'helpers/reachable_census.py')
    census.OUT = ANALYSIS
    control = b.load('reuse_control', HERE/'helpers/control_graph.py')
    save(ANALYSIS/'actual-profiles.json', verify_actual(plan))
    save(ANALYSIS/'negative-controls.json', negatives(census))
    rows, storage, selected, structure = {}, {}, {}, {}
    for mode in b.MODES:
        directory = OUT/mode
        row = census.extend(directory)
        row['directory'] = str(directory)
        rows[mode] = row
        save(ANALYSIS/(mode+'-census.json'), row)
        destination = ANALYSIS/(mode+'-fixed-storage.json')
        result = subprocess.run([sys.executable, '-B', str(HERE/'helpers/native_storage_census_bound_rob64.py'),
                                 '--rtl', str(directory/'rtl'), '--output', str(destination)], capture_output=True, text=True)
        require(result.returncode == 0, 'storage audit failed ' + result.stdout + result.stderr)
        storage[mode] = read(destination)
        graph = control.combinational_graph(directory/'rtl/IntegerBackend.sv')
        save(ANALYSIS/(mode+'-control-graph.json'), graph)
        structure[mode] = structural_indicators(directory/'rtl/IntegerBackend.sv', graph, census)
        selected[mode] = selected_registers(row)
        save(ANALYSIS/(mode+'-selected-registers.json'), selected[mode])
        text = '\n'.join(path.read_text() for path in (directory/'rtl').glob('*.sv'))
        require(not re.search(r'\b(?:BoringUtils|bore|io_mp\w*|io_postedPrep\w*|io_sharedAddress\w*|io_finalLsu\w*)\b', text), 'passive probe survives native lowering')
    baseline = rows['off-off']
    comparisons = {}
    for mode in list(b.MODES)[1:]:
        comparison = census.compare(baseline, rows[mode], 'off-off-to-'+mode)
        comparisons[mode] = comparison
        save(ANALYSIS/(mode+'-comparison.json'), comparison)
    historical = census.extend(b.HISTORICAL)
    historical['directory'] = str(b.HISTORICAL)
    require(sha(b.HISTORICAL/'receipt.json') == plan['historical_receipt_sha256'], 'historical receipt drift')
    save(ANALYSIS/'historical-census.json', historical)
    historical_comparison = census.compare(historical, baseline, 'historical-priority-on-to-off-off')
    save(ANALYSIS/'historical-off-comparison.json', historical_comparison)
    save(ANALYSIS/'structure-indicators.json', structure)
    ram_differences = {}
    for mode in rows:
        ram_differences[mode] = {path: dict(before=baseline['reachable_ram_instances'].get(path), after=rows[mode]['reachable_ram_instances'].get(path))
                                 for path in set(baseline['reachable_ram_instances']) | set(rows[mode]['reachable_ram_instances'])
                                 if baseline['reachable_ram_instances'].get(path) != rows[mode]['reachable_ram_instances'].get(path)}
    save(ANALYSIS/'ram-differences.json', ram_differences)
    findings = []
    table = {}
    for mode, values in b.MODES.items():
        row = rows[mode]
        bits = {name: group['bits'] for name, group in selected[mode].items()}
        expected = dict(queue_token_index=0 if values[0] else 384, queue_token_tag=4096,
                        loadBeat=0 if values[1] else 3904, loadLanes=0 if values[1] else 512,
                        storeAddress=4096, storeByteLanes=512)
        if bits != expected:
            findings.append(mode + ': selected state differs from candidate declaration target; inspect observed register names')
        delta = {kind: row['production_reachable_totals'][kind]-baseline['production_reachable_totals'][kind]
                 for kind in ['scalar_reg_bits','array_reg_bits']}
        target_delta = -(384*values[0]+4416*values[1])
        if delta != dict(scalar_reg_bits=target_delta, array_reg_bits=0):
            findings.append(mode + ': observed whole-production delta differs from source upper bound')
        ports_equal = all(x['ports_equal'] for x in comparisons[mode]['modules']) if mode in comparisons else True
        ram_equal = not ram_differences[mode]
        storage_equal = storage[mode]['groups'] == storage['off-off']['groups']
        hierarchy_equal = ({path: value['module'] for path, value in row['reachable_paths'].items()} ==
                           {path: value['module'] for path, value in baseline['reachable_paths'].items()})
        if not (ports_equal and ram_equal and storage_equal and hierarchy_equal):
            findings.append(mode + ': port/RAM/hierarchy difference requires review')
        table[mode] = dict(**row['production_reachable_totals'], backend_scalar_reg_bits=row['modules']['IntegerBackend']['scalar_reg_bits'],
                          scalar_delta=delta['scalar_reg_bits'], array_delta=delta['array_reg_bits'], selected_register_bits=bits,
                          production_instances=row['production_module_instance_count'], ram_instances=len(row['reachable_ram_instances']),
                          ports_equal_to_off=ports_equal, all_ram_helpers_geometry_ports_equal=ram_equal,
                          fixed_storage_groups_equal=storage_equal, hierarchy_equal_to_off=hierarchy_equal,
                          changed_raw_modules=[x['module'] for x in comparisons[mode]['modules'] if not x['exact_bytes_equal']] if mode in comparisons else [])
    historical_changed = [row['module'] for row in historical_comparison['modules'] if not row['exact_bytes_equal']]
    summary = dict(schema='memory-state-reuse-native-cost-v1', status='REVIEW_REQUIRED' if findings else 'PASS_LITERAL_FOUR_MODE_NATIVE_CENSUS',
                   source_commit=plan['source_commit'], hardware_commit='4d3f1b57643ac9e59d379192e25e03372f6bd2c5',
                   source_freeze_sha256=sha(HERE/'source-freeze.json'), execution_receipt_sha256=sha(OUT/'receipt.json'),
                   table=table, historical_off=dict(exact_all_raw_module_bytes_equal=not historical_changed,
                   changed_raw_modules=historical_changed, production_delta=historical_comparison['delta'],
                   all_ports_equal=all(row['ports_equal'] for row in historical_comparison['modules'])),
                   excluded_external_paths=baseline['excluded_external_paths'], unsupported_aliases=0, normalization_rules=[],
                   findings=findings, structure_indicators=structure,
                   limits=['Reachable declared scalar/array bits after actual native lowering, not mapped FF/LUT/BRAM/DSP resources.',
                           'No Vivado, synthesis, STA, routed timing, or board throughput measurement.',
                           'Native state/RAM/ports and local acyclicity do not prove functional lifetime correctness.',
                           'The two flags remain independently default OFF.'])
    save(ANALYSIS/'summary.json', summary)
    save(HERE/'evidence-manifest.json', {str(path.relative_to(HERE)): sha(path) for path in sorted(HERE.rglob('*'))
                                       if path.is_file() and path.name != 'evidence-manifest.json'})
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    audit()
