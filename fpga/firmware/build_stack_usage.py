#!/usr/bin/env python3
"""Build the qualified complete slice2 ROM with stack metadata; no target execution."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--prefix', default='riscv64-unknown-elf-')
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefix = out / 'wrappers/riscv64-unknown-elf-'
    prefix.parent.mkdir(exist_ok=True)
    for tool in ('gcc', 'objcopy', 'size'):
        executable = shutil.which(args.prefix + tool)
        if not executable:
            raise RuntimeError('missing tool: ' + args.prefix + tool)
        extra = ['-fstack-usage', '-fdump-ipa-cgraph'] if tool == 'gcc' else []
        wrapper = Path(str(prefix) + tool)
        wrapper.write_text('#!/usr/bin/env python3\nimport os,sys,json\ncmd=' +
                           repr([executable, *extra]) + '+sys.argv[1:]\nwith open(' +
                           repr(str(out / 'commands.jsonl')) +
                           ',"a") as f:f.write(json.dumps(cmd)+"\\n")\nos.execv(cmd[0],cmd)\n')
        wrapper.chmod(0o755)
    command = ['python3', str(SOURCE / 'build.py'), '--out', str(out / 'full'),
               '--prefix', str(prefix), '--crc-mode', 'slice2', '--boot-menu', '--netboot',
               '--netboot-posted-rx', '--jtag-download', '--ddr', '--ddr-bytes', '0x80000000',
               '--cpu-hz', '100000000', '--uart-reference-hz', '7372800', '--uart-baud', '460800']
    with (out / 'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (out / 'full/disasm.txt').open('w') as log:
        subprocess.run([args.prefix + 'objdump', '-d', str(out / 'full/bootrom.elf')],
                       stdout=log, check=True)
    subprocess.run(['python3', str(SOURCE / 'audit_stack_usage.py'), '--out', str(out)], check=True)

if __name__ == '__main__':
    main()
