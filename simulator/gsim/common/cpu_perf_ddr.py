#!/usr/bin/env python3
"""Bounded DDR-resident exact-body observation on already emitted native CPU RTL.

No RTL edit, emission, conversion, installation, forced state or clock shortcut.
The existing ROM experiment supplies immutable inputs, never a new PASS result.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from cpu_boot_native import guard, run, sha, write_rom
from cpu_perf_native import make_tb, MARKERS

HERE = Path(__file__).resolve().parent
FROZEN = 'd2b2d4f7aa83bd9479424437d596e9a0e905159c'
BODY_SHA = '31193326af006e2ca93f160d4f4b5d1f07137486301eee84f1b5f6f96fd782e8'
PASS = 'COMMON_CPU_PERF_DDR_NATIVE_PASS'
FILES = ['cpu_perf_ddr.py', 'cpu_perf_ddr_loader.S', 'cpu_perf_ddr_monitor.sv',
         'cpu_perf_native.py', 'cpu_perf_monitor.sv', 'cpu_perf.S',
         'cpu_boot_native.py', 'cpu_boot_tb.sv', 'cpu_boot.ld']


def verify(files):
    for path, digest in files.items():
        if sha(path) != digest:
            raise RuntimeError('hash mismatch: ' + str(path))


def values(line):
    return {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--reference-run', type=Path)
    parser.add_argument('--boot-receipt', type=Path)
    parser.add_argument('--guest-dir', type=Path)
    parser.add_argument('--negative-from', type=Path, help='fresh negative evidence, reuse verified positive model')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh evidence directory required')
    if not 1 <= args.timeout <= 600:
        parser.error('total invocation bound must be <=600 seconds')
    guard(out.parent)
    out.mkdir()
    started = time.monotonic()
    record = dict(status='RUNNING', commands=[], results=[], physical_qualified=False,
                  board_equivalent=False, fixture_sha256={p: sha(HERE/p) for p in FILES})

    def save():
        (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')

    def execute(command, name, expected=None, negative=False):
        record['commands'].append(list(map(str, command)))
        save()
        remaining = args.timeout-(time.monotonic()-started)
        if remaining <= 0:
            raise RuntimeError('total invocation wall-time bound')
        result = run(command, out/name, remaining)
        result['log'] = name
        record['results'].append(result)
        save()
        log = (out/name).read_text()
        if result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('resource bound stopped '+name)
        if negative:
            if not result['returncode'] or expected not in log or PASS in log:
                raise RuntimeError('specific independent negative oracle did not reject '+name)
        elif result['returncode'] or (expected and expected not in log):
            raise RuntimeError('command failed or completion missing: '+name)
        return log

    try:
        if args.negative_from:
            prior_dir = args.negative_from.resolve()
            prior_path = prior_dir/'receipt.json'
            prior = json.loads(prior_path.read_text())
            if prior['status'] != 'PASS_COMMON_CPU_DDR_RESIDENT_PERF_OBSERVATION':
                raise RuntimeError('negative requires actual DDR positive receipt')
            verify({str(prior_dir/p): h for p, h in prior['artifact_sha256'].items()})
            verify({v['path']: v['sha256'] for v in prior['tools'].values()})
            if prior['fixture_sha256'] != record['fixture_sha256']:
                raise RuntimeError('negative fixture drift')
            record.update(positive_receipt=str(prior_path), positive_receipt_sha256=sha(prior_path),
                          profile=prior['profile'], model_sha256=sha(prior_dir/'run.vvp'))
            execute([*prior['run_command'], '+bad_pattern'], 'negative-pattern.log',
                    expected='COMMON_PERF_FINAL_PATTERN_ORACLE index=31', negative=True)
            record['status'] = 'PASS_DDR_PATTERN_NEGATIVE_REJECTED_AFTER_REAL_COMPLETION'
            return
        if not all([args.source_root, args.reference_run, args.boot_receipt, args.guest_dir]):
            parser.error('require source-root, reference-run, boot-receipt, guest-dir')
        source = args.source_root.resolve()
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != FROZEN:
            raise RuntimeError('wrong frozen source HEAD')
        reference_path = args.reference_run.resolve()/'receipt.json'
        reference = json.loads(reference_path.read_text())
        boot_path = args.boot_receipt.resolve()
        boot = json.loads(boot_path.read_text())
        emission_path = Path(reference['emission_receipt_path'])
        if sha(emission_path) != reference['emission_receipt_sha256']:
            raise RuntimeError('emission receipt changed')
        emission = json.loads(emission_path.read_text())
        if emission != reference['emission_receipt'] or emission != boot['emission_receipt']:
            raise RuntimeError('boot/perf emission mismatch')
        for section in ['sources', 'compiledClasspath', 'artifacts']:
            verify(emission[section])
        verify({str(source/p): h for p, h in boot['source_sha256'].items()})
        verify({v['path']: v['sha256'] for v in boot['tools'].values()})
        if reference['clocks'] != boot['clocks'] or reference['rtl_sha256'] != boot['rtl_sha256']:
            raise RuntimeError('boot/perf inputs diverged')
        verify(reference['rtl_sha256'])
        conversion = reference['conversion_receipt']
        if conversion:
            if conversion['status'] != 'PASS_SV2V_LOWERING_ONLY' or '--exclude=SeverityTask' not in conversion['command']:
                raise RuntimeError('assertion-preserving existing conversion required')
            verify(conversion['input_sha256'])
            verify(conversion['output_sha256'])
            verify({conversion['tool']['path']: conversion['tool']['sha256']})
            if conversion['output_sha256'] != reference['rtl_sha256'] or conversion['emission_sha256'] != sha(emission_path):
                raise RuntimeError('conversion/emission mismatch')
            original_text = '\n'.join(Path(p).read_text() for p in conversion['input_sha256'])
            lowered_text = '\n'.join(Path(p).read_text() for p in conversion['output_sha256'])
            for severity in ['$fatal', '$error']:
                if not original_text.count(severity) or original_text.count(severity) != lowered_text.count(severity):
                    raise RuntimeError('severity task mismatch')
        guest_dir = args.guest_dir.resolve()
        guest_path = guest_dir/'receipt.json'
        guest = json.loads(guest_path.read_text())
        verify({str(guest_dir/p): h for p, h in guest['artifact_sha256'].items()})
        verify({v['path']: v['sha256'] for v in guest['tools'].values()})
        verify({str(HERE/p): h for p, h in guest['fixture_sha256'].items()})
        body = (guest_dir/'guest.bin').read_bytes()
        if len(body) != 360 or sha(guest_dir/'guest.bin') != BODY_SHA or reference['guest_image_sha256'] != BODY_SHA:
            raise RuntimeError('original 360-byte body changed')
        if sha(guest_path) != reference['guest_receipt_sha256']:
            raise RuntimeError('original guest receipt changed')
        original_tb = make_tb()
        baseline_tb = args.reference_run.resolve()/'cpu_perf_tb.sv'
        if sha(baseline_tb) != reference['artifact_sha256']['cpu_perf_tb.sv'] or original_tb != baseline_tb.read_text():
            raise RuntimeError('original host/fixture drift')
        old_monitor = (HERE/'cpu_perf_monitor.sv').read_text()
        if original_tb.count(old_monitor) != 1:
            raise RuntimeError('observer splice ambiguity')
        tb = out/'cpu_perf_ddr_tb.sv'
        tb.write_text(original_tb.replace(old_monitor, (HERE/'cpu_perf_ddr_monitor.sv').read_text()))
        # Only observers change; original DDR initialization and service process
        # remain byte-for-byte identical, including global AR/AW ticket state.
        tool = {k: v['path'] for k, v in guest['tools'].items()}
        execute([tool['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
                 '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                 '-DPERF_BODY="'+str(guest_dir/'guest.bin')+'"', '-T'+str(HERE/'cpu_boot.ld'),
                 HERE/'cpu_perf_ddr_loader.S', '-o', out/'loader.elf'], 'build.log')
        execute([tool['objcopy'], '-O', 'binary', out/'loader.elf', out/'loader.bin'], 'objcopy.log')
        symbols_text = execute([tool['nm'], '-n', out/'loader.elf'], 'symbols.log')
        loader_symbols = {n: int(a, 16) for a, _, n in re.findall(r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', symbols_text, re.M)}
        if loader_symbols.get('_start') != 0x80000000 or loader_symbols.get('perf_body') != 0x80001000:
            raise RuntimeError('loader placement wrong')
        image = (out/'loader.bin').read_bytes()
        if len(image) != 4096+360 or image[4096:] != body:
            raise RuntimeError('body embedded bytes differ from original')
        rom = write_rom(image, out/'loader.hex')
        symbols = {k: guest['symbols'][k]+0x200000 for k in MARKERS}
        record.update(profile=reference['profile'], frozen_source_root=str(source), source_commit=actual,
                      hardware_compile_commit=reference['source_commit'], reference_receipt=str(reference_path),
                      reference_receipt_sha256=sha(reference_path), reference_role='input binding and ROM baseline only; not DDR qualification',
                      boot_receipt=str(boot_path), boot_receipt_sha256=sha(boot_path),
                      emission_receipt_path=str(emission_path), emission_receipt_sha256=sha(emission_path),
                      emission_receipt=emission, rtl_sha256=reference['rtl_sha256'],
                      conversion_receipt_sha256=reference['conversion_receipt_sha256'],
                      original_guest_receipt=str(guest_path), original_guest_receipt_sha256=sha(guest_path),
                      body_bytes=360, body_sha256=BODY_SHA, embedded_body_byte_identical=True,
                      loader_symbols=loader_symbols, symbols=symbols, rom=rom,
                      tools=boot['tools'], guest_tools=guest['tools'], clocks=reference['clocks'],
                      preserved=reference['preserved'], axi_host_model=reference['axi_host_model'],
                      service_law=reference['service_law'], host_byte_identical=True,
                      state_caveat='same service law; extra loader/code AR and AW alter ticket indices and edge phase, so individual response latencies are not matched',
                      instruction_state='first cacheable execution after real loader FENCE.I; no additional I-cache prewarming or repeated ROI',
                      classification='code addresses [0,0x10000); data three 4KiB apertures; independent public AXI ID -> R/B scoreboard; loader code reads include allocation, executable-phase code reads are instruction-path traffic',
                      measurement=reference['measurement'])
        binary = out/'run.vvp'
        execute([boot['tools']['iverilog']['path'], '-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1',
                 '-s', 'cpu_boot_tb', '-o', binary, *sorted(reference['rtl_sha256']), tb], 'compile.log')
        command = [boot['tools']['vvp']['path'], '-i', str(binary), '+rom_hex='+str(out/'loader.hex'),
                   '+cpu_half='+str(reference['clocks']['cpu_half_ps']), '+phase_ps=731', '+maxcycles=150000',
                   '+pc_fail='+format(symbols['perf_fail'], 'x'), '+pc_done='+format(symbols['perf_done'], 'x'),
                   '+loader_fence='+format(loader_symbols['loader_fence'], 'x'),
                   '+loader_fail='+format(loader_symbols['loader_fail'], 'x')]
        command += ['+'+k+'='+format(symbols[k], 'x') for k in MARKERS[:8]]
        record['run_command'] = command
        log = execute(command, 'positive.log', expected=PASS)
        rows = []; begins = {}; checkpoints = {}; classifications = {}
        for line in log.splitlines():
            v = values(line)
            if line.startswith('COMMON_PERF_WINDOW '):
                rows.append(v)
            elif line.startswith('COMMON_PERF_BEGIN '):
                begins[v['phase']] = v
            elif line.startswith('COMMON_DDR_WINDOW '):
                classifications[v['phase']] = v
            elif line.startswith('COMMON_DDR_CHECKPOINT '):
                checkpoints[v['stage']] = v
        if [r['phase'] for r in rows] != [0, 1, 2, 3] or sorted(checkpoints) != [0, 1, 2, 3]:
            raise RuntimeError('ordered windows/checkpoints missing')
        if ([r['retired'] for r in rows] != [768, 608, 1280, 1] or
            [r['loads'] for r in rows] != [256, 256, 512, 0] or [r['stores'] for r in rows] != [0, 0, 512, 0]):
            raise RuntimeError('retired workload differs')
        for row in rows:
            if row['end_ps']-row['begin_ps'] != row['cpu_cycles']*2*reference['clocks']['cpu_half_ps']:
                raise RuntimeError('cycle/time units disagree')
            row.update(classifications[row['phase']])
            row['ipc'] = row['retired']/row['cpu_cycles']
            row['data_r_bytes_per_fabric_cycle'] = 8*row['data_r']/row['fabric_cycles']
            row['accepted_w_bytes_per_fabric_cycle'] = 8*row['w']/row['fabric_cycles']
        record['windows'] = rows
        record['checkpoints'] = checkpoints
        record['drain_to_fence_retire'] = {unit: checkpoints[2][key]-begins[3][key]
                                          for unit, key in [('cpu_cycles', 'cpu_edge'), ('fabric_cycles', 'fabric_edge')]}
        record['fence_to_resumed_marker'] = {unit: rows[3][unit]-record['drain_to_fence_retire'][unit]
                                             for unit in ['cpu_cycles', 'fabric_cycles']}
        record['effective_copy'] = {
            'useful_bytes': 4096,
            'cpu_cycles': (rows[3]['end_ps']-rows[2]['begin_ps'])//(2*reference['clocks']['cpu_half_ps']),
            'elapsed_ps': rows[3]['end_ps']-rows[2]['begin_ps'],
            'fabric_cycles': rows[3]['fabric_cycles']+rows[2]['fabric_cycles']+begins[3]['fabric_edge']-
                             (begins[2]['fabric_edge']+rows[2]['fabric_cycles'])}
        record['effective_copy']['useful_bytes_per_fabric_cycle'] = 4096/record['effective_copy']['fabric_cycles']
        record['effective_copy']['useful_MB_per_second'] = 4096*1e6/record['effective_copy']['elapsed_ps']
        for section in ['sources', 'compiledClasspath', 'artifacts']:
            verify(emission[section])
        verify(reference['rtl_sha256'])
        verify({str(HERE/p): h for p, h in record['fixture_sha256'].items()})
        record['status'] = 'PASS_COMMON_CPU_DDR_RESIDENT_PERF_OBSERVATION'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['artifact_sha256'] = {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name != 'receipt.json'}
        record['artifact_bytes'] = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
        record['elapsed_seconds'] = time.monotonic()-started
        save()
        print(record['status']+' receipt='+str(out/'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
