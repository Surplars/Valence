#!/usr/bin/env python3
"""Fail-closed DDR2G release, with fresh whole-board STA/CDC/ROM evidence.

Reuse only hash-identical independent CDC interface tests, never old routed
CPU timing or an old CPU executable. Physical operation remains unverified.
"""
import argparse
import collections
import json
from pathlib import Path
import re
import sys

# Vivado invokes Python with -I to ignore its embedded PYTHONHOME/PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_native_release_contract import cdc_inventory, fingerprint, require, sha, validate_cdc_review
from prepare_native_release_contract import bridge_fields, classify
from audit_native_rv64gc import routed_state, summary


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def validate(contract_path, dcp, cdc_report=None):
    contract = load(contract_path)
    require(contract['status'] == 'READY_DDR2G_RV64GC100_STATIC_RELEASE_NOT_RUNTIME', 'Unqualified contract')
    root, repo = Path(contract['candidate']), Path(contract['repo'])
    require(Path(dcp).resolve() == (root / 'implementation/routed.dcp').resolve(), 'Wrong own routed checkpoint')
    require(sha(dcp) == contract['dcp_sha256'], 'Routed DCP changed')
    require(sha(root / 'inputs.json') == contract['candidate_manifest_sha256'], 'Frozen inputs changed')
    inputs = load(root / 'inputs.json')
    require((inputs['isa'], inputs['f_d_enabled'], inputs['issue_width'], inputs['cpu_hz'],
             inputs['uart_baud'], inputs['ddr_bytes']) ==
            ('rv64gc', True, 2, 100000000, 460800, 0x80000000), 'Wrong hardware profile')
    require(inputs['ram_base'] == '0x80200000' and inputs['end_exclusive'] == '0x100200000', 'Wrong DDR map')
    for name, digest in inputs['candidate_sha256'].items():
        require(sha(root / name) == digest, 'Frozen candidate drift: ' + name)
    for name, digest in inputs['checked_source_sha256'].items():
        require(sha(repo / name) == digest, 'Verified source drift: ' + name)
    for name, digest in contract['qualification_tool_sha256'].items():
        require(sha(root / 'qualification-tools' / name) == digest, 'Qualification tool drift: ' + name)
    evidence = contract['evidence']
    require({'routed_proof', 'cdc_facts', 'mailbox_truth', 'cdc_review', 'register_bridge_static',
             'ddr2g_receipt', 'network_pressure', 'bsp_audit', 'gmac_cdc', 'clock_gate_cdc',
             'managed_cdc', 'quarter_tx', 'quarter_rx'} <= set(evidence), 'Incomplete release evidence')
    for role, item in evidence.items():
        require(sha(item['path']) == item['sha256'], 'Evidence drift: ' + role)
    proof = load(evidence['routed_proof']['path'])
    require(proof['status'] == 'RV64GC100_ROUTED_TIMING_MET_CDC_BOARD_REVIEW_PENDING' and
            proof['dcp_sha256'] == sha(dcp) and proof['source_integrated'] and proof['bit_requested'] and
            proof['routed_timing_met'] and proof['ddr_bytes'] == 0x80000000, 'Current route not qualified')
    for key in ('candidate_input_drift', 'current_source_drift', 'runtime_errors',
                'runtime_critical_warnings', 'drc_errors_or_critical'):
        require(not proof[key], 'Unreviewed route issue: ' + key)
    run = Path(dcp).parent
    for name, digest in proof['artifact_sha256'].items():
        path = run / name
        require(sha(path if path.is_file() else root / name) == digest, 'Route report drift: ' + name)
    timing = (run / 'timing_summary.rpt').read_text()
    require(routed_state(timing) and summary(timing) == proof['board'], 'Not current routed STA')
    require(proof['routing']['all_routed'] and all(proof['clock_coverage'].values()) and
            proof['bus_skew']['checks'] >= 27 and proof['bus_skew']['failures'] == 0 and
            proof['bus_skew']['minimum_slack_ns'] >= 0, 'Route/coverage/skew failure')
    require(all(proof['board'][k] >= 0 for k in ('setup_ns', 'hold_ns', 'pulse_ns')) and
            all(proof['board'][k] == 0 for k in ('setup_failures', 'hold_failures', 'pulse_failures')), 'STA failure')
    for role, marker in (('cdc_facts', 'READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF'),
                         ('mailbox_truth', 'PASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE')):
        text = Path(evidence[role]['path']).read_text()
        binding = re.search(r'^CHECKPOINT=(.+)$', text, re.M)
        require(marker in text and binding and Path(binding[1]).resolve() == Path(dcp).resolve(), 'Wrong current netlist facts')
    statuses = dict(gmac_cdc='PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT',
                    clock_gate_cdc='PASS_MANAGED_CLOCK_GATE_CDC_SHORT',
                    managed_cdc='PASS_MANAGED_PERIPHERAL_CDC_SHORT',
                    quarter_tx='PASS_NATIVE_TX_QUARTER_BOARD_SHORT', quarter_rx='PASS_NATIVE_RX_DESKEW_SHORT')
    for role, expected in statuses.items():
        item = load(evidence[role]['path'])
        require(item['status'] == expected and item['input_sha256'], 'Missing interface proof: ' + role)
        for path, digest in item['input_sha256'].items():
            require(sha(path) == digest, 'Reused independent CDC input changed: ' + path)
    for role in ('ddr2g_receipt', 'network_pressure'):
        require(load(evidence[role]['path'])['status'] == 'passed', 'Affected short check failed')
    if inputs.get('cpu_affected_receipt_sha256'):
        require({'cpu_affected', 'uart_machine_code'} <= set(evidence), 'New CPU/ROM evidence missing')
        cpu = load(evidence['cpu_affected']['path'])
        uart = load(evidence['uart_machine_code']['path'])
        require(cpu['status'] == 'PASS_SOC_UART_MARGIN_AFFECTED_SHORT' and
                sha(evidence['cpu_affected']['path']) == inputs['cpu_affected_receipt_sha256'], 'Wrong current CPU proof')
        require(uart == inputs['uart_machine_code_audit'] and
                sha(evidence['uart_machine_code']['path']) == inputs['uart_machine_code_audit_sha256'] and
                uart['binary_sha256'] == sha(root / 'firmware/bootrom.bin') and uart['divisor'] == 1 and
                uart['baud'] == 460800 and uart['reference_hz'] == 7372800 and uart['fcr'] == 7, 'Wrong compiled UART contract')
    bsp = load(evidence['bsp_audit']['path'])
    require((bsp['memory_bytes'], bsp['cpu_hz'], bsp['uart_baud']) == (0x80000000, 100000000, 460800), 'Wrong Debian BSP')
    firmware = Path(evidence['bsp_audit']['path']).parent
    require(sha(firmware / 'manifest.json') == bsp['delivery_manifest_sha256'], 'BSP manifest drift')
    for name, item in load(firmware / 'manifest.json')['files'].items():
        require(sha(firmware / name) == item['sha256'] and
                (firmware / name).stat().st_size == item['bytes'], 'Debian payload drift: ' + name)
    review = load(evidence['cdc_review']['path'])
    report = Path(cdc_report) if cdc_report else run / 'cdc.rpt'
    count = validate_cdc_review(report.read_text(), review, sha(dcp), set(evidence))
    return dict(status='PASS_DDR2G_RV64GC100_STATIC_RELEASE_NOT_RUNTIME',
                dcp_sha256=sha(dcp), reviewed_cdc_findings=count, bit_generated=False)


def prepare(args):
    require(not args.out.exists(), 'Preserve previous contract')
    root, repo = args.candidate.resolve(), args.repo.resolve()
    dcp = root / 'implementation/routed.dcp'
    prior = load(args.legacy_contract)
    roles = {role: Path(prior['evidence'][role]['path']) for role in
             ('gmac_cdc', 'clock_gate_cdc', 'managed_cdc', 'quarter_tx', 'quarter_rx')}
    for role, path in roles.items():
        require(sha(path) == prior['evidence'][role]['sha256'], 'Interface receipt identity changed')
    roles.update(routed_proof=args.routed_proof, cdc_facts=root / ('cdc-facts-' + args.facts_tag) / 'structural_facts.txt',
                 mailbox_truth=root / ('mailbox-facts-' + args.facts_tag) / 'mailbox_next_state.txt',
                 ddr2g_receipt=args.ddr_receipt or repo / 'build/gsim/ddr2g-20261006-r8/receipt.json',
                 network_pressure=args.network_receipt or repo / 'build/gsim/network-packet-pressure-20261006-2g-r6/receipt.json',
                 bsp_audit=args.bsp / 'bsp-audit.json')
    inputs = load(root / 'inputs.json')
    if inputs.get('cpu_affected_receipt_sha256'):
        roles['cpu_affected'] = Path(inputs['cpu_affected_receipt'])
        roles['uart_machine_code'] = root / 'firmware/uart-machine-code-audit.json'
    facts = roles['cdc_facts'].read_text()
    findings = []
    rows = cdc_inventory((dcp.parent / 'cdc.rpt').read_text())
    for row in rows:
        if row['severity'] == 'Info':
            continue
        category, reason, references = classify(row, facts)
        references = ['ddr2g_receipt' if name == 'native_short' else name for name in references]
        findings.append(dict(fingerprint=fingerprint(row), classification=category, reason=reason,
                             evidence=references, actual_finding=row))
    review = dict(status='PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME',
                  dcp_sha256=sha(dcp), timing_exceptions_added=False, unreviewed_findings=[], findings=findings,
                  class_counts=dict(collections.Counter(f['classification'] for f in findings)))
    bridge = bridge_fields(root, repo)
    args.out.mkdir(parents=True)
    for role, name, value in (('cdc_review', 'cdc-review.json', review),
                               ('register_bridge_static', 'register-bridge-static.json', bridge)):
        roles[role] = args.out / name
        write_new(roles[role], value)
    tools = root / 'qualification-tools'
    contract = dict(status='READY_DDR2G_RV64GC100_STATIC_RELEASE_NOT_RUNTIME',
                    candidate=str(root), repo=str(repo), dcp_sha256=sha(dcp),
                    candidate_manifest_sha256=sha(root / 'inputs.json'),
                    qualification_tool_sha256={p.name: sha(p) for p in tools.iterdir() if p.is_file()},
                    evidence={role: dict(path=str(path), sha256=sha(path)) for role, path in roles.items()},
                    board_verified=False, bit_generated=False,
                    limits=['Fresh full SoC synthesis; incremental implementation is not netlist equivalence.',
                            'Affected short checks only; CPU/Linux/2GiB physical runtime still unverified.',
                            'Positive static timing is not a physical DDR or GMAC stability measurement.'])
    path = args.out / 'qualified-contract.json'
    write_new(path, contract)
    print(json.dumps(validate(path, dcp), sort_keys=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--contract', type=Path)
    ap.add_argument('--dcp', type=Path)
    ap.add_argument('--cdc-report', type=Path)
    ap.add_argument('--candidate', type=Path)
    ap.add_argument('--repo', type=Path)
    ap.add_argument('--bsp', type=Path)
    ap.add_argument('--legacy-contract', type=Path)
    ap.add_argument('--routed-proof', type=Path)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--ddr-receipt', type=Path)
    ap.add_argument('--network-receipt', type=Path)
    ap.add_argument('--facts-tag', default='r5', choices=('r5', 'r6'))
    args = ap.parse_args()
    if args.contract:
        require(args.dcp is not None, '--dcp required')
        print(json.dumps(validate(args.contract, args.dcp, args.cdc_report), sort_keys=True))
    else:
        require(all((args.candidate, args.repo, args.bsp, args.legacy_contract, args.routed_proof, args.out)), 'Missing prepare arguments')
        prepare(args)


if __name__ == '__main__':
    main()
