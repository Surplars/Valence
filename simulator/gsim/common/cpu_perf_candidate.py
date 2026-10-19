#!/usr/bin/env python3
"""Observe a newly emitted common CPU candidate with the exact frozen perf fixture.

Unlike cpu_perf_native.py, this entry point requires a new emission/source/class
chain. A prior boot PASS supplies only reference configuration and tool identities;
it is never evidence that the candidate already passed boot or performance.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from cpu_boot_native import guard, run, sha
from cpu_perf_native import make_tb, MARKERS, PASS

HERE = Path(__file__).resolve().parent


def verify(files):
    for path, digest in files.items():
        if sha(path) != digest:
            raise RuntimeError('hash mismatch: '+str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--emission-receipt', type=Path, required=True)
    parser.add_argument('--conversion-receipt', type=Path)
    parser.add_argument('--reference-run', type=Path, required=True,
                        help='unchanged frozen performance evidence, passing or failing as recorded')
    parser.add_argument('--guest-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--negative-pattern', action='store_true')
    parser.add_argument('--validate-only', action='store_true', help='verify new input binding only; no compile or simulation')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh evidence directory required')
    guard(out.parent); out.mkdir()
    record = dict(status='RUNNING', commands=[], results=[],
                  scope='New DUT candidate, exact frozen guest/TB/synthetic service law; digital only',
                  physical_qualified=False, board_equivalent=False)
    def save():
        (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    def execute(command, name, expected=None, negative=False):
        record['commands'].append(list(map(str,command)));save()
        result=run(command,out/name,args.timeout);result['log']=name
        record['results'].append(result);save()
        log=(out/name).read_text()
        if result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('resource bound stopped '+name)
        if negative:
            if not result['returncode'] or expected not in log or PASS in log:
                raise RuntimeError('specific independent negative oracle did not reject '+name)
        elif result['returncode'] or (expected and expected not in log):
            raise RuntimeError('command failed or expected completion missing: '+name)
        return log
    try:
        source=args.source_root.resolve()
        actual_commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        if actual_commit!=args.source_commit:
            raise RuntimeError('candidate source HEAD differs from explicitly frozen commit')
        reference_dir=args.reference_run.resolve()
        reference_path=reference_dir/'receipt.json'
        reference=json.loads(reference_path.read_text())
        boot_path=Path(reference['boot_receipt'])
        if sha(boot_path)!=reference['boot_receipt_sha256']:
            raise RuntimeError('original boot reference receipt changed')
        boot=json.loads(boot_path.read_text())
        # Configuration/tools only. The old PASS is never assigned to this candidate.
        verify({v['path']:v['sha256'] for v in boot['tools'].values()})
        emission_path=args.emission_receipt.resolve()
        emission=json.loads(emission_path.read_text())
        reference_emission=boot['emission_receipt']
        exempt={'sources','compiledClasspath','artifacts'}
        reference_config={k:v for k,v in reference_emission.items() if k not in exempt}
        candidate_config={k:v for k,v in emission.items() if k not in exempt}
        if candidate_config!=reference_config:
            changes={k:[reference_config.get(k),candidate_config.get(k)] for k in set(reference_config)|set(candidate_config)
                     if reference_config.get(k)!=candidate_config.get(k)}
            raise RuntimeError('candidate changed preserved profile configuration: '+json.dumps(changes))
        for section in exempt:
            if not emission.get(section):
                raise RuntimeError('candidate emission lacks '+section)
            verify(emission[section])
        original_rtl={p:h for p,h in emission['artifacts'].items() if p.endswith('.sv')}
        if not original_rtl:
            raise RuntimeError('candidate emitted RTL missing')
        rtl=original_rtl
        conversion=None
        if args.conversion_receipt:
            conversion=json.loads(args.conversion_receipt.read_text())
            if (conversion.get('status')!='PASS_SV2V_LOWERING_ONLY' or
                conversion.get('input_sha256')!=original_rtl or
                conversion.get('emission_sha256')!=sha(emission_path) or
                '--exclude=SeverityTask' not in conversion.get('command',[])):
                raise RuntimeError('candidate conversion is not bound to this exact emission')
            verify({conversion['tool']['path']:conversion['tool']['sha256']})
            rtl=conversion['output_sha256'];verify(rtl)
            original_text='\n'.join(Path(p).read_text() for p in original_rtl)
            lowered='\n'.join(Path(p).read_text() for p in rtl)
            for severity in ['$fatal','$error']:
                if not original_text.count(severity) or original_text.count(severity)!=lowered.count(severity):
                    raise RuntimeError('candidate conversion changed assertion severity tasks')
        elif emission['cpu']=='a1':
            # Unlowered A1 is allowed only when already accepted by native Icarus;
            # no implicit conversion, source rewriting or fallback is attempted.
            pass
        guest_dir=args.guest_dir.resolve()
        guest_path=guest_dir/'receipt.json'
        guest=json.loads(guest_path.read_text())
        if guest['status']!='PASS_COMMON_PERF_GUEST_BUILD_ONLY':
            raise RuntimeError('passing original guest build required')
        verify({str(guest_dir/p):h for p,h in guest['artifact_sha256'].items()})
        if sha(guest_dir/'guest.bin')!=reference['guest_image_sha256']:
            raise RuntimeError('guest differs from frozen same-load reference')
        fixture={p:sha(HERE/p) for p in reference['fixture_sha256']}
        if fixture!=reference['fixture_sha256'] or fixture!=guest['fixture_sha256']:
            raise RuntimeError('frozen fixture source changed')
        tb=out/'cpu_perf_tb.sv';tb.write_text(make_tb())
        if sha(tb)!=reference['artifact_sha256']['cpu_perf_tb.sv']:
            raise RuntimeError('generated candidate testbench differs from frozen fixture')
        record.update(profile=emission['cpu'],source_commit=actual_commit,source_root=str(source),
                      reference_run=str(reference_dir),reference_receipt_sha256=sha(reference_path),
                      reference_status=reference['status'],reference_role='configuration, clock, tools, guest and testbench comparison only; not candidate qualification',
                      emission_receipt_path=str(emission_path),emission_receipt_sha256=sha(emission_path),
                      emission_receipt=emission,rtl_sha256=rtl,original_rtl_sha256=original_rtl,
                      conversion_receipt_sha256=sha(args.conversion_receipt) if args.conversion_receipt else None,
                      conversion_receipt=conversion,tools=boot['tools'],clocks=reference['clocks'],
                      guest_receipt_sha256=sha(guest_path),guest_image_sha256=sha(guest_dir/'guest.bin'),
                      testbench_sha256=sha(tb),fixture_sha256=fixture,candidate_runner_sha256=sha(__file__),
                      service_law=reference['service_law'],measurement=reference['measurement'],
                      preserved=reference['preserved'],axi_host_model=reference['axi_host_model'])
        if args.validate_only:
            record['status']='PASS_CANDIDATE_INPUT_BINDING_ONLY'
            return
        binary=out/'run.vvp'
        execute([boot['tools']['iverilog']['path'],'-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1',
                 '-s','cpu_boot_tb','-o',binary,*sorted(rtl),tb],'compile.log')
        symbols=guest['symbols']
        command=[boot['tools']['vvp']['path'],'-i',binary,'+rom_hex='+str(guest_dir/'guest.hex'),
                 '+cpu_half='+str(reference['clocks']['cpu_half_ps']),'+phase_ps=731','+maxcycles=150000',
                 '+pc_fail='+format(symbols['perf_fail'],'x'),'+pc_done='+format(symbols['perf_done'],'x')]
        command += ['+'+k+'='+format(symbols[k],'x') for k in MARKERS[:8]]
        log=execute(command,'positive.log',expected=PASS)
        rows=[];begins={};fence=None
        for line in log.splitlines():
            values={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            if line.startswith('COMMON_PERF_WINDOW '):rows.append(values)
            if line.startswith('COMMON_PERF_BEGIN '):begins[values['phase']]=values
            if line.startswith('COMMON_PERF_FENCE '):fence=values
        if [r['phase'] for r in rows]!=[0,1,2,3]:
            raise RuntimeError('missing ordered windows')
        if ([r['retired'] for r in rows]!=[768,608,1280,1] or
            [r['loads'] for r in rows]!=[256,256,512,0] or [r['stores'] for r in rows]!=[0,0,512,0]):
            raise RuntimeError('candidate retired a different workload')
        for row in rows:
            if row['end_ps']-row['begin_ps']!=row['cpu_cycles']*2*reference['clocks']['cpu_half_ps']:
                raise RuntimeError('candidate CPU/time units disagree')
            row['ipc']=row['retired']/row['cpu_cycles']
            row['accepted_r_bytes_per_fabric_cycle']=8*row['r']/row['fabric_cycles']
            row['accepted_w_bytes_per_fabric_cycle']=8*row['w']/row['fabric_cycles']
        if fence is None or fence['b_completed']!=64 or fence['writes']!=64:
            raise RuntimeError('real B-completed fence checkpoint missing')
        record['windows']=rows
        record['drain_to_fence_retire']={unit:fence[key]-begins[3][key] for unit,key in [('cpu_cycles','cpu_edge'),('fabric_cycles','fabric_edge')]}
        record['fence_to_resumed_marker']={unit:rows[3][unit]-record['drain_to_fence_retire'][unit] for unit in ['cpu_cycles','fabric_cycles']}
        if args.negative_pattern:
            execute([*command,'+bad_pattern'],'negative-pattern.log',
                    expected='COMMON_PERF_FINAL_PATTERN_ORACLE index=31',negative=True)
            record['negative_pattern']='PASS_HDL_REJECTED_WRONG_EXPECTED_WORD_AFTER_REAL_COMPLETION'
        for section in exempt:verify(emission[section])
        verify(rtl)
        if sha(__file__)!=record['candidate_runner_sha256']:
            raise RuntimeError('candidate runner changed during observation')
        record['status']='PASS_COMMON_CPU_NATIVE_CANDIDATE_SYNTHETIC_PERF_OBSERVATION'
    except BaseException as error:
        record.update(status='FAIL',error=repr(error));raise
    finally:
        record['artifact_sha256']={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        save();print(record['status']+' receipt='+str(out/'receipt.json'),flush=True)


if __name__=='__main__':main()
