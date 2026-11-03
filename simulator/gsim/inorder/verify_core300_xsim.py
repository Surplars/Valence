#!/usr/bin/env python3
"""Independently validate actual Windows xsim traces using the existing ISA/bus/CRC oracles."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
WINDOWS = Path('/mnt/e/VM/Share/Valence-rtl/Valence-InOrder')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(path):
    value = PureWindowsPath(path)
    if value.drive.upper() == 'E:':
        resolved = Path('/mnt/e', *value.parts[1:]).resolve()
        if resolved.is_relative_to(WINDOWS):
            return resolved
    if path.startswith('\\\\wsl.localhost\\Ubuntu-24.04\\home\\openion\\Valence-InOrder\\'):
        return Path('/', *value.parts[1:]).resolve()
    raise RuntimeError('unexpected source path: '+path)



def check_ram(trace, dump, payload):
    # Reconstruct only ACKNOWLEDGED bus writes from actual Q/C/V frames.
    # No CPU/DUT cache/tag data is consulted. The C++ ISA oracle separately
    # compares these same bus write effects against architectural stores.
    memory=bytearray(payload.read_bytes());memory.extend(bytes(73728-len(memory)))
    owners=[None,None];flags=0;writes=0
    with trace.open() as stream:
        for line in stream:
            fields=line.split()
            if fields[0]=='C':flags=int(fields[2],16)
            elif fields[0]=='Q':
                port=int(fields[1],16)
                if (flags>>(18+port))&1:
                    if owners[port] is not None:raise RuntimeError('RAM ledger duplicate burst owner')
                    owners[port]=list(map(lambda value:int(value,16),fields[2:]))
            elif fields[0]=='V':
                port=int(fields[1],16)
                if (flags>>(15+port))&1 and (flags>>(24+port))&1:
                    owner=owners[port]
                    if owner is None:raise RuntimeError('RAM ledger unowned response')
                    address,write,data,mask,beats=owner
                    if write and not ((flags>>(22+port))&1):
                        for lane in range(8):
                            index=address-0x80000000+lane
                            if (mask>>lane)&1:
                                if not 0<=index<len(memory):raise RuntimeError('RAM write outside memory')
                                memory[index]=(data>>(lane*8))&255
                        writes+=1
                    owners[port]=None
    actual=bytearray(len(memory));address=0;seen=0
    for line in dump.read_text().splitlines():
        line=line.split('//',1)[0]
        for token in line.split():
            if token.startswith('@'):address=int(token[1:],16)
            else:
                if address>=len(actual):raise RuntimeError('RAM dump overflow')
                actual[address]=int(token,16);address+=1;seen+=1
    if seen!=len(memory) or actual!=memory:
        raise RuntimeError('actual xsim final RAM differs from independent bus-write ledger')
    return dict(bytes=len(memory),acknowledged_writes=writes,sha256=hashlib.sha256(actual).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path, required=True)
    parser.add_argument('--export', dest='rtl', type=Path, required=True)
    parser.add_argument('--reference-run', type=Path, required=True)
    parser.add_argument('--candidate-run', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'build'):
        parser.error('fresh repository build/ output required')
    accepted, exported = json.loads(args.acceptance.read_text()), json.loads(args.rtl.read_text())
    if accepted['status'] != 'PASS_I1_CORE300_SHORT_FUNCTIONAL_ONLY' or exported['status'] != 'PASS_I1_ACCEPTED_BATCH_MASKED_RAM_RTL_EXPORT':
        raise RuntimeError('functional/RTL export gate failed')
    payload = Path(accepted['coremark_reference']['path']).parent/'payload/coremark.bin'
    if sha(payload) != accepted['payload']['binary_sha256']:
        raise RuntimeError('fixed official workload binary drift')
    harness = ROOT/'simulator/gsim/harness'
    sources = [harness/name for name in ['five_stage_coremark.cpp', 'five_stage.cpp',
                                        'i1_prediction_metrics.h', 'i1_xsim_replay.h']]
    frozen = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    output.mkdir(parents=True)
    (output/'I1PerformanceCachedCore.h').write_text('#include "i1_xsim_replay.h"\n')
    receipt = dict(status='RUNNING', scope='actual xsim traces; independent ISA, bus, CRC, RAM and prediction checks',
                   acceptance_sha256=sha(args.acceptance), export_sha256=sha(args.rtl),
                   oracle_source_sha256=frozen, verifier_sha256=sha(Path(__file__)), clock_hz=300000000, samples=[], commands=[],
                   formal_score=False, physical_qualified=False)
    def save():
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(cmd, log, trace=None, negative=None):
        cmd = list(map(str,cmd))
        receipt['commands'].append(dict(argv=cmd,log=str(log),trace=str(trace) if trace else None))
        save()
        env = {**os.environ, **({'VALENCE_XSIM_TRACE':str(trace)} if trace else {})}
        result = subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True)
        text = result.stdout+result.stderr
        log.write_text(text)
        if negative:
            if not result.returncode or negative not in text:
                raise RuntimeError('negative check was not rejected: '+str(log))
        elif result.returncode:
            raise RuntimeError('oracle failed: '+str(log))
        return text
    try:
        check = output/'check'
        run(['clang++-19','-std=c++17','-O2','-DI1_COREMARK_PREDICTION=1',
             '-I'+str(output),'-I'+str(harness),harness/'five_stage_coremark.cpp','-o',check],output/'compile.log')
        receipt['oracle_binary_sha256'] = sha(check)
        symbols = accepted['payload']['symbols']
        for role, path in [('reference',args.reference_run),('candidate',args.candidate_run)]:
            simulated = json.loads(path.read_text())
            if simulated['status'] != 'PASS_XSIM_COREMARK_TRACE_ONLY_ORACLE_PENDING':
                raise RuntimeError('xsim did not complete without source drift: '+str(path))
            for name,digest in simulated['source_sha256'].items():
                actual = local(name)
                if sha(actual) != digest:
                    raise RuntimeError('xsim source drift: '+name)
                if actual.suffix == '.sv' and actual.name != 'coremark300_tb.sv':
                    relative = role+'/simulation/'+actual.name
                    if exported['rtl_sha256'].get(relative) != digest:
                        raise RuntimeError('xsim RTL differs from frozen export: '+relative)
            for row in simulated['samples']:
                latency = row['latency']
                folder = output/(role+'-l'+str(latency))
                folder.mkdir()
                trace = local(row['trace'])
                if sha(trace) != row['trace_sha256']:
                    raise RuntimeError('xsim trace drift')
                ram=local(row['final_ram'])
                if sha(ram)!=row['final_ram_sha256']:raise RuntimeError('actual RAM dump drift')
                actual_ram=check_ram(trace,ram,payload)
                if role=='candidate' and latency==1:
                    damaged=folder/'wrong-final-ram.mem'
                    lines=ram.read_text().splitlines()
                    for index,line in enumerate(lines):
                        stripped=line.strip()
                        if stripped and not stripped.startswith(('@','//')):
                            fields=line.split();fields[0]=format(int(fields[0],16)^1,'02x')
                            lines[index]=' '.join(fields);break
                    damaged.write_text('\n'.join(lines)+'\n')
                    try:
                        check_ram(trace,damaged,payload)
                    except RuntimeError as error:
                        if 'actual xsim final RAM differs' not in str(error):raise
                        (folder/'wrong-final-ram.log').write_text(str(error)+'\n')
                        receipt['actual_ram_negative_rejected']=True
                    else:raise RuntimeError('corrupted actual RAM was not rejected')
                cmd = [check,payload,symbols['coremark_validation_errors'],symbols['coremark_elapsed_ticks'],
                       symbols['coremark_crcs'],latency]
                text = run(cmd,folder/'positive.log',trace)
                metrics = json.loads(re.search(r'MATCHED_COREMARK_PASS (.+)',text)[1])
                metrics.update(json.loads(re.search(r'I1_COREMARK_PREDICTION (.+)',text)[1]))
                expected = next(value for value in accepted['profiles'][role]['coremark'] if value['memory_latency']==latency)
                # SV's completion marker records the last zero-based cycle index.
                # The original C++ loop reports the number of consumed trace frames.
                for key,value in metrics.items():
                    target = expected[key]+1 if key=='cycles' else expected[key]
                    if value != target:
                        raise RuntimeError('xsim/GSIM metric mismatch '+role+' '+key)
                if metrics['cycles'] != row['cycles']+1 or metrics['retired'] != row['retired']:
                    raise RuntimeError('trace termination count mismatch')
                run([*cmd,'--inject'],folder/'wrong-register.log',trace,'independent register oracle mismatch')
                run([*cmd,'--inject-prediction-observer'],folder/'wrong-prediction.log',trace,'prediction observation mismatch')
                # Corrupt a response in the ACTUAL trace, independently of CPU/oracle expectations.
                bad = folder/'wrong-response.trace'
                with trace.open() as source, bad.open('w') as dest:
                    for line in source:
                        if line.startswith('V '):
                            fields=line.split();fields[2]=format(int(fields[2],16)^1,'x')
                            dest.write(' '.join(fields)+'\nZ\n')
                            break
                        dest.write(line)
                run(cmd,folder/'wrong-response.log',bad,'independent memory response mismatch')
                receipt['samples'].append(dict(role=role,latency=latency,metrics=metrics,
                    simulation_receipt_sha256=sha(path),trace_sha256=sha(trace),actual_final_ram=actual_ram,
                    register_prediction_response_negatives='REJECTED',trace_frames_minus_completion_index=1))
                save()
        for name,digest in frozen.items():
            if sha(ROOT/name)!=digest:
                raise RuntimeError('oracle source drift')
        receipt['status']='PASS_ACTUAL_XSIM_COREMARK_INDEPENDENT_ISA_BUS_CRC_RAM_PREDICTION'
    except BaseException as error:
        receipt.update(status='FAIL',error=repr(error))
        raise
    finally:
        save()
    print(json.dumps(dict(status=receipt['status'],receipt=str(output/'receipt.json'))))


if __name__ == '__main__':
    main()
