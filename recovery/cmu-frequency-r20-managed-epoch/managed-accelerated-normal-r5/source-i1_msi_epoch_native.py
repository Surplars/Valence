#!/usr/bin/env python3
"""Real full-I1/real-APLIC/real-IMSIC single-clock held-epoch native test.

Requires existing native Icarus/VVP and RISC-V tools. Emission is explicit, so a
caller can coordinate one Mill slot or reuse hash-bound original fixture RTL.
No generated RTL rewriting, fake IRQ injection, clock gating, CDC, CMU backend,
physical timing qualification, Verilator, Vivado, or tool installation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeEpochMain.scala'
PASS = 'I1_MSI_EPOCH_PASS'
SYMBOLS = ['_start', 'configured', 'loop_previous', 'loop_previous_compare', 'loop_increment', 'loop_store', 'loop_load',
           'loop_compare', 'loop_pending', 'loop_jump', 'guest_fail']
FLOOR = 4 * 1024**3


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool(value):
    resolved = shutil.which(str(value))
    if not resolved or not Path(resolved).is_file():
        raise RuntimeError('existing prepared tool required: ' + str(value))
    return Path(resolved).resolve()


def tool_hashes(paths):
    result = {name: {'path': str(path), 'sha256': sha(path)} for name, path in paths.items()}
    compiler = paths.get('iverilog')
    if compiler and compiler.read_bytes()[:2] == b'#!':
        for line in compiler.read_text().splitlines():
            if line.startswith('exec '):
                words = shlex.split(line)
                if len(words) > 1 and Path(words[1]).is_file():
                    result['iverilog_engine'] = {'path': words[1], 'sha256': sha(words[1])}
                if '-B' in words:
                    directory = Path(words[words.index('-B') + 1])
                    for name in ['ivl', 'ivlpp', 'vvp.tgt', 'vvp.conf']:
                        path = directory / name
                        if path.is_file():
                            result[name] = {'path': str(path), 'sha256': sha(path)}
    return result


def sources(guest_only=False):
    paths = [HERE / 'i1_msi_epoch.S', HERE / 'i1_msi_epoch.ld', Path(__file__).resolve()]
    if not guest_only:
        paths += [HERE / 'i1_msi_epoch_tb.sv', FIXTURE, ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
        paths += sorted((ROOT / 'src/main/scala').rglob('*.scala'))
        paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def run(command, output, name, timeout, record):
    command = list(map(str, command))
    started = time.monotonic()
    minimum_free = shutil.disk_usage(output).free
    if minimum_free < FLOOR:
        raise RuntimeError('4 GiB disk floor before ' + name)
    with (output / (name + '.log')).open('w') as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        killed = timed_out = False
        while child.poll() is None:
            minimum_free = min(minimum_free, shutil.disk_usage(output).free)
            timed_out = time.monotonic() - started > timeout
            if timed_out or minimum_free < FLOOR:
                os.killpg(child.pid, signal.SIGKILL)
                killed = True
                break
            time.sleep(0.05)
        child.wait()
    record['cases'].append(dict(name=name, command=command, returncode=child.returncode,
        elapsed_seconds=time.monotonic()-started, minimum_free_bytes=minimum_free,
        timed_out=timed_out, process_group_killed=killed))
    if killed:
        raise RuntimeError('wall-clock or disk resource bound: ' + name)
    return child.returncode, (output / (name + '.log')).read_text()


def guest(output, prefix, record):
    paths = {name: tool(prefix + name) for name in ['gcc', 'objcopy', 'nm', 'objdump']}
    record['tools'].update(tool_hashes(paths))
    commands = [
        ([paths['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
          '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
          '-T' + str(HERE / 'i1_msi_epoch.ld'), HERE / 'i1_msi_epoch.S', '-o', output / 'guest.elf'], 'guest-build'),
        ([paths['objcopy'], '-O', 'binary', output / 'guest.elf', output / 'guest.bin'], 'guest-binary'),
        ([paths['nm'], '-n', output / 'guest.elf'], 'guest-symbols'),
        ([paths['objdump'], '-d', output / 'guest.elf'], 'guest-disassembly'),
    ]
    for command, name in commands:
        rc, _ = run(command, output, name, 60, record)
        if rc:
            raise RuntimeError('guest build failed: ' + name)
    image = (output / 'guest.bin').read_bytes()
    if len(image) > 256 or len(image) % 4:
        raise RuntimeError('guest must fit unchanged 64-word fixture ROM with whole RV instructions')
    padded = image + bytes(256-len(image))
    (output / 'guest.hex').write_text(''.join(
        f'{int.from_bytes(padded[n:n+4], "little"):08x}\n' for n in range(0, 256, 4)))
    symbols = {name: int(address, 16) for address, _, name in re.findall(
        r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', (output / 'guest-symbols.log').read_text(), re.M)}
    if any(name not in symbols for name in SYMBOLS) or symbols['_start'] != 0x80000000:
        raise RuntimeError('missing or misplaced architectural scoreboard PC symbols')
    (output / 'guest_symbols.svh').write_text(''.join(
        f"localparam [63:0] PC_{name.upper()} = 64'h{symbols[name]:016x};\n" for name in SYMBOLS))
    record['guest'] = dict(image_bytes=len(image), rom_words=64,
        symbols={name: symbols[name] for name in SYMBOLS},
        artifacts={name: sha(output / name) for name in
                   ['guest.elf', 'guest.bin', 'guest.hex', 'guest_symbols.svh']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--cross-prefix', default='riscv64-unknown-elf-')
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--emit', action='store_true', help='use only during an explicitly allocated Mill slot')
    mode.add_argument('--rtl-dir', type=Path, help='reuse original emitted fixture RTL without invoking Mill')
    parser.add_argument('--emission-receipt', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh output directory with an existing parent is required')
    if not args.prepare_only and not (args.emit or (args.rtl_dir and args.emission_receipt)):
        parser.error('use --emit or both --rtl-dir and --emission-receipt')
    if not os.environ.get('VALENCE_CLOUD_ENV'):
        parser.error('source scripts/cloud/env.sh before running this test')
    out.mkdir()
    frozen = sources(args.prepare_only)
    record = dict(status='RUNNING', source_sha256=frozen, tools={}, cases=[],
        scope='real unchanged full I1/private caches/Home/internal RAM; real CPU-configured M-APLIC and IMSIC CSR retirement; single clock; no CDC, CMU backend, clock gate, PLL, DDR or physical qualification',
        ledger_boundary='MSI delivered=request.fire at CPU IMSIC boundary; replied=response.fire returned to APLIC; upstream admission queue is checked by separate component tests')
    try:
        guest(out, args.cross_prefix, record)
        if args.prepare_only:
            if sources(True) != frozen:
                raise RuntimeError('guest source drift during preparation')
            record['status'] = 'PASS_I1_MSI_EPOCH_GUEST_ONLY'
            return
        paths = {'iverilog': tool(args.iverilog), 'vvp': tool(args.vvp)}
        record['tools'].update(tool_hashes(paths))
        if args.emit:
            paths['mill'] = tool('mill')
            record['tools'].update(tool_hashes({'mill': paths['mill']}))
            rtl = out / 'rtl'
            rc, _ = run([paths['mill'], '--no-server', 'IonSoC.test.runMain',
                         'platform.CommonI1RuntimeEpochNativeMain', rtl], out, 'emit', 300, record)
            if rc:
                raise RuntimeError('real full-I1 fixture emission failed')
        else:
            rtl = args.rtl_dir.resolve()
        files = sorted(rtl.glob('*.sv'))
        if not files:
            raise RuntimeError('no original emitted SystemVerilog files')
        text = '\n'.join(path.read_text() for path in files)
        if 'module CommonI1RuntimeEpochFixture' not in text or '$fatal' not in text:
            raise RuntimeError('real fixture and inline production assertions are required')
        required_ports = ['io_sources', 'io_holdMsiReply', 'io_msiReplyBlocked', 'io_msiAccepted11', 'io_msiReplied']
        if any(name not in text for name in required_ports):
            raise RuntimeError('emitted fixture lacks required real MSI observation/backpressure ports')
        rtl_hashes = {path.name: sha(path) for path in files}
        record['rtl_sha256'] = rtl_hashes
        if not args.emit:
            receipt = json.loads(args.emission_receipt.read_text())
            if receipt.get('status') not in ('PASS', 'PASS_EMIT_ONLY'):
                raise RuntimeError('passing source-bound emission receipt is required')
            binding = receipt.get('source_sha256', {})
            required = {name: digest for name, digest in frozen.items()
                        if name.startswith('src/main/scala/') or name == str(FIXTURE.relative_to(ROOT))}
            if any(binding.get(name) != digest for name, digest in required.items()):
                raise RuntimeError('emission receipt is not bound to current production and fixture sources')
            if receipt.get('rtl_sha256') != rtl_hashes:
                raise RuntimeError('emitted RTL hash mismatch')
            record['emission_receipt'] = dict(path=str(args.emission_receipt.resolve()), sha256=sha(args.emission_receipt))
        binary = out / 'sim.vvp'
        rc, _ = run([paths['iverilog'], '-g2012', '-I', out, '-s', 'i1_msi_epoch_tb', '-o', binary,
                     *files, HERE / 'i1_msi_epoch_tb.sv'], out, 'compile', 300, record)
        if rc:
            raise RuntimeError('native compile failed')
        record['sim_sha256'] = sha(binary)
        command = [paths['vvp'], binary, '+rom=' + str(out / 'guest.hex')]
        rc, log = run(command, out, 'positive', 900, record)
        if rc or PASS not in log:
            raise RuntimeError('real I1 MSI/epoch positive failed')
        record['ledgers'] = [line for line in log.splitlines() if line.startswith('I1_MSI_EPOCH_')]
        for negative, marker in [('wrong-data', 'independent load data oracle'),
                                 ('wrong-irq', 'independent IMSIC pending oracle')]:
            rc, log = run(command + ['+' + negative], out, negative, 300, record)
            if not rc or marker not in log or PASS in log:
                raise RuntimeError('deliberately wrong independent monitor was not rejected: ' + negative)
        if frozen != sources():
            raise RuntimeError('source drift during native run')
        if rtl_hashes != {path.name: sha(path) for path in files}:
            raise RuntimeError('RTL drift during native run')
        for name, info in record['tools'].items():
            if sha(info['path']) != info['sha256']:
                raise RuntimeError('tool drift during native run: ' + name)
        for name, digest in record['guest']['artifacts'].items():
            if sha(out / name) != digest:
                raise RuntimeError('guest artifact drift during native run: ' + name)
        record['status'] = 'PASS'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['logs_sha256'] = {path.name: sha(path) for path in out.glob('*.log')}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        print(record['status'] + ' receipt=' + str(out / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
