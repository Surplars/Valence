#!/usr/bin/env python3
"""Bounded native Icarus short boot of both unchanged common-platform CPU profiles.

This runner never elaborates the DUT, edits emitted RTL, installs tools or invokes
Verilator/Vivado. It requires a centrally emitted full-capacity programmable top.
GSIM is not an independent-edge simulator; its project baseline is unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FLOOR = 4 * 1024**3
PASS = 'COMMON_CPU_BOOT_NATIVE_PASS'
FW_PASS = 'COMMON_BOOT_FIRMWARE_BANNER_PASS'
PRODUCTION_ROM_SHA256 = '9b7b73d044f0c6a457f5ed7c3ae2f332aa3b076d26ddf65bef577fe24278e80d'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def guard(path):
    free = shutil.disk_usage(path).free
    if free < FLOOR:
        raise RuntimeError(f'4 GiB disk floor: {free} bytes available')
    return free


def run(command, log_path, timeout):
    started, minimum = time.monotonic(), guard(log_path.parent)
    timed_out = breached = killed = False
    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with log_path.open('w') as log:
        child = subprocess.Popen(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT,
                                 cwd=ROOT, start_new_session=True, preexec_fn=no_core)
        while True:
            minimum = min(minimum, shutil.disk_usage(log_path.parent).free)
            breached |= minimum < FLOOR
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            timed_out |= time.monotonic() - started > timeout
            if (timed_out or breached) and not killed:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                killed = True
            time.sleep(0.05)
    return dict(returncode=child.returncode, seconds=time.monotonic()-started,
                maxrss_kib=usage.ru_maxrss, minimum_free_bytes=minimum,
                timed_out=timed_out, disk_floor_breached=breached, process_group_killed=killed)


def source_hashes():
    paths = sorted((ROOT/'src/main/scala').rglob('*.scala'))
    paths += sorted((ROOT/'src/test/scala/platform').glob('*.scala'))
    paths += sorted((ROOT/'src/main/resources').rglob('*.sv'))
    paths += [ROOT/'build.mill', HERE/'cpu_boot.S', HERE/'cpu_boot.ld',
              HERE/'cpu_boot_tb.sv', Path(__file__).resolve()]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def write_rom(image, output):
    if len(image) > 131072:
        raise RuntimeError('ROM image exceeds fixed 128 KiB aperture')
    image = image + bytes(131072-len(image))
    words = [f'{int.from_bytes(image[n:n+4], "little"):08x}\n' for n in range(0,131072,4)]
    output.write_text(''.join(words))
    return {'words': 32768, 'bytes': 131072, 'sha256': sha(output)}


def build_guest(out, prefix):
    record = dict(status='RUNNING', commands=[], results=[])
    paths = {name: Path(prefix+name).resolve() for name in ['gcc','objcopy','nm']}
    record['tools'] = {name: dict(path=str(path), sha256=sha(path)) for name,path in paths.items()}
    def execute(command, name):
        record['commands'].append(list(map(str, command)))
        result = run(command, out/name, 60)
        record['results'].append(result)
        if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('guest build failed: '+str(out/name))
    try:
        execute([paths['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
            '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
            '-T'+str(HERE/'cpu_boot.ld'), HERE/'cpu_boot.S', '-o', out/'guest.elf'], 'build.log')
        execute([paths['objcopy'], '-O', 'binary', out/'guest.elf', out/'guest.bin'], 'objcopy.log')
        execute([paths['nm'], '-n', out/'guest.elf'], 'symbols.log')
        image = (out/'guest.bin').read_bytes()
        padded = write_rom(image, out/'guest.hex')
        words = (out/'guest.hex').read_text().splitlines(keepends=True)
        (out/'guest.even.hex').write_text(''.join(words[0::2]))
        (out/'guest.odd.hex').write_text(''.join(words[1::2]))
        symbols = {name:int(address,16) for address,_,name in re.findall(
            r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', (out/'symbols.log').read_text(), re.M)}
        required = ['_start','boot_fail','boot_done','fence_first','fence_modified','fence_final']
        if any(name not in symbols for name in required) or symbols['_start'] != 0x80000000:
            raise RuntimeError('test ROM precise PC symbols are missing or have wrong base')
        record.update(status='PASS_COMMON_GUEST_BUILD_ONLY', image_bytes=len(image),
            padded_rom=padded, image_sha256=sha(out/'guest.bin'),
            symbols={name:symbols[name] for name in required},
            source_sha256={str(p.relative_to(ROOT)):sha(p) for p in [HERE/'cpu_boot.S',HERE/'cpu_boot.ld']})
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['artifact_sha256']={p.name:sha(p) for p in out.iterdir() if p.is_file()}
        (out/'guest-receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def hash_tools(iverilog, vvp):
    tools = {name:str(Path(path).resolve()) for name,path in [('iverilog',iverilog),('vvp',vvp)]}
    compiler = Path(iverilog)
    if compiler.read_bytes()[:2] == b'#!':
        for line in compiler.read_text().splitlines():
            if line.startswith('exec '):
                words = shlex.split(line)
                if Path(words[1]).is_file():
                    tools['iverilog_engine'] = words[1]
                if '-B' in words:
                    directory = Path(words[words.index('-B')+1])
                    for name in ['ivl','ivlpp','vvp.tgt','vvp.conf']:
                        if (directory/name).is_file():
                            tools[name] = str(directory/name)
    return {name:dict(path=path,sha256=sha(path)) for name,path in tools.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--cross-prefix')
    parser.add_argument('--guest-dir', type=Path)
    parser.add_argument('--rtl-dir', type=Path)
    parser.add_argument('--profile', choices=['i1','a1'])
    parser.add_argument('--emission-receipt', type=Path)
    parser.add_argument('--conversion-receipt', type=Path,
                        help='required provenance for standards-lowered SV; original emitted files stay unchanged')
    parser.add_argument('--classes-dir', action='append', type=Path)
    parser.add_argument('--firmware-bin', type=Path)
    parser.add_argument('--firmware-only', action='store_true')
    parser.add_argument('--reuse-vvp', type=Path)
    parser.add_argument('--reuse-receipt', type=Path)
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG','iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP','vvp'))
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--maxcycles', type=int, default=1000000)
    parser.add_argument('--negative', choices=['uart','drop-b','drop-read'], action='append', default=[])
    args = parser.parse_args()
    if args.firmware_only and not args.firmware_bin:
        parser.error('--firmware-only requires --firmware-bin')
    out = args.output.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh output directory with existing parent required; never overwrite evidence')
    guard(out.parent)
    out.mkdir()
    if args.prepare_only:
        if not args.cross_prefix:
            parser.error('--prepare-only requires --cross-prefix')
        record=build_guest(out,args.cross_prefix)
        print(record['status']+' receipt='+str(out/'guest-receipt.json'), flush=True)
        return
    if not all([args.guest_dir,args.rtl_dir,args.profile,args.emission_receipt]):
        parser.error('require --guest-dir --rtl-dir --profile --emission-receipt')
    guest_dir = args.guest_dir.resolve()
    guest = json.loads((guest_dir/'guest-receipt.json').read_text())
    if guest['status']!='PASS_COMMON_GUEST_BUILD_ONLY':
        parser.error('passing common guest build receipt required')
    for name,digest in guest['artifact_sha256'].items():
        if sha(guest_dir/name)!=digest:
            parser.error('guest artifact hash mismatch: '+name)
    for name,digest in guest['source_sha256'].items():
        if sha(ROOT/name)!=digest:
            parser.error('guest source hash mismatch: '+name)
    toolpaths = {name:shutil.which(value) for name,value in [('iverilog',args.iverilog),('vvp',args.vvp)]}
    if not all(toolpaths.values()):
        parser.error('existing native Icarus/VVP tools required; installation/fallback forbidden')
    files = sorted(args.rtl_dir.resolve().glob('*.sv'))
    if not files or not any('module CommonMachinePlatform' in p.read_text() for p in files):
        parser.error('missing common-platform top RTL')
    text = '\n'.join(p.read_text() for p in files)
    if 'automatic logic' in text or re.search(r'^\s*bind\s', text,re.M):
        parser.error('unsupported Icarus export; use standard firtool lowering, never rewrite RTL')
    if '$fatal' not in text:
        parser.error('inline production assertions required')
    manifest = json.loads(args.emission_receipt.read_text())
    # The emitter owns detailed capacity/source/class checks; preserve its full receipt.
    if manifest.get('cpu') != args.profile:
        parser.error('emission CPU profile mismatch')
    required = {'top':'CommonMachinePlatform','programmableRom':True,'hardwareClocks':True,
        'romBytes':131072,'instructionCacheBytes':32768,'dataCacheBytes':32768,
        'ddrSlots':4,'ddrWriteSlots':2,'independentCpuFabricClocks':True,
        'cacheWays':2,'homeLines':1024,'homeWays':4,'homeAcquireEntries':2,'homeWritebackEntries':2,
        'heldFifo':'HeldResponseCdcDataFifo','fifoDepth':16,'fabricClockHz':250000000,
        'uartHz':50000000,'uartBaud':460800,'triSpeedEthernet':True,'triSpeedTxFrameSlots':2}
    for key,value in required.items():
        if manifest.get(key) != value:
            parser.error(f'emission manifest mismatch: {key}: {manifest.get(key)!r} != {value!r}')
    for section in ['sources','compiledClasspath','artifacts']:
        if not manifest.get(section):
            parser.error('missing emission hash binding: '+section)
        for path,digest in manifest[section].items():
            if sha(path)!=digest:
                parser.error('emission hash mismatch: '+path)
    original_rtl = {path:digest for path,digest in manifest['artifacts'].items() if path.endswith('.sv')}
    actual_rtl = {str(p):sha(p) for p in files}
    conversion = None
    if actual_rtl != original_rtl:
        if not args.conversion_receipt:
            parser.error('non-original RTL requires a bound standards-conversion receipt')
        conversion = json.loads(args.conversion_receipt.read_text())
        if (conversion.get('status') != 'PASS_SV2V_LOWERING_ONLY' or
                conversion.get('emission_sha256') != sha(args.emission_receipt) or
                conversion.get('input_sha256') != original_rtl or
                conversion.get('output_sha256') != actual_rtl or
                '--exclude=SeverityTask' not in conversion.get('command', [])):
            parser.error('standards conversion is not bound to this exact emission and compiled RTL')
        converter = conversion['tool']
        if sha(converter['path']) != converter['sha256']:
            parser.error('standards conversion tool changed')
        original_text = '\n'.join(Path(path).read_text() for path in original_rtl)
        for task in ['$error', '$fatal']:
            if not original_text.count(task) or original_text.count(task) != text.count(task):
                parser.error('standards conversion altered production assertion severity tasks: '+task)
    classes = manifest['compiledClasspath']
    if args.profile=='i1' and manifest.get('tlbEntries')!=16:
        parser.error('full I1 16-entry TLB is required')
    if args.profile=='a1' and manifest.get('issueWidth')!=2:
        parser.error('public Selected A1 issue width 2 is required')
    frozen=source_hashes()
    record=dict(status='RUNNING', profile=args.profile, source_sha256=frozen, classes_sha256=classes,
        rtl_sha256=actual_rtl, emission_receipt=manifest,
        conversion_receipt=conversion,
        conversion_receipt_sha256=sha(args.conversion_receipt) if conversion else None,
        emission_receipt_path=str(args.emission_receipt.resolve()), emission_receipt_sha256=sha(args.emission_receipt),
        tools=hash_tools(toolpaths['iverilog'],toolpaths['vvp']),
        guest_receipt=str(guest_dir/'guest-receipt.json'), guest_receipt_sha256=sha(guest_dir/'guest-receipt.json'),
        commands=[],results=[],checks={},
        scope='full-capacity common platform, actual independent CPU/fabric/raw clocks, ROM program port, managed UART, AXI DDR, timer, APLIC MSI, dirty FENCE.I refetch',
        native_exception='existing pinned GSIM step() has no independent-edge support; project GSIM baseline unchanged',
        preserved={'rom_bytes':131072,'icache_bytes':32768,'dcache_bytes':32768,'ddr_slots':4,'ddr_write_slots':2,
            'axi_id_bits':4,'i1_tlb_entries':16,'a1_issue_width':2,'a1_read_mshrs':2,'a1_writebacks':2},
        clocks={'cpu_half_ps':1667 if args.profile=='i1' else 5000,'fabric_half_ps':2000,
            'aon_half_ps':10000,'uart_half_ps':10000,'tx_half_ps':4000,'rx_half_ps':4000,'phase_ps':731},
        axi_host_model={'read_owners':16,'aw_owners':16,'w_beats':128,'b_owners':16,
            'independent_aw_w':True,'delayed_b_completion':True,'out_of_order_read_selection':True,
            'ram_windows':[['0x00000000','0x0003ffff'],['0x7fdf8000','0x7fdfffff']]},
        cold_initialization='full ROM port programming under asserted common reset with only fabric clock; all clocks start before reset release and remain continuously running thereafter',
        vendor_primitive_model='BUFGCE digital CE capture on falling edge; unchanged production synchronizer remains',
        physical_qualified=False, board_equivalent=False,
        unsupported=['metastability','clock-gating qualification','routed timing','FPGA board boot','full Linux',
            'full ISA qualification','full TUI interaction','Ethernet packets','JTAG operations','hot reset'])
    def save():
        (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    def execute(command,name,expected=None,negative=None):
        record['commands'].append(list(map(str,command))); save()
        result=run(command,out/name,args.timeout)
        result['log']=name; record['results'].append(result); save()
        content=(out/name).read_text()
        if result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('resource bound stopped '+name)
        if negative:
            if not result['returncode'] or negative not in content or PASS in content or FW_PASS in content:
                raise RuntimeError('negative control not independently rejected: '+name)
            record['checks'][name]='PASS_NEGATIVE_REJECTED'
        elif result['returncode'] or (expected and expected not in content):
            raise RuntimeError('native command failed or missing completion: '+name)
        else:
            record['checks'][name]='PASS'
        save()
    try:
        save()
        for fixture in ['cpu_boot.S','cpu_boot.ld','cpu_boot_tb.sv','cpu_boot_native.py']:
            shutil.copy2(HERE/fixture,out/fixture)
        binary=out/'run.vvp'
        if args.reuse_vvp:
            binary=args.reuse_vvp.resolve()
            if not args.reuse_receipt:
                raise RuntimeError('reuse requires original compile receipt')
            prior=json.loads(args.reuse_receipt.read_text())
            if prior['rtl_sha256']!=record['rtl_sha256'] or prior['artifact_sha256'].get('run.vvp')!=sha(binary):
                raise RuntimeError('reused native binary does not match original RTL/compile receipt')
            if prior['artifact_sha256'].get('cpu_boot_tb.sv')!=sha(HERE/'cpu_boot_tb.sv'):
                raise RuntimeError('reused native binary testbench changed')
            record['reused_vvp']={'path':str(binary),'sha256':sha(binary)}
        else:
            execute([toolpaths['iverilog'],'-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-s','cpu_boot_tb','-o',binary,*files,HERE/'cpu_boot_tb.sv'],'compile.log')
        clocks=['+cpu_half='+str(record['clocks']['cpu_half_ps']),'+phase_ps=731','+maxcycles='+str(args.maxcycles)]
        sym=guest['symbols']
        guest_args=['+rom_hex='+str(guest_dir/'guest.hex'),*clocks,*[
            '+pc_'+arg+'='+format(sym[name],'x') for arg,name in [('fail','boot_fail'),('done','boot_done'),
            ('fence_first','fence_first'),('fence_modified','fence_modified'),('fence_final','fence_final')]]]
        if not args.firmware_only:
            execute([toolpaths['vvp'],'-i',binary,*guest_args],'guest.log',expected=PASS)
        if args.firmware_bin:
            firmware=args.firmware_bin.resolve()
            if sha(firmware)!=PRODUCTION_ROM_SHA256:
                raise RuntimeError('production TUI ROM hash mismatch')
            record['production_firmware']={'path':str(firmware),'sha256':sha(firmware),'bytes':firmware.stat().st_size,
                'padded_rom':write_rom(firmware.read_bytes(),out/'firmware.hex')}
            execute([toolpaths['vvp'],'-i',binary,'+firmware_mode','+rom_hex='+str(out/'firmware.hex'),*clocks],
                'firmware.log',expected=FW_PASS)
        for negative in args.negative:
            option,oracle={'uart':('+bad_uart','COMMON_BOOT_UART_BANNER_ORACLE'),
                'drop-b':('+bad_drop_b','COMMON_BOOT_BOUNDED_COMPLETION_ORACLE'),
                'drop-read':('+bad_drop_response','COMMON_BOOT_BOUNDED_COMPLETION_ORACLE')}[negative]
            execute([toolpaths['vvp'],'-i',binary,*guest_args,option],negative+'.log',negative=oracle)
        if frozen!=source_hashes():
            raise RuntimeError('source drift during native run')
        if any(sha(path)!=digest for path,digest in classes.items()):
            raise RuntimeError('compiled classes changed during native run')
        record['status']=('PASS_COMMON_CPU_NATIVE_FIRMWARE_BANNER' if args.firmware_only else
                          'PASS_COMMON_CPU_NATIVE_SHORT_BOOT_AND_FIRMWARE_BANNER' if args.firmware_bin else
                          'PASS_COMMON_CPU_NATIVE_SHORT_BOOT')
    except BaseException as error:
        record.update(status='FAIL',error=repr(error))
        raise
    finally:
        record['artifact_sha256']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        save()
        print(record['status']+' receipt='+str(out/'receipt.json'),flush=True)


if __name__=='__main__':
    main()
