#!/usr/bin/env python3
"""Prove emitted actual Chisel tag helper over all 64-bit bases / 2-bit counts.

This is an arithmetic + conditional state-transition projection, not the Ledger.
Run only after the parent source freeze/compile receipt; no hardware simulator.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FIRTOOL = ROOT / 'build/pmp-cloud-tools-20261025-r1/firtool-1.135.0/firtool'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


ORACLE = r'''
function [64:0] ripple;
input [63:0] base; input [1:0] count;
reg [64:0] value; reg carry, oldbit; integer step, bitno;
begin
  value = {1'b0, base};
  for (step=0; step<3; step=step+1) if (step<count) begin
    carry=1;
    for (bitno=0; bitno<65; bitno=bitno+1) begin
      oldbit=value[bitno]; value[bitno]=oldbit ^ carry; carry=oldbit & carry;
    end
  end
  ripple=value;
end
endfunction
'''
MITER = r'''
module miter(input [63:0] base, input [1:0] count, input exhausted,
input resetState, input recovery, output ok);
wire [64:0] advanced, original, lane1;
wire [63:0] lane0, nextTag; wire nextExhausted;
SplitLowTagAdvanceFormal dut(.base(base),.count(count),.exhausted(exhausted),
.resetState(resetState),.recovery(recovery),.advanced(advanced),.original(original),
.lane0(lane0),.lane1(lane1),.nextTag(nextTag),.nextExhausted(nextExhausted));
''' + ORACLE + r'''
wire [64:0] expected=ripple(base,count);
wire update = !recovery && count!=0;
wire [63:0] expectedTag = resetState ? 64'b0 : update ? expected[63:0] : base;
wire expectedExhausted = resetState ? 1'b0 : update ? expected[64] : exhausted;
assign ok = (advanced==expected) && (original==expected) && (lane0==base) &&
(lane1==ripple(base,2'd1)) && (nextTag==expectedTag) && (nextExhausted==expectedExhausted);
endmodule
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--compile-receipt', type=Path, required=True)
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Verification is intentionally delegated to the source-bound receipt helper.
    import sys
    sys.path.insert(0, str(ROOT / 'fpga/common'))
    import scala_compile_receipt
    compiled = scala_compile_receipt.verify_receipt(a.compile_receipt.resolve())
    classpath = os.pathsep.join(compiled["runClasspathEntries"])
    sources = [ROOT / f for f in ('src/main/scala/core/ooo/retire/SplitLowTagAdvance.scala',
        'src/test/scala/ooo/SplitLowTagAdvanceFormal.scala', 'simulator/gsim/split_low_tag_advance_formal.py')]
    before = {str(x.relative_to(ROOT)): sha(x) for x in sources}
    receipt = {'schema': 'valence-actual-tag-helper-formal-v1', 'status': 'RUNNING',
        'source_inputs': before, 'compile_receipt_sha256': sha(a.compile_receipt),
        'scope': 'Actual emitted helper plus conditional-state projection, not actual Ledger proof',
        'domain': 'All base[63:0], count[1:0]=0..3, exhausted, reset, recovery; no assumptions',
        'tools': {str(x): sha(x) for x in [FIRTOOL, Path(shutil.which('yosys'))]}, 'proofs': {}}

    def run(cmd, log):
        with log.open('w') as f:
            r = subprocess.run([str(x) for x in cmd], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
        return r.returncode

    try:
        for mode in ('none', 'carry', 'exhaustion'):
            d = out / mode
            d.mkdir()
            assert run(['java', '-cp', classpath, 'ooo.SplitLowTagAdvanceFormalMain', d, mode],
                d/'elaborate.log') == 0, 'elaboration failed'
            assert run([FIRTOOL, d/'SplitLowTagAdvanceFormal.fir', '--disable-all-randomization',
                '--split-verilog', '-o', d/'rtl'], d/'firtool.log') == 0, 'firtool failed'
            (d/'miter.v').write_text(MITER)
            script = (f'read_verilog -sv {d}/rtl/SplitLowTagAdvanceFormal.sv {d}/miter.v\n'
                'prep -top miter -flatten\nopt\ncheck -assert\n'
                'sat -verify -prove ok 1 -show-inputs\n')
            (d/'proof.ys').write_text(script)
            start = time.monotonic()
            rc = run(['yosys', '-T', '-s', d/'proof.ys'], d/'proof.log')
            log = (d/'proof.log').read_text()
            passed = rc == 0 and 'SUCCESS' in log
            rejected = rc != 0 and 'proof did fail' in log
            assert passed if mode == 'none' else rejected, f'unexpected proof result {mode}'
            receipt['proofs'][mode] = {'status': 'PASS' if passed else 'EXPECTED_COUNTEREXAMPLE',
                'seconds': time.monotonic()-start, 'returncode': rc}
        # Explicit edge witnesses supplement (not replace) the unconstrained SAT theorem.
        cases = []
        for base in (0,1,2,3,4, (1<<62)-1, (1<<63)-1, (1<<64)-4, (1<<64)-3, (1<<64)-2, (1<<64)-1):
            for count in range(4):
                value = base
                for _ in range(count):
                    carry = 1
                    for bit in range(65):
                        old = (value >> bit) & 1
                        value ^= carry << bit
                        carry &= old
                assert value == base + count
                cases.append({'base':str(base),'count':count,'sum65':str(value)})
        (out/'edge-witnesses.json').write_text(json.dumps(cases, indent=2)+'\n')
        assert before == {str(x.relative_to(ROOT)):sha(x) for x in sources}, 'source changed'
        scala_compile_receipt.verify_receipt(a.compile_receipt.resolve(), java_classpath=classpath)
        receipt['status'] = 'PASS_FULL64_ACTUAL_HELPER_AND_CONDITIONAL_PROJECTION'
    except Exception as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        receipt['artifacts'] = {str(x.relative_to(out)):sha(x) for x in sorted(out.rglob('*')) if x.is_file()}
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':receipt['status'],'receipt':str(out/'receipt.json'),'sha256':sha(out/'receipt.json')}))


if __name__ == '__main__':
    main()
