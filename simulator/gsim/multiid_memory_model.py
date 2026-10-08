#!/usr/bin/env python3
"""Small host-side memory-model tests; does not elaborate or simulate RTL."""
import os
import subprocess
from pathlib import Path
from run import BUILD,HERE,ROOT,compiler,run

def main():
    out=BUILD/'multiid-memory-model';out.mkdir(parents=True,exist_ok=True)
    cxx,_=compiler()
    run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
         HERE/'harness/board_ddr_multiid_test.cpp','-o',out/'run'],log=out/'compile.log')
    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
    run([out/'run'],env=env,log=out/'test.log')
    for arg,anchor in (('--duplicate-id','DDR live read ID reused'),('--bad-boundary','DDR alignment / 4 KiB boundary')):
        p=subprocess.run([out/'run',arg],env=env,text=True,capture_output=True,timeout=30)
        (out/(arg[2:]+'.log')).write_text(p.stdout+p.stderr)
        if p.returncode!=1 or anchor not in p.stdout+p.stderr:raise RuntimeError('host model negative failed: '+arg)
    print((out/'test.log').read_text())

if __name__=='__main__':main()
