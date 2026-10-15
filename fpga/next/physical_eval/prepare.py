"""Freeze the exact native R3 export and explicitly selected timing ROM.

Run in the Unix source environment with explicit input arguments.
Never emits RTL or invokes Vivado.
"""
import hashlib
import importlib.util
import json
if not __debug__:
    raise SystemExit('Safety checks require Python without -O')

from pathlib import Path
import re
import shutil
import subprocess
import sys

import argparse
from input_contract import relative_input, tcl_config, validate_native, positive_threads

def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','run-root','native-root','ip-root','ip-manifest','rom-root'):
        parser.add_argument('--'+name,required=True,type=Path)
    for name in ('commit','rom-sha256','padded-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--threads',type=positive_threads,default=4,
                        help='Positive integer; default 4. Installed Vivado validates its supported range.')
    parser.add_argument('--part',default='xczu15eg-ffvb1156-2-i',choices=['xczu15eg-ffvb1156-2-i'])
    parser.add_argument('--python-mode',choices=['native','wsl'],required=True)
    parser.add_argument('--python-command',nargs='+',required=True)
    parser.add_argument('--wsl-command',nargs='+',default=['wsl.exe'])
    parser.add_argument('--wsl-distribution',default='')
    args=parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}',args.commit):parser.error('Full commit SHA required')
    for name in ('rom_sha256','padded_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}',getattr(args,name)):parser.error('Full ROM hashes required')
    if args.python_mode=='wsl' and not args.wsl_distribution:parser.error('Explicit WSL distribution required')
    return args

args=arguments()
source=args.source_root.resolve();run=args.run_root.resolve()
old=args.ip_root.resolve();rom=args.rom_root.resolve()
native=args.native_root.resolve();commit=args.commit
assert source != run and not run.exists(), 'Run root must be new; prior evidence is immutable'
assert source not in run.parents and run not in source.parents, 'Run root must be outside source checkout'
assert subprocess.check_output(['git','-C',str(source),'diff','HEAD','--name-only'],text=True)==''


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p, value):
    p.write_text(json.dumps(value, indent=2) + '\n')


def load(name):
    spec = importlib.util.spec_from_file_location(name, source/'fpga/next'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == commit
recipe = json.loads((source/'fpga/next/three-proof-row-native-recipe.json').read_text(encoding='utf-8'))
for name, info in recipe['reference_files'].items():
    p = source/'fpga/next/three-proof-row-native-reference'/name
    assert sha(p) == info['sha256'] and p.stat().st_size == info['bytes'], name
entry = json.loads((native/'native-entry.json').read_text(encoding='utf-8'))
validate_native(native,source/'fpga/next/three-proof-row-native-reference',recipe)
assert entry['coreFields'] == 178 and entry['profileFields'] == 95
assert entry['proofRows'] == 3 and entry['earlyCredits'] == 2
assert entry['bscanChain'] == 2 and entry['ramLoaderEnabled'] and entry['nativeMacEnabled']
assert entry['bscanEnabled'] and entry['rawHandoffEnabled']
assert not entry['standaloneTapEnabled']
files = sorted(native.glob('*.sv'))
assert len(files) == 292, len(files)
assert 0 < (rom/'bootrom.bin').stat().st_size <= 131072
assert sha(rom/'bootrom.bin')==args.rom_sha256
raw_rom=(rom/'bootrom.bin').read_bytes()
assert hashlib.sha256(raw_rom+bytes(131072-len(raw_rom))).hexdigest()==args.padded_sha256
inventory=json.loads(args.ip_manifest.read_text(encoding='utf-8'))
for name,info in inventory.items():
    if name.startswith(('ip-build/','mig/')) or name in ('board/board_ddr.xdc','board/pl_ddr4_pins.xdc'):
        path=relative_input(old,name)
        assert sha(path)==info['sha256'],name
run.mkdir(parents=True)
(run/'evidence').mkdir()
shutil.copytree(native, run/'native')
out = run/'export'
out.mkdir()
(out/'rtl').mkdir()
(out/'board').mkdir()
for p in native.iterdir():
    if p.is_file():
        shutil.copy2(p, out/'rtl'/p.name)
export = load('export')
wrapper_source = source/'fpga/next/soc_top_fpga_next_ddr.sv'
wrapper = export.bscan_board_wrapper(wrapper_source.read_text(encoding='utf-8'))
connections = export.check_wrapper_ports(wrapper, (native/'FpgaNextSocTop.sv').read_text(encoding='utf-8'))
assert connections == 76
(out/'board/soc_top_fpga_next_ddr.sv').write_text(wrapper)
listed = [x.strip() for x in (native/'filelist.f').read_text(encoding='utf-8').splitlines() if x.strip() and not x.startswith('#')]
resources = ['ValenceJtagDebugPort.sv', 'ValenceBscanDebugPort.sv', 'ValenceMacRawFallingSample.sv']
resource_results = {}
prefix = recipe['resource_emission_contract']['accepted_prefix_utf8'].encode()
for name in resources:
    matches = list((source/'src/main/resources').rglob(name))
    assert len(matches) == 1, name
    original = matches[0].read_bytes()
    emitted = (native/name).read_bytes()
    assert original.endswith(b'\n') and emitted == prefix + original[:-1], name
    resource_results[name] = dict(source=str(matches[0].relative_to(source)), source_sha256=sha(matches[0]), emitted_sha256=sha(native/name), transformation='exact38byte_header_remove_one_final_LF')
    if name not in listed:
        listed.append(name)
assert len(listed) == len(set(listed)) == 292
assert set(listed) == {p.name for p in files}
(out/'synthesis-files.f').write_text(''.join('rtl/'+name+'\n' for name in listed))
media = load('media_integration')
bscan = load('bscan_integration')
t1 = load('board_t1')
bscan.stage(source, out, 2)
integration = media.stage(source, out)
mode = t1.stage(source, out, True, True)
receipt = dict(status='PASS_RTL_EXPORT_ONLY', exact_commit=commit,
    native_entry=entry, native_emitter='ooo.ThreeProofRowNativeMain',
    board_wrapper=dict(path='board/soc_top_fpga_next_ddr.sv', sha256=sha(out/'board/soc_top_fpga_next_ddr.sv'),
        source='fpga/next/soc_top_fpga_next_ddr.sv', source_sha256=sha(wrapper_source), media='experimental-trispeed',
        named_ports_checked=connections, physical_qualification=False),
    tri_speed_native_integration=integration, native_mac_mode=mode,
    source_sha256={name:sha(source/name) for name in set(t1.INPUTS+t1.PRODUCTION+media.INPUTS)},
    rtl_sha256={p.relative_to(out).as_posix():sha(p) for p in (out/'rtl').iterdir() if p.is_file()},
    synthesis_filelist_sha256=sha(out/'synthesis-files.f'))
dump(out/'receipt.json', receipt)
verified=t1.verify(out)
firmware=run/'firmware'
firmware.mkdir()
for name in ['bootrom.bin','bootrom.coe','bootrom.even.hex','bootrom.odd.hex','bootrom-contract.json','bootrom.map']:
    shutil.copy2(rom/name, firmware/name)
raw=(firmware/'bootrom.bin').read_bytes()
assert hashlib.sha256(raw).hexdigest() == args.rom_sha256
expected=raw+bytes(131072-len(raw))
assert hashlib.sha256(expected).hexdigest() == args.padded_sha256
words=[int(x,16) for x in re.split('[,;\\s]+',(firmware/'bootrom.coe').read_text(encoding='utf-8').split('memory_initialization_vector=',1)[1]) if x]
assert b''.join(x.to_bytes(4,'little') for x in words)==expected
inventory=json.loads(args.ip_manifest.read_text(encoding='utf-8'))
copied={}
for name, info in inventory.items():
    if name.startswith(('ip-build/','mig/')) or name in ('board/board_ddr.xdc','board/pl_ddr4_pins.xdc'):
        p=relative_input(old,name)
        assert sha(p)==info['sha256'],name
        dest=run/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p,dest)
        assert sha(dest)==info['sha256']
        copied[name]=dict(sha256=sha(dest),bytes=dest.stat().st_size,source_relative=name)
mif=run/'ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.mif'
assert b''.join(int(x,2).to_bytes(4,'little') for x in mif.read_text(encoding='utf-8').split())==expected
xci=run/'ip-build/board_ip.srcs/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.xci'
xci_config=json.loads(xci.read_text(encoding='utf-8'))['ip_inst']['parameters']['component_parameters']
coe_path=xci_config['Coe_File'][0]['value']
assert (xci.parent/coe_path).resolve()==firmware/'bootrom.coe', 'ROM XCI must bind the staged COE'
dump(run/'evidence/frozen-inputs.json',dict(commit=commit,tree=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD^{tree}'],text=True).strip(),
    recipe_sha256=sha(source/'fpga/next/three-proof-row-native-recipe.json'),
    references=recipe['reference_files'],native_sv_count=292,native_sv_sha256={p.name:sha(p) for p in files},
    requested_threads=args.threads,tool_thread_validation='DEFERRED_UNTIL_EXPLICIT_VIVADO_RUN',
    resource_results=resource_results,mode_verification=verified,
    rom=dict(status='EXPLICIT_SELECTED_TIMING_ROM_NOT_BOOT_QUALIFIED',bin_sha256=sha(firmware/'bootrom.bin'),padded_sha256=hashlib.sha256(expected).hexdigest(),files={p.name:dict(sha256=sha(p),bytes=p.stat().st_size) for p in firmware.iterdir()}),
    historical_ip_xdc=copied))
print('PASS_R3_FROZEN_INPUTS core178 profile95 rows3 credits2 LSU4 SV292 ports76 two_MAC_generics1 USER2 fixed_ROM128KiB')

# Runtime paths are generated only in the external run directory, never committed.
settings=dict(threads=args.threads,part=args.part,python_mode=args.python_mode,
    python_command=args.python_command,wsl_command=args.wsl_command,
    wsl_distribution=args.wsl_distribution,rom_sha256=args.rom_sha256,padded_sha256=args.padded_sha256)
(run/'physical-config.tcl').write_text(tcl_config(settings))
shutil.copytree(Path(__file__).parent,run/'scripts',ignore=shutil.ignore_patterns('__pycache__','test_*'))
print('PREPARED_ONLY: explicit synth/place commands required; threads='+str(args.threads))
