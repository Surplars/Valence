#!/usr/bin/env python3
"""Explicit bounded native Icarus exception for actual I1 two-clock short boot.

GSIM remains the unchanged supported single-clock project flow. Pinned GSIM
93b8cd23 advances all registers on step(), without independent edge evaluation.
This runner never elaborates/rebuilds the DUT or invokes Verilator/Vivado/Linux.
The centrally emitted single and independent modes must have identical profiles.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import shlex
import subprocess
import time

FLOOR = 4 * 1024**3
PASS = 'I1_INDEPENDENT_BOOT_NATIVE_PASS'
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def guard(path):
    free = shutil.disk_usage(path).free
    if free < FLOOR:
        raise RuntimeError(f'4 GiB disk floor: {free} bytes available')
    return free


def run(command, log_path, timeout):
    before = time.monotonic()
    minimum = guard(log_path.parent)
    timed_out = breached = killed = False
    def no_core_dump():
        resource.setrlimit(resource.RLIMIT_CORE, (0,0))
    with log_path.open('w') as log:
        child = subprocess.Popen(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT,
                                 cwd=ROOT, start_new_session=True, preexec_fn=no_core_dump)
        while True:
            minimum = min(minimum, shutil.disk_usage(log_path.parent).free)
            breached |= minimum < FLOOR
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            timed_out |= time.monotonic() - before > timeout
            if (timed_out or breached) and not killed:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                killed = True
            time.sleep(0.02)
    return dict(returncode=child.returncode, seconds=time.monotonic()-before,
                maxrss_kib=usage.ru_maxrss, minimum_free_bytes=minimum,
                timed_out=timed_out, disk_floor_breached=breached, process_group_killed=killed)


def sources():
    # Include all production Scala shared IP, not only the new wrapper.
    paths = sorted((ROOT/'src/main/scala').rglob('*.scala'))
    paths += [ROOT/'src/test/scala/inorder/I1IndependentClockSocMain.scala',
              ROOT/'src/main/resources/inorder/bootrom.hex',
              ROOT/'simulator/gsim/inorder/soc_smoke.S', ROOT/'simulator/gsim/inorder/soc_link.ld',
              HERE/'i1_independent_boot.S', HERE/'i1_independent_boot_tb.sv', Path(__file__).resolve()]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def build_guest(output, prefix):
    output.mkdir(parents=True, exist_ok=False)
    record = {'status': 'RUNNING', 'commands': [], 'resources': []}
    gcc, objcopy, nm = (Path(prefix + name).resolve() for name in ('gcc', 'objcopy', 'nm'))
    record['tools'] = {name: {'path': str(path), 'sha256': sha(path)}
                       for name, path in (('gcc', gcc), ('objcopy', objcopy), ('nm', nm))}
    elf, binary = output/'guest.elf', output/'guest.bin'
    commands = [([gcc, '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
                 '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                 '-T'+str(ROOT/'simulator/gsim/inorder/soc_link.ld'), HERE/'i1_independent_boot.S',
                 '-o', elf], 'build.log'),
                ([objcopy, '-O', 'binary', elf, binary], 'objcopy.log'),
                ([nm, '-n', elf], 'symbols.log')]
    try:
        for command, log in commands:
            record['commands'].append(list(map(str, command)))
            result = run(command, output/log, 60)
            record['resources'].append(result)
            if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError('guest build failed: '+str(output/log))
        image = binary.read_bytes()
        if len(image)>65536:
            raise RuntimeError('guest exceeded its 64 KiB code aperture')
        padded = image + bytes((-len(image)) % 8)
        (output/'guest.hex').write_text(''.join(f'{int.from_bytes(padded[n:n+8], "little"):016x}\n'
                                               for n in range(0,len(padded),8)))
        symbols = dict((name, int(address,16)) for address, _, name in
                       re.findall(r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$',
                                  (output/'symbols.log').read_text(), re.M))
        required = ['fault_mmio','fault_axi_read','fault_axi_write','fault_ecall','success_break']
        if any(name not in symbols for name in required):
            raise RuntimeError('precise fault PC symbols are missing')
        record.update(status='PASS_GUEST_BUILD_ONLY', image_bytes=len(image), image_words=len(padded)//8,
                      symbols={name:symbols[name] for name in required},
                      source_sha256={str(p.relative_to(ROOT)):sha(p) for p in
                        [HERE/'i1_independent_boot.S', ROOT/'simulator/gsim/inorder/soc_link.ld']},
                      artifact_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file()})
    except BaseException as error:
        record.update(status='FAILED', failure=str(error))
        raise
    finally:
        (output/'guest-receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output', type=Path)
    ap.add_argument('--prepare-only', action='store_true')
    ap.add_argument('--cross-prefix')
    ap.add_argument('--guest-dir', type=Path)
    ap.add_argument('--independent-rtl', type=Path)
    ap.add_argument('--single-rtl', type=Path)
    ap.add_argument('--profile', choices=['test-only','full-cpu'])
    ap.add_argument('--iverilog', default=os.environ.get('IVERILOG','iverilog'))
    ap.add_argument('--vvp', default=os.environ.get('VVP','vvp'))
    ap.add_argument('--timeout', type=int, default=240)
    ap.add_argument('--maxcycles', type=int, default=600000)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.parent.is_dir():
        ap.error('fresh output directory with existing parent required; no evidence is overwritten')
    guard(output.parent)
    if args.prepare_only:
        if not args.cross_prefix:
            ap.error('--prepare-only requires --cross-prefix')
        record = build_guest(output,args.cross_prefix)
        print(record['status']+' receipt='+str(output/'guest-receipt.json'))
        return
    if not (args.independent_rtl and args.single_rtl and args.profile and args.guest_dir):
        ap.error('explicit --profile, --independent-rtl, --single-rtl and --guest-dir are mandatory')
    guest_dir = args.guest_dir.resolve()
    guest = json.loads((guest_dir/'guest-receipt.json').read_text())
    if guest['status']!='PASS_GUEST_BUILD_ONLY':
        ap.error('passing guest build receipt required')
    for name,digest in guest['artifact_sha256'].items():
        if sha(guest_dir/name)!=digest:
            ap.error('guest artifact hash mismatch: '+name)
    for name,digest in guest['source_sha256'].items():
        if sha(ROOT/name)!=digest:
            ap.error('guest source hash mismatch: '+name)
    tools = {name:shutil.which(value) for name,value in [('iverilog',args.iverilog),('vvp',args.vvp)]}
    if not all(tools.values()):
        ap.error('existing explicit Icarus/VVP required; installation and fallback are unsupported')
    rtl = {mode:sorted(path.resolve().glob('*.sv')) for mode,path in
           [('independent',args.independent_rtl),('single',args.single_rtl)]}
    for mode,files in rtl.items():
        if not files or not any('module I1IndependentClockHarness' in p.read_text() for p in files):
            ap.error('missing fresh '+mode+' harness RTL')
        if any('automatic logic' in p.read_text() for p in files):
            ap.error('export disallowLocalVariables; no DUT compatibility rewrite is permitted')
        if not any('$fatal' in p.read_text() for p in files):
            ap.error('inline production assertions required: export --default-layer-specialization=enable')
        if any(re.search(r'^\s*bind\s', p.read_text(), re.M) for p in files):
            ap.error('Icarus does not support bind; enable verification layers in standard firtool emission')
    manifests = {}
    manifest_hashes = {}
    rom_digest = sha(ROOT/'src/main/resources/inorder/bootrom.hex')
    for mode,directory in [('independent',args.independent_rtl),('single',args.single_rtl)]:
        manifest_path = directory.resolve()/'emission-profile.json'
        manifest = json.loads(manifest_path.read_text())
        expected = {'schema':1,'mode':mode,'profile':args.profile,
            'isa':('rv64ima_zicsr_zifencei' if args.profile=='test-only' else 'rv64imafdc_zicsr_zifencei_svade'),
            'instructionCacheBytes':2048 if args.profile=='test-only' else 32768,
            'dataCacheBytes':2048 if args.profile=='test-only' else 32768,
            'coherentCacheWays':2,'cacheLineBytes':64,'ddrSlots':2,'ddrWriteSlots':1,
            'fabricClockHz':50000000,'uartBaud':460800,
            'heldFifo':'HeldResponseCdcDataFifo' if mode=='independent' else 'synchronous',
            'fifoDepth':16 if mode=='independent' else 0,
            'pmpEntries':0 if args.profile=='test-only' else 8,
            'branchPredictorEntries':0 if args.profile=='test-only' else 128,
            'withJtagLoader':False,'managedPeripherals':False,'withNetwork':False,
            'fullBoardQualified':False,'romSha256':rom_digest,
            'loweringOptions':['disallowLocalVariables','disallowPackedArrays'],
            'defaultLayerSpecialization':'enable','verificationFlavor':'if-else-fatal'}
        for key,value in expected.items():
            if manifest.get(key)!=value:
                ap.error(f'{mode} emission manifest mismatch: {key} expected {value!r}, got {manifest.get(key)!r}')
        manifests[mode] = manifest
        manifest_hashes[str(manifest_path)] = sha(manifest_path)
    comparable = lambda m: {k:v for k,v in m.items() if k not in ['mode','heldFifo','fifoDepth']}
    if comparable(manifests['independent']) != comparable(manifests['single']):
        ap.error('same-parameter control differs from independent profile')
    frozen = sources()
    rtl_hashes = {mode:{str(p):sha(p) for p in files} for mode,files in rtl.items()}
    output.mkdir()
    (output/'fixture').mkdir()
    for fixture in [HERE/'i1_independent_boot.S',HERE/'i1_independent_boot_tb.sv',Path(__file__).resolve()]:
        shutil.copy2(fixture,output/'fixture'/fixture.name)
    tool_chain = {name:path for name,path in tools.items()}
    compiler = Path(tools['iverilog'])
    if compiler.read_bytes()[:2]==b'#!':
        for line in compiler.read_text().splitlines():
            if line.startswith('exec '):
                words=shlex.split(line)
                if Path(words[1]).is_file(): tool_chain['iverilog_engine']=words[1]
                if '-B' in words:
                    directory=Path(words[words.index('-B')+1])
                    for engine in ['ivl','ivlpp']:
                        if (directory/engine).is_file(): tool_chain[engine]=str(directory/engine)
    report = dict(status='RUNNING', profile=args.profile, source_sha256=frozen,
        emission_profiles=manifests, emission_profile_sha256=manifest_hashes,
        rtl_sha256=rtl_hashes, rtl_bytes={mode:sum(p.stat().st_size for p in files) for mode,files in rtl.items()},
        tools=tool_chain, tool_sha256={name:sha(path) for name,path in tool_chain.items()},
        guest_receipt=str(guest_dir/'guest-receipt.json'), guest_receipt_sha256=sha(guest_dir/'guest-receipt.json'),
        scope='actual CPU/cache/five-channel CDC/uncached/LineGrant/fabric/ROM/MMIO/AXI short digital boot',
        profile_scope=('TEST_ONLY 2 KiB RV64IMA functional fixture; not production geometry' if args.profile=='test-only'
                       else 'FULL_CPU 32 KiB feature geometry; guest uses RV64IMA subset, not complete ISA qualification'),
        why_gsim_unsupported='pinned GSIM 93b8cd23 step() advances all registers; no supported independent-edge evaluation API',
        gsim_baseline='unchanged single-clock project baseline remains supported; native exception is bounded to this test',
        physical_qualified=False, board_equivalent=False,
        unsupported=['metastability','routed CDC/timing','board boot','clock gating','single-sided hot reset',
                     'transaction-retaining warm reset','JTAG/CMU maintenance CDC','64-bit time rollover',
                     'full Linux','full ISA/performance qualification'],
        preserved={'ddr_read_slots':2,'ddr_write_owners':1,'coherent_channels':['A','B','C','D','E'],
                   'uncached_ports':2,'line_grants':True,'writeback_overlap':True,'read_overlap':True,
                   'whole_line':True,'cache_ways':2,'line_bytes':64,'cdc_fifo':'II1 held-response depth16'},
        timebase={'fabric_clock_hz':50000000,'uart_baud':460800,'timer_tick':'one per fabric edge',
                  'cpu_time':'atomic mailbox snapshot, monotonic/progress asserted',
                  'ddr_ready':'held low through serialized ROM banner, then 2000 additional fabric edges'},
        axi_model={'low_ram_bytes':262144,'high_aperture_tail_bytes':64,'aperture_bytes':2147483648,
                   'read_owners':16,'write_address_owners':16,'write_beats':128,'response_owners':16,
                   'last_beat_read_error_offset':'0x18000','write_b_error_offset':'0x18008',
                   'independent_aw_w':True,'response_backpressure_hold':True,'out_of_order_read_selection':True},
        exact_coverage=['common cold reset and clock-lock hold','ROM banner/DDR-ready then RAM retirement',
          '128 dependent 64-bit RAM stores/loads and coherent final reads','2 GiB final-word byte lane',
          'timer high-half MMIO','MSIP/MTIP/PLIC UART internal loopback','actual 33-byte serial BootROM UART banner',
          'denied MMIO load and last-beat AXI R fault with precise PC','AMO write B fault with precise PC',
          'LR/SC success with bounded retry','LR/ecall/MRET/SC failure','LR/cached-store/SC failure',
          'dirty final state through coherent networkMemory probes','AXI geometry/held offers/strobes/WLAST'],
        disk_floor_bytes=FLOOR,free_before_bytes=guard(output),commands=[],resources=[],positive_cases={},negative_cases={})
    (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    started = time.monotonic()
    try:
        binaries = {}
        for mode,files in rtl.items():
            # Preprocess DUT-only input under the exact active assertion macros.
            # Keep evidence; checking TB $fatal calls would not prove DUT asserts.
            preprocess=output/(mode+'-assertions-preprocessed.sv')
            command=[tools['iverilog'],'-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-DENABLE_INITIAL_MEM_=1',
                     '-E','-o',str(preprocess),*map(str,files)]
            report['commands'].append(command)
            result=run(command,output/(mode+'-preprocess.log'),args.timeout)
            report['resources'].append(dict(label=mode+'-preprocess',**result))
            if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError(mode+' production assertion preprocessing failed')
            preprocessed_text=preprocess.read_text()
            rom_reads=re.findall(r'\$readmemh\s*\(\s*"([^"]+)"',preprocessed_text)
            if rom_reads != [str(ROOT/'src/main/resources/inorder/bootrom.hex')]:
                raise RuntimeError(mode+' expected exactly the checked ROM readmemh: '+repr(rom_reads))
            fatal_count=preprocessed_text.count('$fatal')
            if fatal_count==0: raise RuntimeError(mode+' production assertions are inactive')
            report.setdefault('production_assertions',{})[mode]={'preprocessed_fatal_count':fatal_count,
                'path':str(preprocess),'sha256':sha(preprocess),'rom_readmemh':rom_reads,'macros':{'STOP_COND':1,'ASSERT_VERBOSE_COND':1,'ENABLE_INITIAL_MEM_':1}}
            binary = output/(mode+'.vvp');binaries[mode]=binary
            command = [tools['iverilog'],'-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-DENABLE_INITIAL_MEM_=1',
                       '-s','i1_independent_boot_tb','-o',str(binary),
                       *map(str,files),str(HERE/'i1_independent_boot_tb.sv')]
            if mode=='independent': command.insert(1,'-DI1_OBSERVE_CDC')
            report['commands'].append(command)
            result=run(command,output/(mode+'-compile.log'),args.timeout)
            report['resources'].append(dict(label=mode+'-compile',**result))
            if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError(mode+' Icarus compile failed')
            report.setdefault('binary',{})[mode]={'path':str(binary),'bytes':binary.stat().st_size,'sha256':sha(binary)}
        plus=[f'+image_hex={guest_dir/"guest.hex"}',f'+image_words={guest["image_words"]}',
              f'+image_bytes={guest["image_bytes"]}']
        for flag,symbol in [('mmio','fault_mmio'),('read','fault_axi_read'),('write','fault_axi_write'),
                            ('ecall','fault_ecall'),('success','success_break')]:
            plus.append(f'+pc_{flag}={guest["symbols"][symbol]:x}')
        cases=[('same-50mhz','single',10,10,0),('cpu-fast-100mhz','independent',5,10,3000),
               ('cpu-slow-33mhz','independent',15,10,7000)]
        for name,mode,cpu,fabric,phase in cases:
            command=[tools['vvp'],'-i',str(binaries[mode]),*plus,f'+cpu_half={cpu}',f'+fabric_half={fabric}',
                     f'+phase_ps={phase}',f'+maxcycles={args.maxcycles}']
            if mode=='single': command+=['+single_mode']
            report['commands'].append(command)
            result=run(command,output/(name+'.log'),args.timeout)
            report['resources'].append(dict(label=name,**result))
            log=(output/(name+'.log')).read_text()
            if result['returncode'] or result['timed_out'] or result['disk_floor_breached'] or PASS not in log:
                raise RuntimeError(name+' failed: '+log[-3000:])
            line=next((line for line in log.splitlines() if line.startswith('I1_BOOT_METRICS ')),None)
            if not line: raise RuntimeError('missing metrics: '+name)
            metrics={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}
            cdc_line=next((line for line in log.splitlines() if line.startswith('I1_BOOT_CDC ')),None)
            if mode=='independent' and not cdc_line: raise RuntimeError('missing actual CDC channel coverage')
            cdc_counts={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',cdc_line or '')}
            report['positive_cases'][name]={'cdc_handshakes':cdc_counts,'mode':mode,'cpu_half_ns':cpu,'fabric_half_ns':fabric,
                                           'phase_ps':phase,'metrics':metrics,'resources':result}
            (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
            print(name+' PASS '+line,flush=True)
        # The model retains (rather than destroys) the first AR owner and never
        # produces its R response. A real instruction fetch must then not finish.
        maxnegative=report['positive_cases']['cpu-fast-100mhz']['metrics']['boot_cpu_edges']+20000
        command=[tools['vvp'],'-i',str(binaries['independent']),*plus,'+cpu_half=5','+fabric_half=10',
                 '+phase_ps=3000',f'+maxcycles={maxnegative}','+bad_drop_response']
        report['commands'].append(command)
        result=run(command,output/'negative-drop-response.log',args.timeout)
        report['resources'].append(dict(label='negative-drop-response',**result))
        log=(output/'negative-drop-response.log').read_text()
        if result['returncode']==0 or result['timed_out'] or result['disk_floor_breached'] or PASS in log or \
           'I1_BOOT_BOUNDED_COMPLETION_ORACLE' not in log:
            raise RuntimeError('lost first DDR response negative control was not rejected at the cycle bound')
        report['negative_cases']['drop-first-DDR-response']={'status':'REJECTED','maxcycles':maxnegative,'resources':result}
        single=report['positive_cases']['same-50mhz']['metrics']
        report['comparison']={name:{'boot_cpu_edges_vs_single':case['metrics']['boot_cpu_edges']/single['boot_cpu_edges'],
                                  'boot_fabric_edges_vs_single':case['metrics']['boot_fabric_edges']/single['boot_fabric_edges'],
                                  'retired_vs_single':case['metrics']['retired']/single['retired']}
                              for name,case in report['positive_cases'].items()}
        report['performance_note']='Measured boot counts/AXI service only; no CPU throughput or physical frequency claim. No A/B cache or owner reduction was used to pass; test-only geometry is not production qualification.'
        report['status']='PASS_NATIVE_I1_INDEPENDENT_SHORT_BOOT_'+args.profile.upper().replace('-','_')
    except BaseException as error:
        report.update(status='FAILED',failure=str(error))
    finally:
        if frozen!=sources() or rtl_hashes!={mode:{str(p):sha(p) for p in files} for mode,files in rtl.items()} or \
           manifest_hashes!={name:sha(name) for name in manifest_hashes}:
            report.update(status='FAILED',failure='source or RTL drift during acceptance')
        report['free_after_bytes']=shutil.disk_usage(output).free
        report['minimum_free_bytes']=min([report['free_before_bytes'],report['free_after_bytes']]+
                                         [r['minimum_free_bytes'] for r in report['resources']])
        report['elapsed_seconds']=time.monotonic()-started
        report['log_sha256']={p.name:sha(p) for p in output.glob('*.log')}
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status']+' receipt='+str(output/'receipt.json'),flush=True)
    if report['status']=='FAILED': raise SystemExit(report['failure'])


if __name__=='__main__':
    main()
