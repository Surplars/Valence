#!/usr/bin/env python3
"""Link the RPU handoff against the BSP generated from the board XSA."""
from pathlib import Path
import argparse, hashlib, json, os, re, subprocess
p = argparse.ArgumentParser()
p.add_argument('--bsp', type=Path, required=True)
p.add_argument('--rv-image-dir', type=Path, required=True)
p.add_argument('--sdk', type=Path, required=True)
p.add_argument('--compiler', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--ddr-only', action='store_true')
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
bsp, image, sdk, cc, out = (x.resolve() for x in (a.bsp, a.rv_image_dir, a.sdk, a.compiler, a.output))
assert out.is_relative_to(root / 'build')
out.mkdir(parents=True, exist_ok=False)
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
record = {'status': 'RUNNING', 'commands': []}
def run(args, name):
    args = list(map(str, args));record['commands'].append({'argv': args, 'log': name})
    with (out / name).open('w') as log:
        subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, cwd=root, check=True)
try:
    template = sdk / 'scripts/linker_files/lscript_r5.ld.in'
    script = template.read_text()
    replacements = {'STACK_SIZE': '0x4000', 'HEAP_SIZE': '0x2000',
        'CODE': 'rpu_ddr', 'DATA': 'rpu_ddr',
        'MEMORY_SECTION': 'MEMORY { psu_r5_0_atcm_MEM_0 (rwx) : ORIGIN = 0x0, LENGTH = 0x10000\n rpu_ddr (rwx) : ORIGIN = 0x10000000, LENGTH = 0x04000000 }'}
    for key, value in replacements.items(): script = script.replace('@' + key + '@', value)
    assert not re.search(r'@[A-Za-z_0-9]+@', script)
    (out / 'link.ld').write_text(script)
    flags = [cc, '-DSDT', '-DARMR5', '-mcpu=cortex-r5', '-mfloat-abi=hard', '-mfpu=vfpv3-d16',
        '-O2', '-g', '-ffreestanding', '-Wall', '-Wextra', '-Werror', '-std=c11',
        '-I' + str(bsp / 'include'), '-I' + str(image), '-I' + str(root / 'software/ps-rpu')]
    if a.ddr_only: flags.append('-DI1_RPU_DDR_ONLY=1')
    sources = [root / 'software/ps-rpu' / f for f in ['main.c', 'i1_ps_loader.c']]
    for src in sources: run([*flags, '-c', src, '-o', out / (src.stem + '.o')], src.stem + '-compile.log')
    elf = out / ('i1-rpu-ddr-test.elf' if a.ddr_only else 'i1-rpu-handoff.elf')
    run([*flags, '-specs=' + str(bsp / 'Xilinx.spec'), '-T', out / 'link.ld',
        '-Wl,-u,_boot,--build-id=none,-Map=' + str(out / 'i1-rpu-handoff.map'),
        *[out / (src.stem + '.o') for src in sources], '-L' + str(bsp / 'lib'),
        '-Wl,--start-group', '-lxilstandalone', '-lxil', '-lxiltimer', '-lc', '-lgcc',
        '-Wl,--end-group', '-o', elf], 'link.log')
    nm = str(cc).removesuffix('gcc') + 'nm'
    symbols = {parts[2]: int(parts[0], 16) for line in subprocess.check_output([nm, '-n', elf], text=True).splitlines()
               if len(parts := line.split()) == 3 and re.fullmatch('[0-9a-fA-F]+', parts[0])}
    assert symbols['_boot'] < 0x10000
    assert 0x10000000 <= symbols['g_i1_rpu_report'] < 0x14000000
    assert symbols['__undef_stack'] < 0x14000000
    run([str(cc).removesuffix('gcc') + 'readelf', '-h', '-l', elf], 'elf-layout.log')
    record.update(status='PASS_BOARD_XSA_DERIVED_RPU_ELF_LINKED_NOT_BOARD_TESTED',
        ddr_only=a.ddr_only, report_address=hex(symbols['g_i1_rpu_report']), entry=hex(symbols['_boot']),
        sources_sha256={str(f.relative_to(root)): sha(f) for f in [*sources, root / 'software/ps-rpu/i1_boot_protocol.h', root / 'software/ps-rpu/i1_ps_loader.h', Path(__file__)]},
        bsp_sha256={str(f.relative_to(bsp)): sha(f) for f in sorted(bsp.rglob('*')) if f.is_file()},
        linker_template_sha256=sha(template), rv_image_receipt_sha256=sha(image / 'receipt.json'),
        artifact_sha256={f.name: sha(f) for f in out.iterdir() if f.is_file()})
except BaseException as error:
    record.update(status='FAIL', error=repr(error));raise
finally:
    (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
print(record['status'], record.get('report_address'), flush=True)
