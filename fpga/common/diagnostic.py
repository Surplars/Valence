#!/usr/bin/env python3
"""Independent timing diagnostic. Never produces release/functional acceptance."""
import argparse
import json
import os
from pathlib import Path
import sys
import manifest as gate
import board_inputs
import producer

SCHEMA = 'common-board-diagnostic-v1'
STATUS = 'DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM'
BASELINE = '366a643f93bc598851e16c69aa399529e7c70fdf'
HELPERS = ('diagnostic.py', 'diagnostic.tcl', 'run-diagnostic.ps1', 'diagnostic-baseline.json')


def check(path):
    path = Path(path).absolute(); root = path.parent
    gate.no_links(root)
    m = gate.read(path)
    gate.require(m.get('schema') == SCHEMA and m.get('status') == STATUS, 'diagnostic schema/status required')
    gate.require(m.get('diagnosticOnly') is True and m.get('missing_functional_receipt') is True,
                 'diagnostic cannot claim integrated functional qualification')
    gate.require(m.get('source_commit') == BASELINE, 'unreviewed diagnostic source commit')
    c = m['configuration']
    gate.require(c['cpu'] == 'i1' and c.get('clock_profile') == 'performance300-static', 'only fixed CPU300/fabric250 diagnostic reviewed')
    profile = gate.configuration(c)
    gate.require(c['clocks_hz'] == gate.reviewed_board_clocks('i1','performance300-static'), 'changed diagnostic target clocks')
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
    baseline = gate.read(gate.file_at(root,'fpga/common/diagnostic-baseline.json'))
    gate.require(baseline['commit'] == BASELINE, 'wrong baseline inventory')
    actual_sources={p for p in m['inputs'] if p.startswith(('src/main/scala/','src/main/resources/','src/test/scala/platform/'))}
    gate.require(actual_sources=={p for p in baseline['inputs'] if p.startswith(('src/main/scala/','src/main/resources/','src/test/scala/platform/'))}, 'source closure differs from published baseline')
    for p,h in baseline['inputs'].items():
        # Explicit parser / external-Python isolation overlays only; all actual bytes
        # remain inventory-hashed. Baseline RTL, IP and hardware sources are unchanged.
        if p in ('fpga/common/board_inputs.py', 'fpga/common/test_board_inputs.py',
                 'fpga/common/board_audit.tcl', 'fpga/common/simulate.tcl',
                 'fpga/common/signoff.tcl'): continue
        gate.require(m['inputs'].get(p) == h, 'source differs from published baseline (do not freeze dirty core): '+p)
    for helper in HELPERS:
        gate.require('fpga/common/'+helper in m['inputs'], 'unfrozen diagnostic helper')
    gate.require('functional_receipt' not in m['roles'], 'diagnostic must not supply a fabricated functional role')
    gate.require(m.get('native_evidence') and all(p in m['inputs'] for p in m['native_evidence']), 'freeze actual native evidence')
    dci=[gate.read(gate.file_at(root,p)) for p in m['native_evidence'] if p.endswith('dci-result.json')]
    gate.require(len(dci)==1 and dci[0].get('source_commit')==BASELINE and dci[0].get('dci_positive')=='PASS' and dci[0].get('positive_forbidden_messages_found') is False, 'actual source-bound passing native DCI evidence required')
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
    emitted=[(base/p).as_posix() for p in board_inputs.emitted_artifacts(e['artifacts'])]
    rtl=[p for p in emitted if p.endswith(('.v','.sv')) and '/verification/' not in p]+list(board_inputs.BOARD_RTL)
    sim=[(base/'TriSpeedRgmiiTx.sv').as_posix(),*board_inputs.SIM_RTL]
    c=dict(cpu='i1',clock_profile='performance300-static',top='soc_top_common_ddr',part='xczu15eg-ffvb1156-2-i',abi=1,
           interrupt_abi='aia',rom_base=0x80000000,rom_bytes=131072,
           clocks_hz=gate.reviewed_board_clocks('i1','performance300-static'),features=dict(mac=True,network_dma=True))
    roles=dict(rtl_filelist='diagnostic-generated/rtl.f',simulation_filelist='diagnostic-generated/sim.f',
               emission_profile=a.emission,firmware_contract=a.firmware_contract,rom=a.rom,rom_coe=a.coe,
               board_audit_script='fpga/common/board_audit.tcl',post_synth_constraints='fpga/common/post_synth.tcl',
               post_opt_constraints='fpga/common/post_opt.tcl',media_scenarios='fpga/common/media_scenarios.tcl',
               constraints=['fpga/common/board_pins.xdc','fpga/zu15eg/pl_ddr4_pins.xdc'],ip=[a.mig])
    files=set(emitted+rtl+sim+list(board_inputs.PUBLIC_INPUTS)+a.native_evidence)
    for value in roles.values():files.update(value if isinstance(value,list) else [value])
    files.update(gate.firmware_inputs(root,gate.read(gate.file_at(root,a.firmware_contract))))
    for directory in gate.ROOTS:
        files.update(p.relative_to(root).as_posix() for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    (root/'diagnostic-generated').mkdir()
    for name,lines in [('rtl.f',rtl),('sim.f',sim)]:
        gate.require(len(lines)==len(set(lines)),'duplicate RTL source')
        (root/'diagnostic-generated'/name).write_text('\n'.join(lines)+'\n')
    m=dict(schema=SCHEMA,status=STATUS,diagnosticOnly=True,missing_functional_receipt=True,source_commit=BASELINE,
           configuration=c,threads=a.threads,roles=roles,native_evidence=a.native_evidence,
           producer=dict(schema='common-board-producer-v1',simulation_suite='common-physical-boundaries-v1',media_rates_mbps=[10,100,1000]),
           inputs={p:gate.sha(gate.file_at(root,p)) for p in sorted(files)})
    path=root/'diagnostic.json';path.write_text(json.dumps(m,indent=2)+'\n');check(path);return path


def prepare(path):
    root,m,profile=check(path)
    gate.require(os.name=='nt','native Windows required');gate.local_windows_path(str(root))
    import ctypes
    gate.require(ctypes.windll.kernel32.GetDriveTypeW(str(root.anchor))==3,'local fixed Windows disk required')
    run=root/'diagnostic-run';gate.require(not run.exists(),'preserve earlier diagnostic evidence');run.mkdir()
    pairs=dict(root=str(root),manifest=str(Path(path).absolute()),threads=m['threads'],profile_sha256=profile,
               diagnosticOnly=1,top=m['configuration']['top'],part=m['configuration']['part'],cpu='i1',
               clock_profile='performance300-static',simulation_suite=m['producer']['simulation_suite'])
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
    for name in required:gate.file_at(out,name)
    outputs={p.name:gate.sha(p) for p in out.iterdir() if p.is_file() and p.name!='diagnostic-stage.json'}
    result=dict(schema=SCHEMA,status=STATUS,phase=phase,profile_sha256=profile,source_commit=BASELINE,
                missing_functional_receipt=True,board_tested=False,physical_qualified=False,bit_generated=False,outputs_sha256=outputs)
    (out/'diagnostic-stage.json').write_text(json.dumps(result,indent=2)+'\n');return STATUS


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze');f.add_argument('--root',type=Path,required=True)
    for k in ('emission','rom','coe','firmware-contract','mig'):f.add_argument('--'+k,required=True)
    f.add_argument('--native-evidence',action='append',required=True);f.add_argument('--threads',type=int,default=8)
    for name in ('check','prepare','record'):
        q=sub.add_parser(name);q.add_argument('--manifest',type=Path,required=True)
        if name=='record':q.add_argument('--phase',required=True)
    a=p.parse_args()
    try:
        result=freeze(a) if a.command=='freeze' else prepare(a.manifest) if a.command=='prepare' else record(a.manifest,a.phase) if a.command=='record' else check(a.manifest)[2]
        print(result)
    except (ValueError,KeyError,TypeError,OSError) as e:
        print('DIAGNOSTIC_BLOCKED: '+str(e),file=sys.stderr);sys.exit(1)
