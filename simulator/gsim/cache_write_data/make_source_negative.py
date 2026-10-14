#!/usr/bin/env python3
"""Copy only the candidate production Scala leaf and mutate one exact W0_data anchor.

Does not compile/run, edit the original source, modify generated RTL, alter the
frozen reference, or inject faults into host oracle/observations. Compile the
returned leaf INSTEAD OF the positive production leaf; emit with paired=0.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEAF = ROOT / 'src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala'
MUTATIONS = {
 'miss-uses-live-request': (
  '        Some(Mux(refill, fillRequest.data, request.data)) else None',
  '        Some(Mux(refill, request.data, request.data)) else None', 'miss-merge'),
 'hit-uses-stale-fill': (
  '        Some(Mux(refill, fillRequest.data, request.data)) else None',
  '        Some(Mux(refill, fillRequest.data, fillRequest.data)) else None', 'all-hit-masks'),
 'refill-ignores-byte-mask': (
  '                    fillRequest.mask(byte)\n                val selectStoreByte',
  '                    true.B\n                val selectStoreByte', 'miss-merge'),
 'posted-uses-refill-bytes': (
  '                    postedInstallData(64 * bank + 8 * byte + 7, 64 * bank + 8 * byte),',
  '                    engine.io.response.bits.data(64 * bank + 8 * byte + 7, 64 * bank + 8 * byte),', 'posted-banks'),
}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind', choices=MUTATIONS)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, default=LEAF)
    a=p.parse_args()
    source=a.source.read_text(); old,new,case=MUTATIONS[a.kind]
    assert source.count(old)==1, 'actual production anchor drift: ' + a.kind
    assert 'val shareStoreWriteData: Boolean = false' in source, 'positive default-off production leaf absent'
    mutated=source.replace(old,new,1)
    assert mutated != source
    a.output.mkdir(parents=True, exist_ok=False)
    target=a.output/'NonBlockingCoherentLineCache.scala'
    target.write_text(mutated)
    sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
    receipt={'kind':a.kind,'original':str(a.source.resolve()),'original_sha256':sha(source),
             'mutated':str(target.resolve()),'mutated_sha256':sha(mutated),'old':old,'new':new,
             'case':case,'emit_args':'<output> 1 1 0 1 1',
             'expected':'independent actual CPU/C byte oracle failure only; RTL/pair assertion is NOT acceptance',
             'compile_policy':'replace positive production leaf with mutated leaf; all dependencies unchanged',
             'status':'SOURCE_PREPARED_NOT_COMPILED_OR_RUN'}
    (a.output/'mutation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
if __name__=='__main__':main()
