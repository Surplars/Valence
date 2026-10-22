#!/usr/bin/env python3
"""Exact reviewed non-functional comparison; never rewrites simulator/DUT files."""
import argparse, hashlib, json
from pathlib import Path

def digest(b): return hashlib.sha256(b).hexdigest()
def compare(reference, current):
    a = {p.name: p.read_bytes() for p in reference.glob('*.sv')}
    b = {p.name: p.read_bytes() for p in current.glob('*.sv')}
    assert a.keys() == b.keys() and len(a) == 248, 'module inventory mismatch'
    changed = sorted(n for n in a if a[n] != b[n])
    assert changed == ['EthernetPacketDma.sv', 'EthernetTxDescriptorQueue.sv'], changed
    substitutions = {
        'EthernetPacketDma.sv': [('_arbiter_io_clients_0_request_valid_T_7', '_arbiter_io_clients_0_request_valid_T_6', 3)] +
            [(f'EthernetPacketDma.scala:{new}\\n', f'EthernetPacketDma.scala:{old}\\n', 1)
             for new, old in zip(range(491, 497), range(444, 450))],
        'EthernetTxDescriptorQueue.sv': [(f'EthernetTxDescriptorQueue.scala:{new}\\n',
            f'EthernetTxDescriptorQueue.scala:{old}\\n', 1) for new, old in [(87,84),(132,124),(133,125),(134,126)]]}
    mutations = {
        'EthernetPacketDma.sv': [
            ('logic', '~reset', 'reset'), ('width', 'wire [8:0]', 'wire [7:0]'),
            ('constant', "9'h4", "9'h3"),
            ('handshake', '(io_memory_request_ready)', '(io_memory_response_valid)')],
        'EthernetTxDescriptorQueue.sv': [
            ('logic', '~reset', 'reset'), ('width', 'wire [64:0]', 'wire [63:0]'),
            ('constant', "65'h7", "65'h6"),
            ('handshake', '& io_engineIdle', '& io_engineDone')]}
    negatives = {}
    for name, changes in substitutions.items():
        def normalize(text):
            for old, new, count in changes:
                assert text.count(old) == count, (name, old, 'unexpected replacement count')
                # Alpha-renaming is injective: the old reference identifier must
                # not already be a separate signal in the current artifact.
                if old.startswith('_arbiter_'):
                    assert new not in text, 'identifier collision'
                text = text.replace(old, new)
            return text.encode()
        text = b[name].decode()
        assert normalize(text) == a[name], (name, 'unreviewed functional/text difference')
        for kind, old, new in mutations[name]:
            assert old in text, (name, kind, 'missing mutation site')
            mutated = text.replace(old, new, 1)
            assert normalize(mutated) != a[name], (name, kind, 'mutation escaped comparison')
            negatives[name + ':' + kind] = dict(status='REJECTED', old=old, new=new)
    return dict(status='PASS_EXACT_REVIEWED_NONFUNCTIONAL_DIFFERENCES_ONLY',
        byte_identical_modules=246, total_modules=248, nonbyte_identical=changed,
        allowed_substitutions=substitutions, negative_controls=negatives,
        claim='Literal byte equality after only listed alpha-renaming and assertion-source-location replacements; not 248/248 byte identity, formal equivalence, or timing equivalence.',
        reference_sha256={n:digest(v) for n,v in a.items()},current_sha256={n:digest(v) for n,v in b.items()})
if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reference',type=Path);p.add_argument('current',type=Path);p.add_argument('receipt',type=Path);args=p.parse_args()
    result=compare(args.reference,args.current);args.receipt.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
