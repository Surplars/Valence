#!/usr/bin/env python3
"""Read-only native cone audit; requires separately lowered paired backend RTL."""
import argparse
import hashlib
import json
import re
from pathlib import Path

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def assignments(text):
    result = {}
    for name, expr in re.findall(r'\bwire\s*(?:\[[^\]]+\]\s*)*(\w+)\s*=\s*(.*?);', text, re.S):
        result[name] = expr
    for name, expr in re.findall(r'\bassign\s+(\w+)\s*=\s*(.*?);', text, re.S):
        result[name] = expr
    return result

def identifiers(expr):
    expr = re.sub(r"\b\d+'[s]?[bdhoBDHO][a-fA-F0-9_xzXZ]+", '', expr)
    return set(re.findall(r'\b[A-Za-z_]\w*\b', expr))

def cone(expr, equations):
    seen, leaves = set(), set()
    def visit(name):
        if name in seen:
            return
        seen.add(name)
        if name not in equations:
            leaves.add(name)
        else:
            for dependency in identifiers(equations[name]):
                visit(dependency)
    for name in identifiers(expr):
        visit(name)
    return {'nodes': sorted(seen), 'leaves': sorted(leaves)}

def ports(text, module, instance):
    start = re.search(r'\b'+module+r'\s+'+instance+r'\s*\(', text)
    assert start, (module, instance)
    end = text.index('\n  );', start.end())
    body = text[start.end():end]
    result = {}
    for match in re.finditer(r'\.(\w+)\s*\(', body):
        pos, depth = match.end(), 1
        while depth:
            depth += (body[pos] == '(') - (body[pos] == ')')
            pos += 1
        result[match[1]] = body[match.end():pos-1].strip()
    return result

def registers(text):
    result = {}
    for dimensions, name in re.findall(r'\breg\s*((?:\[[^\]]+\]\s*)*)(\w+)\s*;', text):
        width = 1
        for high, low in re.findall(r'\[(\d+):(\d+)\]', dimensions):
            width *= abs(int(high)-int(low))+1
        result[name] = width
    return result

def inspect(directory):
    backend = (directory/'IntegerBackend.sv').read_text()
    rob = (directory/'RenameRob.sv').read_text()
    stage_path = directory/'IssueExecuteStage.sv'
    stage = stage_path.read_text()
    return {'backend': backend, 'rob': rob, 'stage': stage,
        'ledger_ports': ports(backend, 'RenameRob', 'ledger'),
        'stage_ports': ports(backend, r'IssueExecuteStage(?:_\d+)?', 'executionStages_1'),
        'files': {p.name: sha(p) for p in (directory/'IntegerBackend.sv', directory/'RenameRob.sv', stage_path)}}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--off', type=Path, required=True)
    ap.add_argument('--on', type=Path, required=True)
    ap.add_argument('--published', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    old, new, published = [inspect(p) for p in (a.off, a.on, a.published)]
    result = {'scope': 'Retained native RTL only; no mapped area, physical fanout or timing claim.'}
    for label, item in [('off', old), ('on', new), ('published', published)]:
        item['cancel_cone'] = cone(item['stage_ports']['io_cancel'], assignments(item['backend']))
        item['queue_token_leaves'] = [n for n in item['cancel_cone']['leaves']
            if re.fullmatch(r'queue_\d+_renamed_token_(?:index|tag)', n)]
        result[label] = {key: item[key] for key in ('files', 'stage_ports', 'queue_token_leaves')}
    assert len(old['queue_token_leaves']) == len(published['queue_token_leaves']) == 32
    assert not new['queue_token_leaves'], 'new functional cancellation retains queue-token query'
    query = assignments(new['rob'])['io_lane1OwnerMatch']
    query_cone = cone(query, assignments(new['rob']))
    expected_leaves = {f'entries_{i}_tag' for i in range(16)} | {
        'io_complete_1_bits_token_index', 'io_complete_1_bits_token_tag'}
    assert set(query_cone['leaves']) == expected_leaves, ('query has unexpected dependencies', query_cone)
    for item in (old, new, published):
        deq = item['stage_ports']['io_deq_bits']
        for field, width in [('index', 4), ('tag', 64)]:
            expression = item['ledger_ports']['io_complete_1_bits_token_'+field]
            match = re.fullmatch(re.escape(deq)+r'\[(\d+):(\d+)\]', expression)
            assert match and int(match[1])-int(match[2])+1 == width, expression
        stage_equations = assignments(item['stage'])
        assert set(cone(stage_equations['io_deq_bits'], stage_equations)['leaves']) == {'payload'}
        assert 'payload' in registers(item['stage']), 'query does not terminate at the execution payload Q'
    shared_wire = new['ledger_ports']['io_lane1OwnerMatch']
    assert shared_wire in new['cancel_cone']['leaves']
    # A local output wire has one declaration, one ledger output binding and one cancel use.
    assert len(re.findall(r'\b'+re.escape(shared_wire)+r'\b', new['backend'])) == 3, 'shared Boolean gained other consumers'
    equations = assignments(new['rob'])
    equality_nodes = [name for name, expr in equations.items()
        if re.search(r'==\s*io_complete_1_bits_token_tag', expr)]
    assert len(equality_nodes) == 1, 'duplicated lane-1 tag equality'
    equality = equality_nodes[0]
    assert equality in query_cone['nodes'], 'output does not expose the actual tag equality'
    assert equality in cone(equations['accepted_1'], equations)['nodes'], 'final acceptance bypasses shared query'
    state = {}
    for module in ('IntegerBackend', 'RenameRob', 'IssueExecuteStage'):
        left, right = [registers((p/(module+'.sv')).read_text()) for p in (a.off, a.on)]
        assert left == right, (module, 'register inventory changed', set(left)^set(right))
        state[module] = {'registers': len(left), 'bits': sum(left.values()), 'identical': True}
    old_modules = {p.name: p for p in a.off.glob('*.sv')}
    new_modules = {p.name: p for p in a.on.glob('*.sv')}
    assert old_modules.keys() == new_modules.keys(), 'native module inventory changed'
    changed = sorted(name for name in old_modules if sha(old_modules[name]) != sha(new_modules[name]))
    assert changed == ['IntegerBackend.sv', 'RenameRob.sv'], 'unexpected native module changed'
    lane0 = [ports(item['backend'], r'IssueExecuteStage(?:_\d+)?', 'executionStages_0')['io_cancel']
        for item in (old, new)]
    assert lane0[0] == lane0[1], 'lane-0 cancellation changed'
    prf_ports = [ports(item['backend'], 'OwnerBankedPhysicalRegisterFile', 'physicalFile')
        for item in (old, new)]
    assert prf_ports[0] == prf_ports[1], 'PRF port connections changed'
    final_write = [assignments(item['backend'])['physicalWrites_1_valid'] for item in (old, new)]
    destinations = [assignments(item['backend'])['ownerReady_io_wake_1_bits'] for item in (old, new)]
    assert final_write[0] == final_write[1] and destinations[0] == destinations[1]
    result.update({'status': 'PASS_NATIVE_OWNER_CONE', 'query_expression': query,
        'query_cone': query_cone, 'shared_local_wire': shared_wire,
        'audit_script_sha256': sha(Path(__file__)), 'native_modules': len(old_modules),
        'changed_modules': changed, 'other_modules_byte_identical': len(old_modules)-len(changed),
        'lane0_cancel_identical': True, 'prf_connections_identical': True,
        'final_prf_write1_qualifier': final_write[1], 'queue_writeback_destination': destinations[1],
        'removed_functional_queue_query': {'rows': 16, 'width': 68, 'index_bits': 4, 'tag_bits': 64},
        'state': state, 'no_complete_valid_or_accepted_feedback': True,
        'limitations': ['Small backend inspection output remains live; published board inspection is pruned.',
            'Verification layers are disabled during lowering; assertion-only past bits are not functional state.']})
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(result['status'])

if __name__ == '__main__':
    main()
