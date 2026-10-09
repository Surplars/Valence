#!/usr/bin/env python3
"""Small integration-contract tests. No linking, compression, or model execution."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import compare as c
from prepare import require,sha
repo=Path(__file__).resolve().parents[4]
relative='simulator/gsim/elf_debug_compression.py'
helper_path=repo/relative
negatives=0

def reject(fn,anchor=None):
    global negatives
    try:fn()
    except (RuntimeError,ValueError,KeyError,FileNotFoundError) as error:
        if anchor:require(anchor in str(error),'wrong compression rejection: '+str(error))
        negatives+=1;return
    raise RuntimeError('compression integration negative passed')

with tempfile.TemporaryDirectory(prefix='monitor-compression-contract-') as temporary:
    root=Path(temporary);before=root/'replay.uncompressed';after=root/'replay';receipt=root/'debug-compression.json'
    before.write_bytes(b'synthetic before, not ELF');after.write_bytes(b'synthetic after, not ELF')
    log=root/'debug-compression.log';log.write_text('MONITOR_DEBUG_COMPRESSION_PASS\n')
    products={'launcher_contract.h','replay','positive-traffic.tsv','positive-hot-stage.tsv','positive-frontend.tsv'}|{'negative-'+n+'-traffic.tsv' for n in c.NEGATIVES}
    base=dict(compress_debug=False,products=dict.fromkeys(products,'synthetic'),steps=[dict(name=n,exit=1 if n.startswith('negative-') else 0) for n in ['link','positive']+['negative-'+n for n in c.NEGATIVES]],external_fixture_inputs=c.driver.external_sources(repo,False),debug_compression_tools={})
    c.inventory(base);c.compression_evidence(base,root,repo)
    x=copy.deepcopy(base);x['compress_debug']=True;x['products'].update({'replay.uncompressed':sha(before),'replay':sha(after),'debug-compression.json':'synthetic'})
    x['steps'].insert(1,dict(name='debug-compression',exit=0,command=c.driver.compression_command(repo,root),log='debug-compression.log'))
    x['external_fixture_inputs']=c.driver.external_sources(repo,True);x['debug_compression_tools']={'synthetic_tools':'contract-stub-only'}
    c.inventory(x)
    for name in ('replay.uncompressed','debug-compression.json'):
        bad=copy.deepcopy(x);bad['products'].pop(name);reject(lambda bad=bad:c.inventory(bad),'product set')
    bad=copy.deepcopy(x);bad['steps'].pop(1);reject(lambda:c.inventory(bad),'step set')
    bad=copy.deepcopy(x);bad['compress_debug']=False;reject(lambda:c.inventory(bad),'product set')
    bad=copy.deepcopy(x);bad['compress_debug']='true';reject(lambda:c.inventory(bad),'must be boolean')
    proof=dict(schema='valence-new-debug-compression-v1',status='PASS_DEBUG_COMPRESSION_ONLY',tools=x['debug_compression_tools'],tool_sha256=sha(helper_path),before_sha256=sha(before),after_sha256=sha(after))
    receipt.write_text(json.dumps(proof))
    calls=[]
    class ContractStub:
        def validate_compression_receipt(self,a,b,p):
            require((a,b,p)==(before,after,receipt),'validator received wrong new output paths');calls.append((a,b,p));return json.loads(p.read_text())
    with patch.object(c.driver,'load_helper',return_value=ContractStub()):
        c.compression_evidence(x,root,repo);require(len(calls)==1,'compression skipped proof validator')
        for field,reason in [('schema','schema/status'),('status','schema/status'),('tools','tool/helper'),('tool_sha256','tool/helper'),('before_sha256','product mismatch'),('after_sha256','product mismatch')]:
            changed=copy.deepcopy(proof);changed[field]='changed';receipt.write_text(json.dumps(changed));reject(lambda:c.compression_evidence(x,root,repo),reason)
        receipt.write_text('{malformed');reject(lambda:c.compression_evidence(x,root,repo))
        receipt.unlink();reject(lambda:c.compression_evidence(x,root,repo));receipt.write_text(json.dumps(proof))
        bad=copy.deepcopy(x);bad['steps'][1]['command'][-1]='wrong-proof.json';reject(lambda:c.compression_evidence(bad,root,repo),'step command')
        bad=copy.deepcopy(x);bad['external_fixture_inputs'][relative]='changed';reject(lambda:c.compression_evidence(bad,root,repo),'source binding')
        log.write_text('missing anchor\n');reject(lambda:c.compression_evidence(x,root,repo),'anchor');log.write_text('MONITOR_DEBUG_COMPRESSION_PASS\n')
    # The real shared validator must run, rather than merely trust stub proof JSON.
    reject(lambda:c.compression_evidence(x,root,repo),'requires ELF64')
print(f'PASS_MONITOR_COMPRESSION_INTEGRATION_HOST negatives={negatives} default_inventory_preserved=1 validator_invoked=1 no_real_compression=1')
