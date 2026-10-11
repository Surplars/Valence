#!/usr/bin/env python3
"""Short production MAC async check, with exact-source export and RTL reuse.

Needs existing Mill/firtool/Icarus; never installs tools or invokes CAD. Fresh
mode emits TXslots1/2 sequentially. Reuse mode checks the paired source/RTL
receipt before running new host tests on those identical emitted bytes.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
runtime=load('run_mac_boundary_cdc')
structural=load('check_mac_boundary_cdc_structure')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mill',default='mill')
    parser.add_argument('--reuse-export-receipt',type=Path)
    parser.add_argument('--reuse-rtl-prefix',type=Path,
        help='exact directory prefix ending before TX slot number, e.g. build/rtl-slots')
    args=parser.parse_args()
    if bool(args.reuse_export_receipt)!=bool(args.reuse_rtl_prefix):
        parser.error('reuse requires both exact export receipt and RTL directory prefix')
    if args.output.exists():parser.error('use a fresh output directory')
    if not shutil.which('iverilog') or not shutil.which('vvp'):parser.error('existing official Icarus/VVP required')
    if not args.reuse_export_receipt and not shutil.which(args.mill):parser.error('existing Mill required')
    args.output=args.output.resolve()
    inputs=sorted((ROOT/'src/main/scala').rglob('*.scala'))
    inputs += [ROOT/'src/test/scala/ip/TriSpeedManagedBoundaryCdc.scala',ROOT/'build.mill',ROOT/'Makefile',
               ROOT/'fpga/zu15eg/trispeed_board_constraints.tcl']
    inputs += [HERE/n for n in ('check_mac_boundary.py','run_mac_boundary_cdc.py','check_mac_boundary_cdc_structure.py',
               'mac-boundary-cdc-inventory.json','tests/mac_boundary_cdc_tb.sv','tests/mac_cdc_clock_model.sv')]
    hashes={str(p.relative_to(ROOT)):sha(p) for p in inputs}
    prior=json.loads(args.reuse_export_receipt.read_text()) if args.reuse_export_receipt else None
    if prior:
        assert prior['status']=='PASS_EXACT_SOURCE_EXPORT_ONLY','unqualified reuse receipt'
        for name,digest in prior['source_sha256'].items():
            assert sha(ROOT/name)==digest, 'reuse source drift: '+name
    args.output.mkdir(parents=True)
    report={'status':'RUNNING','source_sha256':hashes,'parameters':{},'cases':{},'commands':[],
            'synthesis_run':False,'physical_cdc_verified':False,'board_verified':False}
    inventory=json.loads((HERE/'mac-boundary-cdc-inventory.json').read_text())
    begin=time.monotonic()
    try:
        for slots in (1,2):
            rtl=Path(str(args.reuse_rtl_prefix.resolve())+str(slots)) if prior else args.output/f'rtl-slots{slots}'
            params={'txFrameSlots':slots,'maxFrameBytes':2048,'macRxSlots':4,'cpuHz':100000000,
                    'aonHz':50000000,'mediaHz':125000000,'hardwareClocks':True}
            if prior:
                assert prior['exports'][str(slots)]['parameters']==params,'reuse parameter mismatch'
                assert {p.name:sha(p) for p in sorted(rtl.glob('*.sv'))}==prior['exports'][str(slots)]['sha256'],'reuse RTL drift'
            else:
                command=[args.mill,'-i','IonSoC.test.runMain','ip.TriSpeedManagedBoundaryCdcMain',str(rtl),str(slots)]
                report['commands'].append(command)
                resources=runtime.run_logged(command,args.output/f'export-slots{slots}.log',900,cwd=ROOT)
                if resources['returncode']:raise RuntimeError(f'slots{slots} export failed')
                report.setdefault('export_resources',{})[str(slots)]=resources
            report['parameters'][str(slots)]=params
            audit=structural.audit(rtl,inventory)
            (args.output/f'structure-slots{slots}.json').write_text(json.dumps(audit,indent=2)+'\n')
            command=[sys.executable,str(HERE/'run_mac_boundary_cdc.py'),str(rtl),str(args.output/f'run-slots{slots}')]
            report['commands'].append(command)
            resources=runtime.run_logged(command,args.output/f'run-slots{slots}.log',900)
            if resources['returncode']:raise RuntimeError(f'slots{slots} asynchronous check failed')
            case=json.loads((args.output/f'run-slots{slots}/receipt.json').read_text())
            assert case['status']=='PASS_NATIVE_MAC_BOUNDARY_ONLY'
            report['cases'][str(slots)]={'status':case['status'],'summary':case['summary'],
                'runtime_receipt_sha256':sha(args.output/f'run-slots{slots}/receipt.json'),
                'rtl_sha256':audit['rtl_sha256']}
        report['status']='PASS_NATIVE_MAC_BOUNDARY_BATCH_ONLY'
    except BaseException as error:report.update(status='FAILED',failure=str(error))
    finally:
        if hashes!={str(p.relative_to(ROOT)):sha(p) for p in inputs}:report.update(status='FAILED',failure='input drift')
        report['elapsed_seconds']=time.monotonic()-begin
        (args.output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status']+' receipt='+str(args.output/'receipt.json'))
    if report['status']=='FAILED':raise SystemExit(report['failure'])


if __name__=='__main__':main()
