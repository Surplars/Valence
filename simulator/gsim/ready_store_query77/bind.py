#!/usr/bin/env python3
"""Regenerate held semantic bindings for an explicitly supplied model; never run it.
Bindings remain pending independent semantic review, even when all fields prove.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from prepare import HERE, sha, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--repository', type=Path, default=HERE.parents[2])
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.repository.resolve())
    model, output = args.model.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(HERE):
        raise ValueError('fresh binding output outside package required')
    hashes = {name: sha(model / name) for name in ('BoardSocGsim.fir', 'BoardSocGsim.h')}
    output.mkdir(parents=True)
    for name in ('binding_memory', 'binding_memory_core'):
        key = name + '_generate'
        spec = importlib.util.spec_from_file_location(key, HERE / 'held' / (key + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
        result = module.generate(model)
        (output / (name + '_on.json')).write_text(json.dumps(result, indent=2) + '\n')
        missing = [f for f in result['fields'] if f['required'] and f['status'] != 'PROVEN']
        if missing:
            raise ValueError('required semantic bindings missing: ' + repr([f['target'] for f in missing]))
        text = module.emit(result) if name == 'binding_memory' else module.emit(result, 'binding_memory_on.h')
        (output / (name + '_on.h')).write_text(text)
    if hashes != {name: sha(model / name) for name in hashes}:
        raise ValueError('model changed while binding')
    (output / 'receipt.json').write_text(json.dumps({'status': 'BINDINGS_GENERATED_INDEPENDENT_REVIEW_REQUIRED',
        'model': hashes, 'manifest_sha256': sha(HERE / 'inputs.json'), 'runtime_qualified': False}, indent=2) + '\n')


if __name__ == '__main__':
    main()
