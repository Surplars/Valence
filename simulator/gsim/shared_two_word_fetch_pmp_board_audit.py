#!/usr/bin/env python3
"""Compare complete experimental CHIRRTL exports, excluding source locations only.

Input root must contain before/default/off/on exports and before/after-source-sha256.json.
This performs no export, simulation, qualification, synthesis, or implementation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hardware(text):
    return re.sub(r' @\[[^\n]*?\]', '', text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    repo = Path(__file__).resolve().parents[2]
    sources = json.loads((root / 'after-source-sha256.json').read_text())
    assert sources == {name: sha((repo / name).read_bytes()) for name in sources}, 'source changed after capture'
    raw = {side: (root / side / 'FpgaNextSocTop.fir').read_text() for side in ('before', 'default', 'off', 'on')}
    normalized = {side: hardware(text) for side, text in raw.items()}
    assert normalized['before'] == normalized['default'] == normalized['off'], 'default/off full hardware IR changed'
    assert normalized['on'] != normalized['off'], 'enabled candidate did not change hardware IR'
    actual = {side: json.loads((root / side / 'experiment.json').read_text()) for side in ('default', 'off', 'on')}
    for side, report in actual.items():
        assert report['mode'] == side and report['actualHelperInstances'] == (2 if side == 'on' else 0)
        assert report['coreFields'] == 178 and report['profileFields'] == 95
        assert report['actualNativeMacInstances'] == report['actualBscanInstances'] == 1
        assert report['actualBscanChain'] == 2 and report['actualRamLoaderPresent']
        assert not report['actualCacheRangeCandidate'] and not report['physicalQualification']
        assert report['rawChirrtlSha256'] == sha(raw[side].encode())
        assert report['hardwareChirrtlSha256'] == sha(normalized[side].encode())
        for key in ('core', 'profile', 'fieldOrder'):
            assert report[key] == actual['default'][key], key + ' differs'
    receipt = {
        'schema': 'experimental-shared-two-word-board-comparison-v1',
        'auditScriptSha256': sha(Path(__file__).read_bytes()),
        'status': 'PASS_CONSTRUCTOR_AND_FULL_CHIRRTL_ONLY',
        'excludedFromComparison': 'source-location annotations only; no hardware IR normalization',
        'beforeRawSha256': sha(raw['before'].encode()),
        'rawHashes': {side: sha(text.encode()) for side, text in raw.items()},
        'hardwareHashes': {side: sha(text.encode()) for side, text in normalized.items()},
        'defaultOffFullHardwareIrIdenticalToBefore': True,
        'enabledHelperInstances': 2, 'coreFields': 178, 'profileFields': 95,
        'sourceSha256': sources,
        'prepatchSourceSha256': json.loads((root / 'before-source-sha256.json').read_text()),
        'enabledCallerBehaviorQualified': False, 'physicalQualification': False,
    }
    (root / 'comparison-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('PASS_FULL_CHIRRTL before=default=off; on helpers=2; source locations excluded; no behavior/physical claim')


if __name__ == '__main__':
    main()
