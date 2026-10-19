#!/usr/bin/env python3
"""Bind an existing severity-preserving sv2v conversion to a new native emission."""
import argparse
import json
from pathlib import Path
import shlex

from cpu_boot_native import guard, run, sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--emission-receipt',type=Path,required=True)
    parser.add_argument('--tool-receipt',type=Path,required=True,
                        help='existing successful sv2v conversion/tool receipt; no installation')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.parent.is_dir():parser.error('fresh output directory required')
    guard(out.parent);out.mkdir()
    record=dict(status='RUNNING',scope='Existing sv2v standards lowering only; no original RTL edits or assertion removal')
    def save():(out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    try:
        emission=args.emission_receipt.resolve();manifest=json.loads(emission.read_text())
        for section in ['sources','compiledClasspath','artifacts']:
            for path,digest in manifest[section].items():
                if sha(path)!=digest:raise RuntimeError('emission changed: '+path)
        original={p:h for p,h in manifest['artifacts'].items() if p.endswith('.sv')}
        if not original:raise RuntimeError('no emitted SystemVerilog')
        tool=json.loads(args.tool_receipt.read_text())['tool']
        if sha(tool['path'])!=tool['sha256']:raise RuntimeError('existing sv2v tool changed')
        command=[tool['path'],'--exclude=SeverityTask','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1',*sorted(original)]
        output=out/'lowered.sv'
        shell=shlex.join(command)+' > '+shlex.quote(str(output))+' 2> '+shlex.quote(str(out/'convert.stderr'))
        record.update(tool=tool,input_sha256=original,emission_profile=str(emission),emission_sha256=sha(emission),
                      command=command,runner_sha256=sha(__file__),wrapper_command=['bash','-c',shell])
        save();result=run(['bash','-c',shell],out/'guard.log',120);record['result']=result;save()
        if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('bounded conversion failed')
        original_text='\n'.join(Path(p).read_text() for p in original)
        converted=output.read_text();counts={}
        for severity in ['$fatal','$error']:
            counts[severity]=dict(original=original_text.count(severity),converted=converted.count(severity))
            if counts[severity]['original']==0 or counts[severity]['original']!=counts[severity]['converted']:
                raise RuntimeError('assertion severity altered: '+severity)
        for path,digest in original.items():
            if sha(path)!=digest:raise RuntimeError('original emitted RTL changed during conversion')
        record.update(status='PASS_SV2V_LOWERING_ONLY',severity_counts=counts,output_sha256={str(output):sha(output)})
    except BaseException as error:
        record.update(status='FAIL',error=repr(error));raise
    finally:
        record['artifacts']={str(p):sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        save();print(record['status']+' receipt='+str(out/'receipt.json'),flush=True)


if __name__=='__main__':main()
