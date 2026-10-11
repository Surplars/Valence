#!/usr/bin/env python3
"""Fresh compact/reference adapter and original transport gates.

Uses the existing sequential component runner. Default models are the exact
cycle-paired adapter plus real StoreBuffer/translation transport. A frozen
qualified reference and independent original-owner oracle are required.
"""
import hashlib
import json
from pathlib import Path
import pending_store_proof_integration as runner

REFERENCE = 'src/test/scala/ooo/TranslatedFrozenProofReference.scala'
BINDING = 'simulator/gsim/bound_store_prefetch/frozen-reference-v1.json'
REFERENCE_SHA256 = 'ac91f63c127a824b2867098cc5c73a6faa16817bdfcdd745e4e4bb5f48b5d497'
ORIGINAL_SHA256 = 'd85a05a9c1c28f3854e95229d92859e65dd9b3f07f757ecd6e4fd69e26605be1'
CLASS_NAMES = ('VirtualDataRequest', 'TranslatedDataRequest', 'TranslationResponseOwner',
               'CheckedDataRequest', 'DataTranslationAdapter')


def validate_source(root):
    binding = json.loads((root / BINDING).read_text())
    reference = (root / REFERENCE).read_bytes()
    assert hashlib.sha256(reference).hexdigest() == REFERENCE_SHA256, 'frozen independent reference drift'
    assert binding['reference_sha256'] == REFERENCE_SHA256
    assert binding['baseline_commit'] == '82c6dce82a0ea63ed2cfc09334624f8d8117d372'
    assert binding['baseline_sha256'] == ORIGINAL_SHA256
    original = reference.decode().split('\n', 1)[1]
    for name in CLASS_NAMES:
        original = original.replace('Reference' + name, name)
    assert hashlib.sha256(original.encode()).hexdigest() == ORIGINAL_SHA256, 'reference is not class-only renamed'
    transport = (root / 'src/test/scala/ooo/PendingStoreProofGsim.scala').read_text()
    prefix = transport.split('class PendingStoreProofBackendGsim')[0]
    assert hashlib.sha256(prefix.encode()).hexdigest() == binding['transport_bridge']['prefix_sha256']


def main():
    runner.DEFAULT_MODELS = 'translated,transport'
    runner.MODELS['translated'] = ('TranslatedFrozenProofGsim', 'translated', [],
                                  ['MEMORY_PROOF_ENABLED=1'], 'COMPACT_PAIR_PASS')
    runner.HOST_FILES['translated'] = 'simulator/gsim/harness/translated_frozen_proof.cpp'
    runner.EXTRA_INPUTS += ['simulator/gsim/translated_frozen_proof.py', BINDING]
    runner.EXTRA_NEGATIVES['translated'] = [
        ('--mutate-token', 'independent original full-tuple certificate mismatch'),
        ('--mutate-data', 'independent original response data mismatch'),
        *[(flag, 'frozen store proof requires') for flag in
          ('--size4', '--size5', '--size6', '--size7', '--mask', '--va', '--offset',
           '--pa-high', '--pa-range', '--unaligned', '--request-size', '--atomic')],
        ('--flush-live', 'VM/PMP/SFENCE changes must drain'),
        ('--pmp-live', 'VM/PMP/SFENCE changes must drain'),
    ]
    runner.validate_source = validate_source
    runner.main()


if __name__ == '__main__':
    main()
