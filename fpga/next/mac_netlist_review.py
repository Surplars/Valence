#!/usr/bin/env python3
"""Stage and bind a future read-only MAC netlist collection. Never runs Vivado.

prepare-job requires a separately produced implementation provenance receipt;
it cannot infer that an arbitrary DCP came from the current RTL. verify-job is
also called by the generated Tcl immediately before opening the checkpoint.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
FILES = ('audit_mac_netlist.tcl', 'mac-boundary-cdc-inventory.json', 'mac_netlist_review.py',
         'mac_registered_level_constraints.tcl')
INPUTS = tuple('fpga/next/' + name for name in FILES) + (
    'fpga/zu15eg/native-gmac-cdc-constraints.tcl',
    'fpga/zu15eg/cdc_constraints.tcl',
    'src/main/scala/ip/ethernet/TriSpeedManagedGmac.scala',
    'src/main/scala/ip/ethernet/EthernetMediaTransition.scala',
)
STATUS = 'SOURCE_BOUND_PREPARED_NOT_NETLIST_QUALIFIED'
MAILBOXES = ['txRate', 'rxRate', 'txConfig/mailbox', 'rxConfig/mailbox',
            'txStats/mailbox', 'rxStats/mailbox', 'rxDiagnostics/mailbox',
            'rawDiagnostics/mailbox', 'rxStop/command']
FIFOS = ['txFifo/fifo', 'rxFifo/fifo', 'physicalIngress/crossing/fifo']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def tcl(value):
    """Produce Tcl values, never interpolate a path as executable Tcl code."""
    if isinstance(value, dict):
        return '[dict create ' + ' '.join(tcl(x) for kv in value.items() for x in kv) + ']'
    if isinstance(value, (list, tuple)):
        return '[list ' + ' '.join(map(tcl, value)) + ']'
    text = str(int(value)) if isinstance(value, bool) else str(value)
    for a, b in (('\\', '\\\\'), ('$', '\\$'), ('[', '\\['), (']', '\\]'),
                 ('"', '\\"'), ('\n', '\\n'), ('\r', '\\r')):
        text = text.replace(a, b)
    return '"' + text + '"'


def contract(inventory):
    c = inventory['netlist_contract']
    if (inventory['version'] != 2 or c['version'] != 1 or
            inventory['board_root'] != 'u_soc/board/nativeBank/gmac' or
            inventory['mailboxes'] != MAILBOXES or inventory['fifos'] != FIFOS or
            list(c['mailbox_widths']) != MAILBOXES or list(c['fifo_pointer_widths']) != FIFOS or
            list(c['mailbox_widths'].values()) != [2, 2, 52, 52, 160, 160, 256, 96, 1] or
            list(c['fifo_pointer_widths'].values()) != [5, 5, 7] or c['fifo_payload_width'] != 38 or
            c['status'] != 'PREPARED_NOT_NETLIST_QUALIFIED'):
        raise RuntimeError('MAC current exact 9/3 contract required; shape changes need review')
    expected = [
        ['txLink_sync', 'mediaOpen_reg', 'cpu', 'tx', 'cpuRelease', 'txRelease'],
        ['rxLink_sync', 'mediaOpen_reg', 'cpu', 'rx', 'cpuRelease', 'rxRelease'],
        ['rawRxOpen_sync', 'mediaOpen_reg', 'cpu', 'raw_rx', 'cpuRelease', 'rawRxRelease'],
        ['ingressEmpty_sync', 'ingressEmptySource_reg', 'raw_tx', 'cpu', 'rawTxRelease', 'cpuRelease'],
        ['txWireDrained_sync', 'txWireDrainedSource_reg', 'raw_tx', 'cpu', 'rawTxRelease', 'cpuRelease'],
    ]
    if c['level_rules'] != expected:
        raise RuntimeError('MAC registered launch/reset/clock rules changed; review required')
    expected_mailbox_domains = dict(zip(MAILBOXES, [
        ['cpu','raw_tx'], ['cpu','raw_rx'], ['cpu','tx'], ['cpu','rx'],
        ['tx','cpu'], ['rx','cpu'], ['rx','cpu'], ['raw_rx','cpu'], ['cpu','rx']]))
    expected_fifo_domains = dict(zip(FIFOS, [['cpu','tx'], ['rx','cpu'], ['raw_rx','raw_tx']]))
    if c['mailbox_clock_domains'] != expected_mailbox_domains or c['fifo_clock_domains'] != expected_fifo_domains:
        raise RuntimeError('MAC packet source/destination clock roles changed; review required')
    return {**c, 'root': inventory['board_root'],
            'retired_chains': inventory['retired_independent_level_chains']}


def stage(root, output):
    before = {p: sha(root / p) for p in INPUTS}
    board = output / 'board'
    for name in FILES:
        shutil.copy2(root / 'fpga/next' / name, board / name)
    rules = contract(json.loads((board / FILES[1]).read_text()))
    binding = {'schema': 'valence-mac-netlist-binding-v1', 'status': STATUS,
               'source_sha256': before, 'contract': rules,
               'staged_sha256': {name: sha(board / name) for name in FILES},
               'netlist_qualified': False, 'vivado_run': False}
    dump(board / 'mac-netlist-binding.json', binding)
    (board / 'mac-netlist-binding.tcl').write_text(
        '# Generated source-bound data, not netlist evidence.\n' +
        'set VALENCE_MAC_CONTRACT ' + tcl(rules) + '\n' +
        'set VALENCE_MAC_BINDING ' + tcl({'status': STATUS,
            'binding_sha256': sha(board / 'mac-netlist-binding.json')}) + '\n')
    if before != {p: sha(root / p) for p in INPUTS}:
        raise RuntimeError('MAC review sources changed while staging')
    return {'status': 'PREPARED_NOT_NETLIST_QUALIFIED', 'manifest': 'board/mac-netlist-binding.json',
            'sha256': sha(board / 'mac-netlist-binding.json'),
            'collector': 'board/audit_mac_netlist.tcl',
            'prepare_command': 'python3 board/mac_netlist_review.py prepare-job EXPORT CHECKPOINT PROVENANCE JOB --rate 1000',
            'source_sha256': before, 'netlist_qualified': False}


def safe_child(root, name):
    p = Path(name)
    if p.is_absolute() or '..' in p.parts:
        raise RuntimeError('Unsafe relative artifact path: ' + name)
    full = (root / p).resolve()
    if not full.is_relative_to(root.resolve()) or not full.is_file():
        raise RuntimeError('Missing/escaped artifact: ' + name)
    return full


def verified_export(export):
    receipt = json.loads((export / 'receipt.json').read_text())
    if receipt['status'] != 'PASS_RTL_EXPORT_ONLY' or not receipt.get('tri_speed_native_integration'):
        raise RuntimeError('Matching completed tri-speed board export required')
    media = receipt['tri_speed_native_integration']
    manifest_path = safe_child(export, media['manifest'])
    if sha(manifest_path) != media['sha256']:
        raise RuntimeError('Media integration manifest hash mismatch')
    manifest = json.loads(manifest_path.read_text())
    for name, digest in {**receipt['rtl_sha256'], **manifest['artifacts_sha256']}.items():
        if sha(safe_child(export, name)) != digest:
            raise RuntimeError('Export/staged artifact hash mismatch: ' + name)
    if sha(export / 'synthesis-files.f') != receipt['synthesis_filelist_sha256']:
        raise RuntimeError('Synthesis filelist mismatch')
    b = json.loads((export / 'board/mac-netlist-binding.json').read_text())
    contract(json.loads((export / 'board/mac-boundary-cdc-inventory.json').read_text()))
    if b['status'] != STATUS:
        raise RuntimeError('Invalid MAC collector binding status')
    for name, digest in b['source_sha256'].items():
        if receipt['source_sha256'].get(name) != digest:
            raise RuntimeError('Collector source differs from emitted source: ' + name)
    return receipt, b


def prepare_job(export, checkpoint, provenance, job, rate):
    export, checkpoint, provenance, job = (p.resolve() for p in (export, checkpoint, provenance, job))
    receipt, binding = verified_export(export)
    validate_provenance(export, checkpoint, provenance, rate, receipt)
    # This is provenance supplied by the implementation run, not cryptographic
    # proof of elaboration. Retain it for independent review, never synthesize it.
    if job.exists():
        raise RuntimeError('Use a fresh collector job directory')
    job.mkdir(parents=True)
    data = {'schema': 'valence-mac-netlist-job-v1', 'status': 'PREPARED_NOT_NETLIST_QUALIFIED',
            'export': str(export), 'checkpoint': str(checkpoint), 'provenance': str(provenance),
            'rate_mbps': rate, 'export_receipt_sha256': sha(export / 'receipt.json'),
            'checkpoint_sha256': sha(checkpoint), 'provenance_sha256': sha(provenance),
            'binding_sha256': sha(export / 'board/mac-netlist-binding.json'),
            'python': sys.executable, 'vivado_run': False, 'netlist_qualified': False}
    dump(job / 'job.json', data)
    helper = export / 'board/mac_netlist_review.py'
    script = '# Prepared only; run separately under authorized Vivado on this host.\n'
    script += 'exec ' + ' '.join(tcl(x) for x in (sys.executable, helper, 'verify-job', job / 'job.json')) + '\n'
    script += 'open_checkpoint ' + tcl(checkpoint) + '\n'
    script += 'source ' + tcl(export / 'board/mac-netlist-binding.tcl') + '\n'
    script += 'source ' + tcl(export / 'board/audit_mac_netlist.tcl') + '\n'
    script += 'dict set VALENCE_MAC_BINDING checkpoint_sha256 ' + tcl(data['checkpoint_sha256']) + '\n'
    script += 'dict set VALENCE_MAC_BINDING export_receipt_sha256 ' + tcl(data['export_receipt_sha256']) + '\n'
    script += 'valence_mac::collect $VALENCE_MAC_CONTRACT $VALENCE_MAC_BINDING ' + tcl(job / 'reports') + ' ' + str(rate) + '\n'
    (job / 'collect.tcl').write_text(script)
    return data


def validate_provenance(export, checkpoint, provenance, rate, receipt):
    proof = json.loads(provenance.read_text())
    expected = {'schema': 'valence-mac-checkpoint-provenance-v1',
                'export_receipt_sha256': sha(export / 'receipt.json'),
                'checkpoint_sha256': sha(checkpoint), 'rate_mbps': rate,
                'source_sha256': receipt['source_sha256'], 'rtl_sha256': receipt['rtl_sha256']}
    if any(proof.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Checkpoint provenance does not bind this export, rate and DCP')
    if not proof.get('implementation_log_sha256') or not proof.get('constraint_files_sha256'):
        raise RuntimeError('Checkpoint provenance needs implementation log and exact constraint file hashes')
    for category in ('implementation_log_sha256', 'constraint_files_sha256'):
        if not isinstance(proof[category], dict):
            raise RuntimeError('Provenance file hash maps required')
        for name, digest in proof[category].items():
            if sha(safe_child(provenance.parent, name)) != digest:
                raise RuntimeError('Implementation provenance artifact drift: ' + name)
    required = ('trispeed_board_constraints.tcl', 'native-gmac-cdc-constraints.tcl',
                'cdc_constraints.tcl', 'mac_registered_level_constraints.tcl')
    if not {sha(export / 'board' / name) for name in required}.issubset(set(proof['constraint_files_sha256'].values())):
        raise RuntimeError('Provenance omits current packet or registered-level constraint recipe')


def verify_job(path):
    data = json.loads(path.read_text()); export = Path(data['export'])
    receipt, _ = verified_export(export)
    for key, file in [('export_receipt', export / 'receipt.json'),
                      ('checkpoint', Path(data['checkpoint'])), ('provenance', Path(data['provenance'])),
                      ('binding', export / 'board/mac-netlist-binding.json')]:
        if sha(file) != data[key + '_sha256']:
            raise RuntimeError('Collector job byte identity changed: ' + key)
    validate_provenance(export, Path(data['checkpoint']), Path(data['provenance']), data['rate_mbps'], receipt)
    return 'SOURCE_AND_CHECKPOINT_BYTES_VERIFIED_NOT_NETLIST_QUALIFIED'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('prepare-job')
    for name in ('export', 'checkpoint', 'provenance', 'job'): p.add_argument(name, type=Path)
    p.add_argument('--rate', type=int, required=True, choices=[10, 100, 1000])
    p = sub.add_parser('verify-job'); p.add_argument('job', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare-job':
        print(prepare_job(args.export, args.checkpoint, args.provenance, args.job, args.rate)['status'])
    else:
        print(verify_job(args.job))


if __name__ == '__main__':
    main()
