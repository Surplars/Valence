#!/usr/bin/env python3
"""Produce or verify the bound Scala compile receipt used by candidate exporters.

Run from any directory. The checkout root comes from this script, not the caller.
No hardware is emitted or simulated. A failed attempt retains logs/attempt.json
but never publishes a successful-schema compile-receipt.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SCHEMA = 'valence-scala-compile-v1'
ROOT = Path(__file__).resolve().parents[2]
SCALA_ROOTS = ('src/main/scala', 'src/test/scala', 'third_party/berkeley-hardfloat/src/main/scala')
RESOURCE_ROOTS = ('src/main/resources', 'src/test/resources', 'compile-resources',
                  'third_party/berkeley-hardfloat/src/main/resources',
                  'third_party/berkeley-hardfloat/compile-resources')
BUILD_INPUTS = ('build.mill', '.mill-version', '.mill-jvm-opts')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_map(paths):
    return {str(Path(path).resolve()): sha(path) for path in sorted(set(paths))}


def compile_source_paths(root):
    root = Path(root)
    sources = [p for name in SCALA_ROOTS for p in (root / name).rglob('*.scala') if p.is_file()]
    sources += [p for name in RESOURCE_ROOTS for p in (root / name).rglob('*') if p.is_file()]
    sources += [root / name for name in BUILD_INPUTS]
    return sorted(set(sources))


def parse_pathref(value):
    # Mill's ref/qref:version:hash:path has three metadata colons. Splitting at
    # every colon would corrupt a native Windows drive path such as C:\\repo.
    require(isinstance(value, str), 'invalid Mill PathRef')
    fields = value.split(':', 3)
    require(len(fields) == 4 and fields[0] in ('ref', 'qref') and fields[3], 'invalid Mill PathRef')
    return fields[3]


def split_java_classpath(value, separator=None):
    return value.split(os.pathsep if separator is None else separator)


def normalized_path(value, root):
    path = Path(value)
    return (path if path.is_absolute() else Path(root) / path).resolve()


def current_classpath(root):
    root = Path(root)
    record = json.loads((root / 'out/IonSoC/test/runClasspath.json').read_text(encoding='utf-8'))
    values = record['value']
    require(isinstance(values, list) and values, 'empty Mill runtime classpath')
    entries = [str(normalized_path(parse_pathref(value), root)) for value in values]
    files = []
    for entry in entries:
        path = Path(entry)
        if path.is_dir():
            files.extend(p for p in path.rglob('*') if p.is_file())
        elif path.is_file():
            files.append(path)
    # Preserve entry order, duplicates, and missing optional resource directories;
    # only the expanded file map is deduplicated, matching the Scala consumer.
    classes = file_map(files)
    require(classes, 'empty compiled classpath')
    return entries, classes


def source_commit(root):
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def verify_record(receipt, root, java_classpath=None):
    root = Path(root).resolve()
    require(isinstance(receipt, dict), 'compile receipt must be an object')
    require(receipt.get('schema') == SCHEMA and type(receipt.get('exit')) is int and receipt['exit'] == 0,
            'complete successful bound compile receipt required; legacy exit-only rejected')
    require(receipt.get('sourceRoot') == str(root), 'compile source root mismatch')
    require(receipt.get('sourceCommit') == source_commit(root), 'compile source commit mismatch')
    sources = file_map(compile_source_paths(root))
    require(receipt.get('sourceInputs') == sources, 'compile source set/hash mismatch')
    manifest = receipt.get('sourceManifest', {})
    require(set(manifest) == {'path', 'sha256'}, 'compile source manifest binding missing')
    require(sha(manifest['path']) == manifest['sha256'] and
            json.loads(Path(manifest['path']).read_text(encoding='utf-8')) == sources,
            'compile source manifest mismatch')
    entries, classes = current_classpath(root)
    require(receipt.get('runClasspathEntries') == entries and receipt.get('compiledClasspath') == classes,
            'post-compile runtime classpath set/hash mismatch')
    if java_classpath is not None:
        actual = [str(normalized_path(entry, root)) for entry in split_java_classpath(java_classpath)]
        require(actual == entries, 'actual Java classpath entry/order mismatch')
    return receipt


def verify_receipt(path, root=ROOT, java_classpath=None):
    return verify_record(json.loads(Path(path).read_text(encoding='utf-8')), root, java_classpath)


def write_json(path, record, exclusive=True):
    with Path(path).open('x' if exclusive else 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def produce(root, out, mill='mill'):
    root, out = Path(root).resolve(), Path(out).resolve()
    require(not out.exists(), 'fresh output directory required; existing evidence is never overwritten')
    out.mkdir(parents=True)
    attempt = dict(status='RUNNING', exit=None, sourceRoot=str(root), commands=[])
    attempt_path = out / 'attempt.json'
    write_json(attempt_path, attempt)
    start = time.monotonic()
    try:
        executable = shutil.which(str(mill))
        require(executable is not None, 'Mill executable not found: ' + str(mill))
        executable = str(Path(executable).resolve())
        sources = file_map(compile_source_paths(root))
        commit = source_commit(root)
        manifest = out / 'compile-source-inputs.json'
        write_json(manifest, sources)
        receipt = dict(schema=SCHEMA, status='PASS_SCALA_COMPILE', exit=0,
            sourceRoot=str(root), sourceCommit=commit,
            sourceManifest=dict(path=str(manifest), sha256=sha(manifest)), sourceInputs=sources,
            producer=dict(path=str(Path(__file__).resolve()), sha256=sha(__file__)),
            mill=dict(path=executable, sha256=sha(executable)))
        for name, command, timeout in (
                ('compile', [executable, '-i', 'IonSoC.test.compile'], 600),
                ('classpath', [executable, '-i', 'show', 'IonSoC.test.runClasspath'], 120)):
            require(file_map(compile_source_paths(root)) == sources and source_commit(root) == commit,
                    'source/commit drift before ' + name)
            log_path = out / (name + '.log')
            command_record = dict(name=name, command=command, exit=None, log=str(log_path))
            attempt['commands'].append(command_record)
            try:
                with log_path.open('x', encoding='utf-8') as log:
                    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                command_record['exit'] = result.returncode
            finally:
                if log_path.is_file():
                    command_record['log_sha256'] = sha(log_path)
            require(command_record['exit'] == 0, name + ' failed; see ' + str(log_path))
        receipt['runClasspathEntries'], receipt['compiledClasspath'] = current_classpath(root)
        receipt['commands'] = attempt['commands']
        verify_record(receipt, root)
        destination = out / 'compile-receipt.json'
        write_json(destination, receipt)
        attempt.update(status='PASS_SCALA_COMPILE', exit=0,
                       receipt=dict(path=str(destination), sha256=sha(destination)))
        return destination
    except BaseException as error:
        failed = [item['exit'] for item in attempt['commands'] if item['exit'] not in (None, 0)]
        attempt.update(status='FAIL', exit=failed[-1] if failed else 1,
                       error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        attempt['elapsed_seconds'] = time.monotonic() - start
        write_json(attempt_path, attempt, exclusive=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--out', type=Path, help='new output directory for compile logs and bound receipt')
    mode.add_argument('--verify', type=Path, help='verify an existing receipt without compiling or emitting')
    parser.add_argument('--mill', default='mill', help='native Mill executable (default: PATH lookup)')
    parser.add_argument('--java-classpath', help='optional actual Java classpath for --verify; uses os.pathsep')
    args = parser.parse_args()
    if args.java_classpath is not None and args.verify is None:
        parser.error('--java-classpath requires --verify')
    try:
        if args.verify is not None:
            verify_receipt(args.verify, ROOT, args.java_classpath)
            print('SCALA_COMPILE_RECEIPT_VERIFIED ' + str(args.verify.resolve()))
        else:
            print('SCALA_COMPILE_RECEIPT_PASS ' + str(produce(ROOT, args.out, args.mill)))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print('SCALA_COMPILE_RECEIPT_BLOCKED: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
