"""Stage versioned combined-bandwidth native candidate, fail closed without inputs.

Does not emit RTL, invoke Vivado, synthesize, place, route, or generate a bitstream.
Legacy prepare.py and its frozen reference remain independent and unchanged.
"""
import argparse
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
from input_contract import positive_threads, tcl_config, relative_input
from combined_contract import (SCHEMA, FLAGS, ROM_FILES, checked_files, info, read, require,
                               sha, source_closure, validate_ip, validate_native, validate_rom, write)

HERE = Path(__file__).resolve().parent


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'run-root', 'native-root', 'ip-root', 'ip-manifest', 'rom-root',
                 'rom-manifest', 'toolchain-manifest'):
        parser.add_argument('--'+name, required=True, type=Path)
    for name in ('commit', 'rom-sha256', 'padded-sha256', 'vivado-version'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--ip-ownership', type=Path, help='Required XCI ownership records for any OOC DCP/EDIF assets')
    parser.add_argument('--threads', type=positive_threads, default=4)
    parser.add_argument('--part', default='xczu15eg-ffvb1156-2-i', choices=['xczu15eg-ffvb1156-2-i'])
    parser.add_argument('--python-mode', choices=['native', 'wsl'], required=True)
    parser.add_argument('--python-command', nargs='+', required=True)
    parser.add_argument('--wsl-command', nargs='+', default=['wsl.exe'])
    parser.add_argument('--wsl-distribution', default='')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.commit):
        parser.error('Full commit SHA required')
    if any(not re.fullmatch('[0-9a-f]{64}', getattr(args, name)) for name in ('rom_sha256', 'padded_sha256')):
        parser.error('Full ROM hashes required')
    if args.python_mode == 'wsl' and not args.wsl_distribution:
        parser.error('Explicit WSL distribution required')
    if not args.vivado_version.strip():
        parser.error('Exact expected Vivado version -short required')
    return args


def main(args):
    source, run, native, rom, old = (getattr(args, x).resolve() for x in
                                    ('source_root', 'run_root', 'native_root', 'rom_root', 'ip_root'))
    require(not run.exists() and run != source and source not in run.parents and run not in source.parents,
            'Require fresh external run root')
    require(HERE == source/'fpga/next/physical_eval', 'Execute the candidate scripts from the selected source checkout')
    closure = source_closure(source)
    require(closure['commit'] == args.commit, 'Wrong source commit')
    toolchain = read(args.toolchain_manifest)
    for name in ('mill', 'firtool', 'java', 'python'):
        require(isinstance(toolchain[name]['version'], str) and toolchain[name]['version'].strip(), 'Missing tool version')
        require(re.fullmatch('[0-9a-f]{64}', toolchain[name]['sha256']) is not None, 'Missing tool hash')
    audited = validate_native(native, closure, toolchain)
    rom_manifest = read(args.rom_manifest)
    padded = validate_rom(rom, rom_manifest, args.rom_sha256, args.padded_sha256)
    ownership = read(args.ip_ownership) if args.ip_ownership else {}
    inventory = validate_ip(old, read(args.ip_manifest), padded, run, ownership)
    # All external inputs are validated before making even the fresh run directory.
    run.mkdir(parents=True)
    (run/'evidence').mkdir()
    shutil.copytree(native, run/'native')
    out = run/'export'
    (out/'rtl').mkdir(parents=True)
    (out/'board').mkdir()
    for name in audited['inventory']['files']:
        dest = out/'rtl'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative_input(native, name), dest)
    def load(name):
        spec = importlib.util.spec_from_file_location('combined_'+name, source/'fpga/next'/f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    export, media, bscan, t1 = (load(x) for x in ('export', 'media_integration', 'bscan_integration', 'board_t1'))
    wrapper_source = source/'fpga/next/soc_top_fpga_next_ddr.sv'
    wrapper = export.bscan_board_wrapper(wrapper_source.read_text())
    connections = export.check_wrapper_ports(wrapper, (native/'FpgaNextSocTop.sv').read_text())
    require(connections == 76, 'Wrong native wrapper ports')
    (out/'board/soc_top_fpga_next_ddr.sv').write_text(wrapper)
    listed = (native/'filelist.f').read_text().splitlines()
    (out/'synthesis-files.f').write_text(''.join('rtl/'+name+'\n' for name in listed if name.strip()))
    # Recheck the exact known resource emission transform, independently of inventory.
    resource_results = {}
    for name in ('ValenceJtagDebugPort.sv', 'ValenceBscanDebugPort.sv', 'ValenceMacRawFallingSample.sv'):
        paths = list((source/'src/main/resources').rglob(name))
        require(len(paths) == 1, 'Missing/ambiguous source resource: '+name)
        original = paths[0].read_bytes()
        # The emitted prefix is tool-version dependent; derive it only from the pinned firtool version.
        match = re.search(r'firtool(?: version)?[- ]([0-9]+\.[0-9]+\.[0-9]+)', toolchain['firtool']['version'])
        require(match is not None, 'Cannot establish exact resource emission compiler version')
        prefix = ('// Generated by CIRCT firtool-'+match[1]+'\n').encode()
        require(original.endswith(b'\n') and (native/name).read_bytes() == prefix+original[:-1],
                'Resource differs from exact source transform: '+name)
        resource_results[name] = dict(source=paths[0].relative_to(source).as_posix(),
                                      source_sha256=sha(paths[0]), emitted_sha256=sha(native/name), prefix=prefix.decode())
    bscan.stage(source, out, 2)
    integration = media.stage(source, out)
    mode = t1.stage(source, out, True, True)
    receipt = dict(status='PASS_RTL_EXPORT_ONLY', candidate_schema=SCHEMA, exact_commit=args.commit,
        native_entry=audited['entry'], native_emitter='ooo.CombinedBandwidthNativeMain',
        board_wrapper=dict(path='board/soc_top_fpga_next_ddr.sv', sha256=sha(out/'board/soc_top_fpga_next_ddr.sv'),
            source='fpga/next/soc_top_fpga_next_ddr.sv', source_sha256=sha(wrapper_source),
            media='experimental-trispeed', named_ports_checked=connections, physical_qualification=False),
        tri_speed_native_integration=integration, native_mac_mode=mode,
        source_sha256={name: sha(source/name) for name in set(t1.INPUTS+t1.PRODUCTION+media.INPUTS)},
        rtl_sha256={p.relative_to(out).as_posix(): sha(p) for p in (out/'rtl').rglob('*') if p.is_file()},
        synthesis_filelist_sha256=sha(out/'synthesis-files.f'))
    write(out/'receipt.json', receipt)
    mode_verified = t1.verify(out)
    (run/'firmware').mkdir()
    for name in ROM_FILES:
        shutil.copy2(rom/name, run/'firmware'/name)
    for name in inventory:
        dest = run/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative_input(old, name), dest)
    validate_rom(run/'firmware', rom_manifest, args.rom_sha256, args.padded_sha256)
    validate_ip(run, inventory, padded, run, ownership)
    settings = dict(threads=args.threads, part=args.part, python_mode=args.python_mode,
        python_command=args.python_command, wsl_command=args.wsl_command,
        wsl_distribution=args.wsl_distribution, rom_sha256=args.rom_sha256, padded_sha256=args.padded_sha256)
    (run/'physical-config.tcl').write_text(tcl_config(settings))
    shutil.copytree(HERE, run/'scripts', ignore=shutil.ignore_patterns('__pycache__', 'test_*'))
    require(source_closure(source) == closure, 'Source changed during staging')
    validate_native(run/'native', closure, toolchain)
    preflight = subprocess.run([sys.executable, '-B', str(run/'scripts/preflight.py'), str(run)],
                              capture_output=True, text=True, check=True)
    (run/'evidence/static-preflight.txt').write_text(preflight.stdout)
    write(run/'evidence/combined-inputs.json', dict(schema=SCHEMA, status='PREPARED_NOT_PHYSICALLY_QUALIFIED',
        featureFlags=FLAGS, sourceClosure=closure, emissionToolchain=toolchain, vivadoVersion=args.vivado_version,
        actualAuditSha256=sha(native/'actual-combined-native.json'), nativeSvCount=sum(
            name.endswith('.sv') for name in audited['inventory']['files']), resourceResults=resource_results,
        modeVerification=mode_verified, romManifest=rom_manifest, ipManifest=inventory, ipOwnership=ownership,
        romSha256=args.rom_sha256, paddedSha256=args.padded_sha256, physicalQualification=False))
    files = {p.relative_to(run).as_posix(): info(p) for p in run.rglob('*') if p.is_file()}
    write(run/'package-seal.json', dict(schema='combined-bandwidth-package-seal-v1', files=files))
    print('PREPARED_COMBINED_ONLY: sealed actual inventory; no synthesis, placement, timing, boot or board qualification')


if __name__ == '__main__':
    main(arguments())
