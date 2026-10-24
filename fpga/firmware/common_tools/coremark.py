#!/usr/bin/python3
"""Run the unchanged pinned CoreMark workload; refuse invalid/too-short scores."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys

BINARY = Path('/usr/local/lib/valence-tools/coremark')
EXPECTED = {'seedcrc':'e9f5','crclist':'e714','crcmatrix':'1fd7','crcstate':'8e3a'}

def evaluate(output):
    for field, expected in EXPECTED.items():
        matches = re.findall(r'^(?:\[0\])?' + field + r'\s*:\s*0x([0-9a-fA-F]+)\s*$', output, re.M)
        if len(matches) != 1 or int(matches[0],16) != int(expected,16):
            raise ValueError('CoreMark CRC missing, duplicated or wrong: '+field)
    elapsed = re.findall(r'^Total time \(secs\):\s*([0-9.]+)\s*$', output, re.M)
    rates = re.findall(r'^Iterations/Sec\s*:\s*([0-9.]+)\s*$', output, re.M)
    if len(elapsed) != 1 or len(rates) != 1:
        raise ValueError('CoreMark timing missing or duplicated')
    seconds, rate = float(elapsed[0]), float(rates[0])
    if not math.isfinite(seconds) or seconds <= 0 or not math.isfinite(rate) or rate <= 0:
        raise ValueError('CoreMark timing is invalid')
    if seconds < 10:
        return {'status':'SHORT_CRC_ONLY_NOT_VALID_SCORE','crc_validated':True,
                'elapsed_seconds':seconds, 'iterations_per_second':None}
    if 'Correct operation validated.' not in output or 'ERROR' in output or 'Errors detected' in output:
        raise ValueError('CoreMark reported an error or no final validation')
    return {'status':'WORKLOAD_VALIDATED_CURRENT_EXECUTION_ENVIRONMENT', 'crc_validated':True,
            'elapsed_seconds':seconds, 'iterations_per_second':rate,
            'qualification':'Not an officially submitted score. QEMU results are not SoC performance.'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=0,help='0 auto-calibrates to at least10s; short runs do not yield scores')
    args=parser.parse_args(argv)
    if not 0 <= args.iterations <= 100000000:
        parser.error('iterations0..100000000 required')
    completed=subprocess.run([str(BINARY),'0','0','0x66',str(args.iterations)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(completed.stdout,end='',flush=True)
    if completed.returncode:
        raise RuntimeError('CoreMark process failed: '+str(completed.returncode))
    result=evaluate(completed.stdout)
    print(json.dumps(result,sort_keys=True))
    return 2 if result['iterations_per_second'] is None else 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,RuntimeError,ValueError) as error:
        print('COREMARK_FAILED: '+str(error),file=sys.stderr);raise SystemExit(1)
