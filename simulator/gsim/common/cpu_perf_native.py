#!/usr/bin/env python3
"""Short, unchanged-RTL common CPU performance observation; never physical signoff."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from cpu_boot_native import guard, run, sha, write_rom

HERE = Path(__file__).resolve().parent
FROZEN = 'df9821cd8be30898bf289a06350dd49d5ad65b66'
PASS = 'COMMON_CPU_PERF_NATIVE_PASS'
MARKERS = ['dep_begin', 'dep_end', 'ind_begin', 'ind_end', 'copy_begin', 'copy_end',
           'drain_begin', 'drain_end', 'perf_fail', 'perf_done', 'final_fence']


def verify_files(files):
    for path, digest in files.items():
        if sha(path) != digest:
            raise RuntimeError('hash mismatch: ' + str(path))


def make_tb():
    text = (HERE / 'cpu_boot_tb.sv').read_text()
    cut = text.index('  reg [63:0] trace_pc[0:15]')
    tail = text.index('\nendmodule', cut)
    text = text[:cut] + (HERE / 'cpu_perf_monitor.sv').read_text() + text[tail:]
    anchor = '    for(init_i=0;init_i<4096;init_i=init_i+1) monitor_ram[init_i]=0;'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '''
    // External DDR preload only, through the same memory serviced by real AXI.
    for(init_i=0;init_i<512;init_i=init_i+1) begin
      ram[(32'h10000>>3)+init_i]=64'h80210000+8*((init_i+1)%512);
      ram[(32'h20000>>3)+init_i]=64'h1234567800000000+init_i;
      ram[(32'h30000>>3)+init_i]=64'hbad0bad0bad0bad0;
    end''')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--tool-receipt', type=Path)
    parser.add_argument('--boot-receipt', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--guest-dir', type=Path)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--maxcycles', type=int, default=150000)
    parser.add_argument('--negative-pattern', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh output directory required')
    guard(out.parent)
    out.mkdir()
    record = dict(status='RUNNING', commands=[], results=[], source_commit=FROZEN,
                  physical_qualified=False, board_equivalent=False,
                  fixture_sha256={p.name: sha(p) for p in [Path(__file__), HERE/'cpu_perf.S',
                      HERE/'cpu_perf_monitor.sv', HERE/'cpu_boot_tb.sv', HERE/'cpu_boot.ld', HERE/'cpu_boot_native.py']})
    def save():
        (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')
    def execute(command, name, expected=None, negative=False, timeout=None):
        record['commands'].append(list(map(str, command))); save()
        result = run(command, out/name, timeout or args.timeout)
        result['log'] = name
        record['results'].append(result); save()
        log = (out/name).read_text()
        if result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('resource bound stopped '+name)
        if negative:
            if result['returncode'] == 0 or expected not in log or PASS in log:
                raise RuntimeError('negative control was not rejected by HDL oracle')
        elif result['returncode'] or (expected and expected not in log):
            raise RuntimeError('native command failed: '+name)
        return log
    try:
        if args.prepare_only:
            if not args.tool_receipt:
                parser.error('--prepare-only requires original guest --tool-receipt')
            prior = json.loads(args.tool_receipt.read_text())
            record['tools'] = prior['tools']
            verify_files({v['path']:v['sha256'] for v in prior['tools'].values()})
            tool = {k:v['path'] for k,v in prior['tools'].items()}
            execute([tool['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
                     '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                     '-T'+str(HERE/'cpu_boot.ld'), HERE/'cpu_perf.S', '-o', out/'guest.elf'], 'build.log', timeout=60)
            execute([tool['objcopy'], '-O', 'binary', out/'guest.elf', out/'guest.bin'], 'objcopy.log', timeout=60)
            symbols = execute([tool['nm'], '-n', out/'guest.elf'], 'symbols.log', timeout=60)
            symbols = {n:int(a,16) for a,_,n in re.findall(r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', symbols, re.M)}
            if symbols.get('_start') != 0x80000000 or any(k not in symbols for k in MARKERS):
                raise RuntimeError('precise PC symbols missing')
            record['symbols'] = {k:symbols[k] for k in MARKERS}
            record['guest_bytes'] = (out/'guest.bin').stat().st_size
            record['rom'] = write_rom((out/'guest.bin').read_bytes(), out/'guest.hex')
            record['status'] = 'PASS_COMMON_PERF_GUEST_BUILD_ONLY'
        else:
            if not all([args.boot_receipt, args.source_root, args.guest_dir]):
                parser.error('require --boot-receipt --source-root --guest-dir')
            root = args.source_root.resolve()
            commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            if commit != FROZEN:
                raise RuntimeError('wrong frozen source commit')
            prior = json.loads(args.boot_receipt.read_text())
            if prior['status'] != 'PASS_COMMON_CPU_NATIVE_SHORT_BOOT':
                raise RuntimeError('passing unchanged native boot receipt required')
            verify_files({str(root/k):v for k,v in prior['source_sha256'].items()})
            verify_files(prior['rtl_sha256'])
            verify_files({v['path']:v['sha256'] for v in prior['tools'].values()})
            manifest = prior['emission_receipt']
            if sha(prior['emission_receipt_path']) != prior['emission_receipt_sha256']:
                raise RuntimeError('emission receipt changed')
            for section in ['sources', 'compiledClasspath', 'artifacts']:
                verify_files(manifest[section])
            conversion = prior['conversion_receipt']
            if conversion:
                if conversion['status'] != 'PASS_SV2V_LOWERING_ONLY' or '--exclude=SeverityTask' not in conversion['command']:
                    raise RuntimeError('assertion-preserving conversion required')
                verify_files(conversion['input_sha256']); verify_files(conversion['output_sha256'])
                if conversion['output_sha256'] != prior['rtl_sha256'] or conversion['emission_sha256'] != prior['emission_receipt_sha256']:
                    raise RuntimeError('conversion/emission mismatch')
                originals = '\n'.join(Path(p).read_text() for p in conversion['input_sha256'])
                lowered = '\n'.join(Path(p).read_text() for p in conversion['output_sha256'])
                for severity in ['$fatal', '$error']:
                    if originals.count(severity) == 0 or originals.count(severity) != lowered.count(severity):
                        raise RuntimeError('production assertion severity changed')
            guest_dir = args.guest_dir.resolve()
            guest = json.loads((guest_dir/'receipt.json').read_text())
            if guest['status'] != 'PASS_COMMON_PERF_GUEST_BUILD_ONLY':
                raise RuntimeError('passing performance guest build required')
            verify_files({str(guest_dir/k):v for k,v in guest['artifact_sha256'].items()})
            if guest['fixture_sha256'] != record['fixture_sha256']:
                raise RuntimeError('guest/monitor source drift')
            record.update(profile=prior['profile'], boot_receipt=str(args.boot_receipt.resolve()),
                          boot_receipt_sha256=sha(args.boot_receipt), rtl_sha256=prior['rtl_sha256'],
                          emission_receipt_sha256=prior['emission_receipt_sha256'],
                          source_sha256=prior['source_sha256'], tools=prior['tools'], clocks=prior['clocks'],
                          guest_receipt_sha256=sha(guest_dir/'receipt.json'), guest_image_sha256=sha(guest_dir/'guest.bin'),
                          preserved=prior['preserved'], axi_host_model=prior['axi_host_model'],
                          service_law={
                            'units':'rising fabric clock edges, never CPU cycles',
                            'ar_ready':'fabric_edges % 5 not in [1,2]', 'aw_ready':'fabric_edges % 7 not in [2,3]',
                            'w_ready':'fabric_edges % 4 != 1',
                            'read_first_eligibility':'AR edge + 3 + (zero-based AR ticket * 7) % 13; newest eligible ticket first; held burst through RLAST',
                            'read_completion':'accepted RLAST, not AR acceptance; one 64-bit R beat per eligible edge when ready',
                            'write_backing_update':'after paired AW and all accepted W beats; bytes applied according to WSTRB',
                            'write_completion':'B handshake only; eligible at data-pairing edge + 23 + (current total AW count * 3) % 31',
                            'capacities':'unchanged 16 read owners/16 AW/128 W beats/16 B host queues; DUT 4 DDR slots/2 writes'},
                          measurement={'boundaries':'unique retired PC markers; exclude both marker instructions from retired count',
                            'cpu_cycles':'end CPU rising edge number minus begin CPU rising edge number',
                            'fabric_cycles':'fabric rising edges strictly between retired marker timestamps; reject coincident boundary edges',
                            'occupancy':'post-handshake owners, sampled 1ps after fabric rising edge; read AR through accepted RLAST, write AW through accepted B',
                            'cold_copy':'4096 bytes, 512 loads and 512 stores; retirement window reported separately from real B/maintenance completion',
                            'warm':'64 lines preloaded by guest, then 256 dependent loads and 256 loads grouped eight independent destinations',
                            'excluded':'ROM programming, prewarm, checking, UART; no steady-state DRAM bandwidth or board claim'})
            tb = out/'cpu_perf_tb.sv'; tb.write_text(make_tb())
            binary = out/'run.vvp'
            compile_command = [prior['tools']['iverilog']['path'], '-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1',
                               '-s', 'cpu_boot_tb', '-o', binary, *sorted(prior['rtl_sha256']), tb]
            execute(compile_command, 'compile.log')
            symbols = guest['symbols']
            command = [prior['tools']['vvp']['path'], '-i', binary,
                       '+rom_hex='+str(guest_dir/'guest.hex'), '+cpu_half='+str(prior['clocks']['cpu_half_ps']),
                       '+phase_ps=731', '+maxcycles='+str(args.maxcycles),
                       '+pc_fail='+format(symbols['perf_fail'],'x'), '+pc_done='+format(symbols['perf_done'],'x')]
            command += ['+'+k+'='+format(symbols[k],'x') for k in MARKERS[:8]]
            log = execute(command, 'positive.log', expected=PASS)
            rows = []
            for line in log.splitlines():
                if line.startswith('COMMON_PERF_WINDOW '):
                    rows.append({k:int(v) for k,v in re.findall(r'(\w+)=(\d+)', line)})
            if [r['phase'] for r in rows] != [0,1,2,3]:
                raise RuntimeError('all four ordered observation windows required')
            for row in rows:
                if row['end_ps']-row['begin_ps'] != row['cpu_cycles']*2*prior['clocks']['cpu_half_ps']:
                    raise RuntimeError('CPU cycle/timebase mismatch')
                row['ipc'] = row['retired']/row['cpu_cycles']
                row['accepted_r_bytes_per_fabric_cycle'] = 8*row['r']/row['fabric_cycles']
                row['accepted_w_bytes_per_fabric_cycle'] = 8*row['w']/row['fabric_cycles']
            record['windows'] = rows
            if args.negative_pattern:
                execute([*command, '+bad_pattern'], 'negative-pattern.log', expected='COMMON_PERF_FINAL_PATTERN_ORACLE index=31', negative=True)
                record['negative_pattern'] = 'PASS_HDL_REJECTED_WRONG_EXPECTED_WORD_AFTER_REAL_COMPLETION'
            verify_files(prior['rtl_sha256'])
            verify_files({str(root/k):v for k,v in prior['source_sha256'].items()})
            record['status'] = 'PASS_COMMON_CPU_NATIVE_SYNTHETIC_PERF_OBSERVATION'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['artifact_sha256'] = {p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        record['artifact_bytes'] = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
        save()
        print(record['status']+' receipt='+str(out/'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
