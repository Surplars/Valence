#!/usr/bin/env python3
"""Independent timing diagnostic. Never produces release/functional acceptance."""
import argparse
import json
import os
import re
from pathlib import Path
import sys
import manifest as gate
import board_inputs
import producer

SCHEMA = 'common-board-diagnostic-v1'
STATUS = 'DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM'
BASELINE = '366a643f93bc598851e16c69aa399529e7c70fdf'
DYNAMIC_BASELINE = '52ca7058224dc3e9b84f4cdd382a3f8d3bbb8765'
DYNAMIC_OVERLAYS = {
    'fpga/common/' + name for name in (
        'diagnostic.py', 'diagnostic.tcl', 'test_diagnostic.py', 'board_inputs.py', 'test_board_inputs.py',
        'common_cdc.tcl', 'post_synth.tcl', 'post_opt.tcl', 'media_constraints.tcl', 'board_audit.tcl',
        'resume_diagnostic.py', 'resume_diagnostic.tcl', 'dynamic/performance_targets.tcl',
        'test_dynamic_clock_targets.py', 'test_dynamic_diagnostic.py',
        'performance_telemetry_constraints.tcl', 'test_performance_telemetry_constraints.py')
}
HELPERS = ('diagnostic.py', 'diagnostic.tcl', 'run-diagnostic.ps1', 'diagnostic-baseline.json')
OLD_DYNAMIC_MIG = '278fef82fc53811b462514f4859aa455897f6e362e05f8d992433a9b54ea6330'
# Actual native 2025.2 upgrade, reviewed independently of this input parser.
# This is a diagnostic input identity, not DDR calibration or board approval.
NEW_DYNAMIC_MIG = '445bf6243f84bad8fdb2d86565b6f5f6f0b70281db88e4e743870583d02ce870'
NEW_DYNAMIC_MIG_DCP = 'a66a81a57f8f8ddb03ad70d26b8cef21ed4402c6136841ede9803fa1bf877c50'


def dynamic_mig(root, m):
    gate.require(len(m['roles'].get('ip', [])) == 1, 'one actual DDR4 XCI required')
    digest = m['inputs'].get(m['roles']['ip'][0])
    receipt = m['roles'].get('native_mig_replacement')
    if digest == OLD_DYNAMIC_MIG:
        gate.require(receipt is None, 'replacement may not silently use old MIG')
        return
    gate.require(digest == NEW_DYNAMIC_MIG and receipt in m.get('native_evidence', []),
                 'new MIG requires exact reviewed identity and native replacement evidence')
    r = gate.read(gate.file_at(root, receipt))
    expected = dict(schema='common-native-mig2025p2-replacement-v1', status='PASS',
                    original_xci_sha256=OLD_DYNAMIC_MIG, xci_sha256=NEW_DYNAMIC_MIG,
                    xci_size=54491, component_dcp_sha256=NEW_DYNAMIC_MIG_DCP,
                    component_dcp_size=5049818, vivado='2025.2', ip_version='2.2',
                    ip_revision=28, part='xczu15eg-ffvb1156-2-i', ip_locked=False,
                    common_config_differences={}, port_count=871, port_differences=[],
                    ui_clock_period_ns=4.0, ooc_exit_code=0, ooc_errors=0,
                    ooc_critical_warnings=0, requested_threads=8, general_thread_limit=8,
                    board_tested=False, physical_qualified=False)
    for key, value in expected.items():
        gate.require(key in r and r[key] == value, 'native MIG replacement mismatch: '+key)
    # Bind actual native reports, not just an asserted summary. These stay local;
    # no vendor IP, DCP, raw run logs or fabricated old receipt is published.
    reports = r.get('evidence_sha256', {})
    gate.require(isinstance(reports, dict) and reports, 'native MIG report bindings required')
    for path, digest in reports.items():
        gate.require(m['inputs'].get(path) == digest and gate.sha(gate.file_at(root, path)) == digest,
                     'native MIG report changed or omitted: '+path)


def software_parameter_delivery(root, m):
    """Fresh reviewed source inventory. No old-baseline overlays or hash relabeling."""
    name = m['roles'].get('source_inventory')
    gate.require(name == 'delivery/software-parameters/source-inputs.json' and name in m['inputs'],
                 'missing explicit software-parameter source inventory')
    gate.require(m['inputs'][name] == gate.sha(gate.file_at(root, name)), 'new source inventory digest mismatch')
    inventory = gate.read(gate.file_at(root, name))
    commit = m.get('source_commit', '')
    gate.require(re.fullmatch('[0-9a-f]{40}', commit) and
                 inventory.get('schema') == 'common-software-parameter-source-inventory-v1' and
                 inventory.get('source_commit') == commit and m.get('production_source_baseline') == commit and
                 inventory.get('status') == 'REVIEWED_STRUCTURAL_ONLY' and
                 inventory.get('physical_qualified') is False and inventory.get('board_qualified') is False,
                 'new source inventory must identify the actual reviewed unqualified candidate')
    files = inventory.get('files_sha256', {})
    required = {p for p in m['inputs'] if any(p.startswith(prefix + '/') for prefix in gate.ROOTS)}
    required |= set(board_inputs.PUBLIC_INPUTS) | set(board_inputs.BOARD_RTL)
    required |= {p for p in m['inputs'] if p.startswith('fpga/firmware/')}
    gate.require(files and set(files) == required, 'new reviewed source inventory closure mismatch')
    for path, digest in files.items():
        gate.require(m['inputs'].get(path) == digest and gate.sha(gate.file_at(root, path)) == digest,
                     'new reviewed source input mismatch: ' + path)
    return dict(commit=commit, inputs=files)


def dynamic_delivery(root, m):
    # The actual published commit and the immutable production baseline are
    # distinct. A fresh export may have a different aggregate Git history;
    # every delivered source/input byte must still match the reviewed inventory.
    gate.require(re.fullmatch(r'[0-9a-f]{40}', m.get('source_commit', '')) is not None,
                 'actual published delivery commit required')
    if m.get('configuration', {}).get('functional_profile') == board_inputs.SOFTWARE_PARAMETER_PROFILE:
        return software_parameter_delivery(root, m)
    name = m['roles'].get('source_inventory')
    gate.require(name == 'delivery/boot50-dynamic-r25/source-inputs.json', 'missing reviewed delivery inventory')
    gate.require(m['inputs'].get(name) == gate.sha(gate.file_at(root, name)), 'delivery inventory changed')
    inventory = gate.read(gate.file_at(root, name))
    gate.require(inventory.get('production_source_baseline') == DYNAMIC_BASELINE, 'wrong delivery production baseline')
    gate.require(bool(inventory.get('files_sha256')), 'empty delivery inventory')
    for path, digest in inventory['files_sha256'].items():
        gate.require(m['inputs'].get(path) == digest and gate.sha(gate.file_at(root, path)) == digest,
                     'delivery source/input mismatch: ' + path)


def check(path):
    path = Path(path).absolute(); root = path.parent
    gate.no_links(root)
    m = gate.read(path)
    gate.require(m.get('schema') == SCHEMA and m.get('status') == STATUS, 'diagnostic schema/status required')
    gate.require(m.get('diagnosticOnly') is True and m.get('missing_functional_receipt') is True,
                 'diagnostic cannot claim integrated functional qualification')
    c = m['configuration']
    dynamic = c.get('clock_profile') == 'boot50-dynamic'
    software_parameters = c.get('functional_profile') == board_inputs.SOFTWARE_PARAMETER_PROFILE
    gate.require(not software_parameters or dynamic, 'software parameters require dynamic physical profile')
    baseline_commit = m.get('source_commit') if software_parameters else DYNAMIC_BASELINE if dynamic else BASELINE
    reviewed_candidate = None
    if dynamic:
        gate.require(m.get('production_source_baseline') == baseline_commit, 'unreviewed production source baseline')
        reviewed_candidate = dynamic_delivery(root, m)
    else:
        gate.require(m.get('source_commit') == baseline_commit, 'unreviewed diagnostic source baseline')
    gate.require(c['cpu'] == 'i1' and c.get('clock_profile') in ('performance300-static', 'boot50-dynamic'), 'only reviewed I1 diagnostic profiles')
    if dynamic:
        gate.require(m.get('sta_targets_hz') == dict(cpu=300000000, fabric=250000000), 'CPU300/fabric250 stress requirements cannot be relaxed')
        dynamic_mig(root, m)
        for name, digest in {'fpga/common/board_pins.xdc':'1da67e780fe0b5f560c8a45eb90b61c2ac1ba8bb151a2b5a04f6d845db87e3ec', 'fpga/zu15eg/pl_ddr4_pins.xdc':'3c699e25cfcb6d12831ceb2f9846ef22b9ac16e7a3a2a6f6a3b813731b21afbf'}.items():
            gate.require(m['inputs'].get(name) == digest, 'dynamic board pin source changed: '+name)
    profile = gate.configuration(c)
    gate.require(c['clocks_hz'] == gate.reviewed_board_clocks('i1', c['clock_profile']), 'changed diagnostic boot clocks')
    gate.require(type(m.get('threads')) is int and m['threads'] >= 8, 'request at least8 threads')
    gate.require(m.get('inputs') and len({p.casefold() for p in m['inputs']}) == len(m['inputs']), 'invalid input inventory')
    for p,h in m['inputs'].items():
        gate.require(gate.sha(gate.file_at(root,p)) == h, 'diagnostic input changed: '+p)
    for directory in gate.ROOTS:
        gate.require((root/directory).is_dir(), 'missing source root: '+directory)
        for p in (root/directory).rglob('*'):
            gate.no_links(p)
            if p.is_file() and '__pycache__' not in p.parts:
                gate.require(p.relative_to(root).as_posix() in m['inputs'], 'unfrozen source: '+str(p))
    baseline = reviewed_candidate if software_parameters else gate.read(gate.file_at(root, 'fpga/common/dynamic/diagnostic-baseline.json' if dynamic else 'fpga/common/diagnostic-baseline.json'))
    gate.require(baseline['commit'] == baseline_commit, 'wrong baseline inventory')
    actual_sources={p for p in m['inputs'] if p.startswith(('src/main/scala/','src/main/resources/','src/test/scala/platform/'))}
    gate.require(actual_sources=={p for p in baseline['inputs'] if p.startswith(('src/main/scala/','src/main/resources/','src/test/scala/platform/'))}, 'source closure differs from published baseline')
    for p,h in baseline['inputs'].items():
        if not software_parameters and dynamic and p in DYNAMIC_OVERLAYS: continue
        # Explicit parser / external-Python isolation overlays only; all actual bytes
        # remain inventory-hashed. Baseline RTL, IP and hardware sources are unchanged.
        if not software_parameters and p in ('fpga/common/board_inputs.py', 'fpga/common/test_board_inputs.py',
                 'fpga/common/board_audit.tcl', 'fpga/common/simulate.tcl',
                 'fpga/common/signoff.tcl', 'fpga/common/synthesize.tcl', 'fpga/common/implement.tcl'): continue
        gate.require(m['inputs'].get(p) == h, 'source differs from published baseline (do not freeze dirty core): '+p)
    for helper in HELPERS:
        gate.require('fpga/common/'+helper in m['inputs'], 'unfrozen diagnostic helper')
    gate.require('functional_receipt' not in m['roles'], 'diagnostic must not supply a fabricated functional role')
    gate.require(m.get('native_evidence') and all(p in m['inputs'] for p in m['native_evidence']), 'freeze actual native evidence')
    dci=[gate.read(gate.file_at(root,p)) for p in m['native_evidence'] if p.endswith('dci-result.json')]
    gate.require(len(dci)==1 and dci[0].get('source_commit')==BASELINE and dci[0].get('dci_positive')=='PASS' and dci[0].get('positive_forbidden_messages_found') is False, 'actual source-bound passing native DCI evidence required')
    if dynamic:
        dci_path = next(p for p in m['native_evidence'] if p.endswith('dci-result.json'))
        gate.require(m['inputs'][dci_path] == '37b5cdbcd7ec99b47735c65bd01437a0dd88a3dd86c78d84bde417de092033c3', 'only unchanged independently verified native DCI receipt may be reused')
        gate.require(set(p.replace('\\','/') for p in dci[0].get('source_sha256', {})) == {'fpga/common/native_dci_startup.sv', 'fpga/common/dci_startup_tb.sv'}, 'DCI reuse must remain the exact two-source component, not old whole profile')
    for p,h in dci[0].get('source_sha256',{}).items():
        gate.require(m['inputs'].get(p.replace('\\','/'))==h, 'native DCI source differs')
    gate.firmware_contract(root,m,gate.read(gate.file_at(root,m['roles']['firmware_contract'])))
    producer.validate(root,m)
    run=root/'diagnostic-run'
    if run.exists():
        gate.require((run/'input-sha256.txt').read_text().strip()==gate.sha(path), 'diagnostic manifest changed after preparation')
        gate.require((run/'config-sha256.txt').read_text().strip()==gate.sha(run/'config.tcl'), 'diagnostic config changed')
    return root,m,profile


def freeze(a):
    root=a.root.absolute(); gate.no_links(root)
    gate.require(not (root/'diagnostic.json').exists() and not (root/'diagnostic-generated').exists(), 'fresh diagnostic inputs required')
    e=gate.read(gate.file_at(root,a.emission)); base=gate.relative(a.emission).parent
    gate.require(e.get('functionalProfile') != board_inputs.SOFTWARE_PARAMETER_PROFILE,
                 'legacy freeze cannot create software-parameter candidate: supply independently reviewed new inventory and feature receipt')
    emitted=[(base/p).as_posix() for p in board_inputs.emitted_artifacts(e['artifacts'])]
    rtl=[p for p in emitted if p.endswith(('.v','.sv')) and '/verification/' not in p]+list(board_inputs.BOARD_RTL)
    sim=[(base/'TriSpeedRgmiiTx.sv').as_posix(),*board_inputs.SIM_RTL]
    clock_profile = e.get('clockProfile')
    gate.require(clock_profile in ('performance300-static', 'boot50-dynamic'), 'unsupported diagnostic emission')
    dynamic = clock_profile == 'boot50-dynamic'
    if dynamic:
        gate.require(re.fullmatch(r'[0-9a-f]{40}', a.delivery_commit or '') is not None, 'pass the actual published Git --delivery-commit')
    c=dict(cpu='i1',clock_profile=clock_profile,top='soc_top_common_ddr',part='xczu15eg-ffvb1156-2-i',abi=1,
           interrupt_abi='aia',rom_base=0x80000000,rom_bytes=131072,
           clocks_hz=gate.reviewed_board_clocks('i1',clock_profile),features=dict(mac=True,network_dma=True),
           performance_telemetry=e.get('performanceTelemetry', False))
    roles=dict(rtl_filelist='diagnostic-generated/rtl.f',simulation_filelist='diagnostic-generated/sim.f',
               emission_profile=a.emission,firmware_contract=a.firmware_contract,rom=a.rom,rom_coe=a.coe,
               board_audit_script='fpga/common/board_audit.tcl',post_synth_constraints='fpga/common/post_synth.tcl',
               post_opt_constraints='fpga/common/post_opt.tcl',media_scenarios='fpga/common/media_scenarios.tcl',
               constraints=['fpga/common/board_pins.xdc','fpga/zu15eg/pl_ddr4_pins.xdc'],ip=[a.mig])
    files=set(emitted+rtl+sim+list(board_inputs.PUBLIC_INPUTS)+a.native_evidence)
    replacement = getattr(a, 'mig_replacement_evidence', None)
    if replacement:
        gate.require(dynamic and replacement in a.native_evidence, 'freeze actual dynamic MIG receipt with --native-evidence')
        roles['native_mig_replacement'] = replacement
        files.update(gate.read(gate.file_at(root, replacement)).get('evidence_sha256', {}))
    if dynamic:
        roles['source_inventory'] = 'delivery/boot50-dynamic-r25/source-inputs.json'
        files.update(gate.read(gate.file_at(root, roles['source_inventory']))['files_sha256'])
    for value in roles.values():files.update(value if isinstance(value,list) else [value])
    files.update(gate.firmware_inputs(root,gate.read(gate.file_at(root,a.firmware_contract))))
    for directory in gate.ROOTS:
        files.update(p.relative_to(root).as_posix() for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    (root/'diagnostic-generated').mkdir()
    for name,lines in [('rtl.f',rtl),('sim.f',sim)]:
        gate.require(len(lines)==len(set(lines)),'duplicate RTL source')
        (root/'diagnostic-generated'/name).write_text('\n'.join(lines)+'\n')
    m=dict(schema=SCHEMA,status=STATUS,diagnosticOnly=True,missing_functional_receipt=True,source_commit=a.delivery_commit if dynamic else BASELINE,
           configuration=c,threads=a.threads,roles=roles,native_evidence=a.native_evidence,
           producer=dict(schema='common-board-producer-v1',simulation_suite='common-physical-boundaries-v1',media_rates_mbps=[10,100,1000]),
           inputs={p:gate.sha(gate.file_at(root,p)) for p in sorted(files)})
    if dynamic:
        m['sta_targets_hz'] = dict(cpu=300000000, fabric=250000000)
        m['production_source_baseline'] = DYNAMIC_BASELINE
        m['source_commit_scope'] = 'actual published delivery commit; production baseline and explicit diagnostic-tool overlays are separately byte-verified'
        m['native_dci_reuse_scope'] = 'exact unchanged two-source component only; not whole-profile acceptance'
    path=root/'diagnostic.json';path.write_text(json.dumps(m,indent=2)+'\n');check(path);return path


def prepare(path):
    root,m,profile=check(path)
    gate.require(os.name=='nt','native Windows required');gate.local_windows_path(str(root))
    import ctypes
    gate.require(ctypes.windll.kernel32.GetDriveTypeW(str(root.anchor))==3,'local fixed Windows disk required')
    run=root/'diagnostic-run';gate.require(not run.exists(),'preserve earlier diagnostic evidence');run.mkdir()
    pairs=dict(root=str(root),manifest=str(Path(path).absolute()),threads=m['threads'],profile_sha256=profile,
               diagnosticOnly=1,control_lemma=1,top=m['configuration']['top'],part=m['configuration']['part'],cpu='i1',
               clock_profile=m['configuration']['clock_profile'],simulation_suite=m['producer']['simulation_suite'],
               performance_telemetry=int(m['configuration'].get('performance_telemetry', False)))
    for name in ('rtl_filelist','simulation_filelist','post_synth_constraints','post_opt_constraints','media_scenarios','rom_coe','rom'):
        pairs[name]=str(root/m['roles'][name])
    pairs['mig_xci']=str(root/m['roles']['ip'][0]);pairs['constraints']=' '.join(gate.tcl(str(root/p)) for p in m['roles']['constraints'])
    for k,v in m['configuration']['clocks_hz'].items():pairs['hz_'+k]=v
    (run/'config.tcl').write_text('\n'.join('set valence('+k+') '+gate.tcl(v) for k,v in pairs.items())+'\n')
    (run/'input-sha256.txt').write_text(gate.sha(path)+'\n');(run/'config-sha256.txt').write_text(gate.sha(run/'config.tcl')+'\n')
    return STATUS


def record(path,phase):
    root,m,profile=check(path);gate.require(phase in ('synthesis','implementation'),'invalid diagnostic phase')
    out=root/'diagnostic-run'/phase
    gate.require(not (out/'stage-receipt.json').exists(),'formal receipt forbidden in diagnostic')
    required=['synthesized.dcp','clock-output-checks.txt','generated-clocks.rpt','ip-synthesis.json'] if phase=='synthesis' else ['routed.dcp','timing.rpt','coverage.rpt','cdc.rpt','drc.rpt','clocks.rpt','route.rpt','bus-skew.rpt','diagnostic-audit.txt']
    if m['configuration']['clock_profile'] == 'boot50-dynamic' and phase == 'synthesis':
        required += ['dynamic-performance-target-clocks.rpt', 'dynamic-boot-parameters.txt', 'cpu_clock-ce-timing.rpt', 'fabric_clock-ce-timing.rpt']
    for name in required:gate.file_at(out,name)
    outputs={p.name:gate.sha(p) for p in out.iterdir() if p.is_file() and p.name!='diagnostic-stage.json'}
    result=dict(schema=SCHEMA,status=STATUS,phase=phase,profile_sha256=profile,source_commit=m['source_commit'],
                missing_functional_receipt=True,board_tested=False,physical_qualified=False,bit_generated=False,outputs_sha256=outputs)
    if 'production_source_baseline' in m: result['production_source_baseline'] = m['production_source_baseline']
    (out/'diagnostic-stage.json').write_text(json.dumps(result,indent=2)+'\n');return STATUS


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze');f.add_argument('--root',type=Path,required=True)
    for k in ('emission','rom','coe','firmware-contract','mig'):f.add_argument('--'+k,required=True)
    f.add_argument('--native-evidence',action='append',required=True);f.add_argument('--threads',type=int,default=8);f.add_argument('--delivery-commit')
    f.add_argument('--mig-replacement-evidence', help='Actual local 2025.2 MIG replacement receipt; fresh diagnostic package only')
    for name in ('check','prepare','record'):
        q=sub.add_parser(name);q.add_argument('--manifest',type=Path,required=True)
        if name=='record':q.add_argument('--phase',required=True)
    a=p.parse_args()
    try:
        result=freeze(a) if a.command=='freeze' else prepare(a.manifest) if a.command=='prepare' else record(a.manifest,a.phase) if a.command=='record' else check(a.manifest)[2]
        print(result)
    except (ValueError,KeyError,TypeError,OSError) as e:
        print('DIAGNOSTIC_BLOCKED: '+str(e),file=sys.stderr);sys.exit(1)
