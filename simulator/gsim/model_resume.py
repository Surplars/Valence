#!/usr/bin/env python3
"""Opt-in, host-only relink of an already bound GSIM model. Never runs a DUT.

Consumes the existing focused-runner receipt (inputs_before/after, tools_before/
after, artifacts_sha256), its valence-scala-compile-v1 receipt, and the existing
real-gsim-header-gate-v1 build receipt. It does not import weaker legacy formats.
A caller pins both receipt hashes and selects the exact model directory/top.
Missing historical compile-input linkage is rejected. A checkpoint that merely
lists CPU/compile files cannot supply that missing causal proof. Old formats
without a direct link or complete historical source map require a fresh build;
never edit their sealed receipts to retrofit a link.
This v1 supports the existing bounded harness include style: literal project
includes must resolve inside frozen copies, system headers come from the pinned
toolchain, and actual non-system dependencies are checked after syntax. Macro,
include_next, external include paths, and include-search environment overrides
are deliberately unsupported. No real relink qualification is implied by the
pure mock tests.

--check is read-only. --build creates a fresh directory and returns
RELINKED_NOT_RUN. The owning runner must execute its own positive/negative
oracles and issue a NEW functional receipt; no prior PASS is inherited.
A rejection is explicit (exit 2), never an implicit cache hit or a fresh build.
The caller may then choose its ordinary fresh-build path. No Mill, GSIM, Scala
compile, generated-DUT compile, or simulation is invoked here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import sys

sys.dont_write_bytecode = True
import a1_common_cpu_retirement as base

ROOT = base.common.ROOT
sys.path.insert(0, str(ROOT / 'fpga/common'))
import scala_compile_receipt as scala


class ReuseRejected(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise ReuseRejected(reason)


def sha(path):
    try:
        return base.sha(Path(path))
    except OSError as error:
        raise ReuseRejected('missing/unreadable bound input: ' + str(path)) from error


def read_bound(path, expected):
    path = Path(path).resolve()
    require(re.fullmatch('[0-9a-f]{64}', expected or '') is not None, 'a pinned receipt SHA256 is required')
    require(sha(path) == expected, 'receipt SHA mismatch: ' + str(path))
    return json.loads(path.read_text())


def within(path, root):
    return path == root or root in path.parents


def source_map(prior_inputs):
    # Re-enumerate complete compile inputs (including resources/HardFloat) and
    # the existing conservative harness-header/config closure. New files count.
    current = base.source_inputs()
    for p in scala.compile_source_paths(ROOT):
        current[str(p.relative_to(ROOT))] = sha(p)
    for name in prior_inputs:
        p = (ROOT / name).resolve()
        require(within(p, ROOT), 'source path escapes checkout: ' + name)
        current[name] = sha(p)
    return dict(sorted(current.items()))


def model_members(model, top):
    return {str(p.relative_to(model)): sha(p) for p in sorted(model.rglob('*'))
            if p.is_file() and (p.suffix in ('.fir', '.h', '.hpp', '.inc', '.cpp', '.o')
                                or p.name in ('run-compile-receipt.json', 'effective-config.json',
                                              'effective-parameters.json'))}


def inspect(prior_path, prior_sha, compile_path, compile_sha, model_name, top, host):
    include_environment = {key: os.environ[key] for key in (
        'CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH',
        'DEPENDENCIES_OUTPUT', 'SUNPRO_DEPENDENCIES') if os.environ.get(key)}
    require(not include_environment, 'unbound include/dependency environment: ' + ', '.join(include_environment))
    prior_path, compile_path = Path(prior_path).resolve(), Path(compile_path).resolve()
    host = Path(host).resolve()
    require(host.suffix == '.cpp' and within(host, ROOT), 'one checkout-local host .cpp is required')
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', top or '') is not None, 'invalid top name')
    relative = Path(model_name)
    require(not relative.is_absolute() and '..' not in relative.parts and relative.parts, 'invalid model directory')
    model = (prior_path.parent / relative).resolve()
    require(within(model, prior_path.parent) and model != prior_path.parent, 'model directory escapes receipt scope')
    prior = read_bound(prior_path, prior_sha)
    compile_record = read_bound(compile_path, compile_sha)
    require(prior.get('inputs_unchanged') is True and prior.get('tools_unchanged') is True,
            'prior run lacks unchanged source/tool guards')
    require(prior.get('inputs_before') == prior.get('inputs_after') and
            prior.get('tools_before') == prior.get('tools_after'), 'prior guard values disagree')
    require(prior.get('status') == 'FAIL' or str(prior.get('status', '')).startswith('PASS_'),
            'prior run must be terminal; a functional FAIL is not a build failure')
    require(compile_record.get('schema') == scala.SCHEMA and type(compile_record.get('exit')) is int and
            compile_record['exit'] == 0 and compile_record.get('status') == 'PASS_SCALA_COMPILE',
            'complete successful Scala provenance required')
    require(compile_record.get('sourceRoot') == str(ROOT) and
            compile_record.get('sourceCommit') == prior.get('source_revision'), 'Scala/run source provenance mismatch')
    manifest = compile_record.get('sourceManifest', {})
    require(read_bound(manifest.get('path', ''), manifest.get('sha256', '')) == compile_record['sourceInputs'],
            'Scala source manifest mismatch')
    require(compile_record.get('compiledClasspath') and compile_record.get('runClasspathEntries'),
            'post-compile classpath provenance missing')
    # A host-only relink consumes no current JVM classes. Their historical hash
    # map stays bound by the immutable compile receipt; a new emit must use the
    # ordinary current-head Scala verifier instead, never this historical mode.
    # Never union later compile inputs into historical provenance merely because
    # HEAD is unchanged. Either the parent already pins this exact compile, all
    # its inputs were already in the historical parent. A checkpoint listing
    # unrelated receipts together cannot establish this historical relationship.
    direct = prior.get('scala_compile_receipt')
    complete_history = all(within(Path(name).resolve(), ROOT) and
        prior['inputs_before'].get(str(Path(name).resolve().relative_to(ROOT))) == digest
        for name, digest in compile_record['sourceInputs'].items())
    if direct is not None:
        require(Path(direct.get('path', '')).resolve() == compile_path and direct.get('sha256') == compile_sha,
                'historical parent pins a different compile receipt')
    else:
        require(complete_history, 'compile inputs lack historical binding; fresh build required, not retroactive proof')
    expected_sources = dict(prior['inputs_before'])
    for name, digest in compile_record['sourceInputs'].items():
        p = Path(name).resolve()
        require(within(p, ROOT), 'compile source escapes checkout')
        name = str(p.relative_to(ROOT))
        require(name not in expected_sources or expected_sources[name] == digest,
                'Scala/run source hash disagreement: ' + name)
        expected_sources[name] = digest
    artifacts = prior.get('artifacts_sha256', {})
    prefix = relative.as_posix() + '/'
    expected_artifacts = {name[len(prefix):]: digest for name, digest in artifacts.items()
                          if name.startswith(prefix) and (Path(name).suffix in ('.fir', '.h', '.hpp', '.inc', '.cpp', '.o')
                          or Path(name).name in ('run-compile-receipt.json', 'effective-config.json', 'effective-parameters.json'))}
    require(expected_artifacts and model_members(model, top) == expected_artifacts,
            'model artifact set/hash mismatch (including added or removed files)')
    build_name = 'run-compile-receipt.json'
    require(build_name in expected_artifacts, 'no bound generated-model build receipt; fresh build required')
    build = read_bound(model / build_name, expected_artifacts[build_name])
    require(build.get('schema') == 'real-gsim-header-gate-v1' and build.get('syntax_pass') is True,
            'unsupported/incomplete model build receipt')
    tools = base.tool_binding(True)
    require(tools == prior['tools_after'], 'tool identity mismatch; source/tool changes require a fresh build')
    compiler = tools['compiler']
    require(build.get('compiler') == compiler['path'] and sha(compiler['command']) == compiler['sha256'],
            'DUT compiler binding mismatch')
    flags = build.get('flags')
    require(isinstance(flags, list) and all(isinstance(f, str) for f in flags), 'ordered DUT flags missing')
    safe_flags = {'-std=c++20', '-O0', '-O1', '-O2', '-O3', '-g',
                  '-fsanitize=address,undefined', '-fno-sanitize-recover=all'}
    require(all(f in safe_flags or f.startswith('-D') or f == '-I' + str(model) for f in flags),
            'unsupported flags/dependency roots; use the ordinary fresh-build path')
    include = '-I' + str(model)
    require(flags.count(include) == 1 and all(not f.startswith('-I') or f == include for f in flags),
            'v1 requires exactly the bound model include directory; other include roots need a fresh build')
    headers = {str(p): sha(p) for p in sorted(model.glob('*.h'))}
    require(build.get('headers') == headers, 'model header closure differs from build recipe')
    require(build.get('binary_sha256') == artifacts.get(prefix + 'run') and
            sha(model / 'run') == build.get('binary_sha256'), 'completed old build/binary binding missing')
    old_host = Path(build.get('host', '')).resolve()
    require(within(old_host, ROOT) and old_host.suffix == '.cpp', 'invalid historical host')
    old_host_name = str(old_host.relative_to(ROOT))
    require(expected_sources.get(old_host_name) == build.get('host_sha256'), 'old host provenance missing')
    current_sources = source_map(expected_sources)
    allowed = old_host_name if host == old_host else None
    delta = {name: [expected_sources.get(name), current_sources.get(name)]
             for name in sorted(set(expected_sources) | set(current_sources))
             if expected_sources.get(name) != current_sources.get(name)}
    require(set(delta) <= ({allowed} if allowed else set()), 'non-host input set/hash changed: ' + ', '.join(delta))
    generated = sorted(model.glob(top + '[0-9]*.cpp'))
    require(generated and (model / (top + '.fir')).is_file() and (model / (top + '.h')).is_file(),
            'top/FIR/generated-source identity mismatch')
    objects = build.get('objects', [])
    dut_objects = [entry for entry in objects if Path(entry.get('source', '')).resolve() in generated]
    require(len(dut_objects) == len(generated) and
            {Path(x['source']).resolve() for x in dut_objects} == set(generated), 'DUT translation-unit set mismatch')
    for entry in dut_objects:
        source, obj = Path(entry['source']).resolve(), Path(entry['object']).resolve()
        require(within(obj, model) and obj.suffix == '.o', 'DUT object path escapes model')
        require(sha(source) == entry['source_sha256'] and sha(obj) == entry['object_sha256'],
                'DUT source/object differs from its prior bound hash')
        key = hashlib.sha256(json.dumps({'source': sha(source), 'headers': headers,
                'flags': flags, 'compiler': compiler['sha256']}, sort_keys=True).encode()).hexdigest()
        require(entry.get('key') == key, 'DUT full content key mismatch; filename existence is not proof')
        require(expected_artifacts.get(str(obj.relative_to(model))) == entry['object_sha256'],
                'DUT object is not bound by the parent receipt')
    return {'prior_path': str(prior_path), 'prior_sha256': prior_sha,
            'scala_receipt': str(compile_path), 'scala_receipt_sha256': compile_sha,
            'historical_source_revision': prior['source_revision'], 'model': str(model), 'top': top,
            'model_artifacts': expected_artifacts, 'inputs': current_sources, 'tools': tools,
            'host': str(host), 'host_sha256': sha(host), 'old_host': str(old_host),
            'old_host_sha256': build['host_sha256'], 'allowed_host_delta': delta,
            'dut_recipe': build, 'dut_objects': dut_objects,
            'helper_sha256': sha(__file__), 'include_environment': include_environment}


def check_frozen_includes(copies, model, host):
    allowed = {Path(name).resolve() for name in copies}
    pending, seen = [Path(host).resolve()], set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        require(path in allowed, 'project include is not a frozen input')
        text = path.read_text()
        require(not re.search(r'^\s*#\s*pragma\s+(?:GCC|clang)\s+system_header', text, re.M),
                'project system_header pragma is outside the frozen-include contract')
        require(not re.search(r'^\s*#\s*include_next\b', text, re.M), 'include_next is outside the frozen host contract')
        for line in re.findall(r'^\s*#\s*include\b\s*([^\n]+)', text, re.M):
            match = re.match(r'(["<])([^">]+)[">]', line)
            require(match is not None, 'macro/dynamic include is unsupported by the frozen host contract')
            opening, target = match.groups()
            require(not Path(target).is_absolute(), 'external absolute include is not frozen: ' + target)
            if opening == '"':
                candidates = [(path.parent / target).resolve(), (model / target).resolve()]
                found = next((candidate for candidate in candidates if candidate in allowed), None)
                require(found is not None, 'quoted include escapes frozen closure: ' + target)
                pending.append(found)
            else:
                require('..' not in Path(target).parts, 'angle include escapes frozen/toolchain roots')
                candidate = (model / target).resolve()
                if candidate in allowed:
                    pending.append(candidate)
    return sorted(map(str, seen))


def check_dependencies(path, copies):
    text = Path(path).read_text().replace('\\\n', '')
    require(':' in text, 'compiler did not produce a valid header dependency file')
    dependencies = [Path(name).resolve() for name in shlex.split(text.split(':', 1)[1])]
    allowed = {Path(name).resolve(): digest for name, digest in copies.items()}
    require(dependencies and all(name in allowed and sha(name) == allowed[name] for name in dependencies),
            'actual non-system compiler dependency escapes frozen inputs')
    return {str(name): allowed[name] for name in dependencies}


def execute(command, log):
    base.common.run(command, log=log, timeout=600)


def build_host(arguments, out):
    out = Path(out).resolve()
    require(not out.exists(), 'fresh output directory required; existing evidence is never overwritten')
    prior_root = Path(arguments['prior_path']).resolve().parent
    require(not within(out, prior_root) and not within(prior_root, out), 'new output must be outside prior evidence')
    out.mkdir(parents=True)
    record = {'schema': 'gsim-host-resume-v1', 'status': 'RUNNING', 'scope': 'host-only build; no functional result', 'commands': []}
    def save():
        scala.write_json(out / 'resume-receipt.json', record, exclusive=False)
    save()
    plan = None
    try:
        plan = inspect(**arguments)
        record['binding'] = plan
        snapshot = out / 'model'; snapshot.mkdir()
        copies = {}
        # Only consume verified copies for this build; never emit into, clean,
        # relink in, or overwrite the historical model directory.
        wanted = [name for name in plan['model_artifacts'] if Path(name).suffix in ('.h', '.hpp', '.inc')]
        wanted += [str(Path(e['object']).relative_to(plan['model'])) for e in plan['dut_objects']]
        for name in wanted:
            source, target = Path(plan['model']) / name, snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
            require(sha(target) == plan['model_artifacts'][name], 'model changed while snapshotting: ' + name)
            copies[str(target)] = sha(target)
        for name, expected in plan['inputs'].items():
            if name.startswith('simulator/gsim/harness/') and Path(name).suffix in ('.h', '.hpp', '.inc'):
                target = out / 'inputs' / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target); require(sha(target) == expected, 'host header drift during copy')
                copies[str(target)] = expected
        host = Path(plan['host']); frozen_host = out / 'inputs' / host.relative_to(ROOT)
        frozen_host.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(host, frozen_host)
        require(sha(frozen_host) == plan['host_sha256'], 'host changed while snapshotting')
        copies[str(frozen_host)] = plan['host_sha256']
        literal_dependencies = check_frozen_includes(copies, snapshot, frozen_host)
        old_include = '-I' + plan['model']; new_include = '-I' + str(snapshot)
        flags = [new_include if flag == old_include else flag for flag in plan['dut_recipe']['flags']]
        compiler = plan['tools']['compiler']['command']; obj = out / 'host.o'; binary = out / 'run'
        objects = [snapshot / Path(e['object']).relative_to(plan['model']) for e in plan['dut_objects']]
        commands = [([compiler, *flags, '-MMD', '-MF', out / 'header-deps.d', '-MT', 'host.o', '-fsyntax-only', frozen_host], 'header-syntax.log'),
                    ([compiler, *flags, '-c', frozen_host, '-o', obj], 'host-compile.log'),
                    ([compiler, *flags, *objects, obj, '-ldl', '-o', binary], 'link.log')]
        record['host_recipe'] = {'flags': flags, 'include_relocation': [old_include, new_include],
                                 'frozen_inputs': copies, 'literal_project_dependencies': literal_dependencies}
        for command, name in commands:
            require(inspect(**arguments) == plan, 'input/artifact/tool drift before host build stage')
            require(all(sha(p) == expected for p, expected in copies.items()), 'frozen build inputs changed')
            execute(command, out / name)
            if name == 'header-syntax.log':
                record['host_recipe']['actual_non_system_dependencies'] = check_dependencies(out / 'header-deps.d', copies)
            record['commands'].append({'argv': list(map(str, command)), 'log': name, 'log_sha256': sha(out / name)})
            save()
        require(inspect(**arguments) == plan and all(sha(p) == v for p,v in copies.items()), 'input drift after relink')
        record.update(status='RELINKED_NOT_RUN', host_object_sha256=sha(obj), binary_sha256=sha(binary),
                      simulation_executed=False, inherited_functional_pass=False,
                      current_source_revision=base.git(ROOT, 'rev-parse', 'HEAD').strip())
        return out / 'resume-receipt.json'
    except BaseException as error:
        record.update(status='REJECTED' if isinstance(error, ReuseRejected) else 'BUILD_FAILED',
                      error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-receipt', type=Path, required=True)
    parser.add_argument('--prior-sha', required=True)
    parser.add_argument('--compile-receipt', type=Path, required=True)
    parser.add_argument('--compile-sha', required=True)
    parser.add_argument('--model-subdir', required=True)
    parser.add_argument('--top', required=True)
    parser.add_argument('--host', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true'); mode.add_argument('--build', type=Path, metavar='FRESH_OUT')
    args = parser.parse_args()
    arguments = dict(prior_path=args.prior_receipt, prior_sha=args.prior_sha,
                     compile_path=args.compile_receipt, compile_sha=args.compile_sha,
                     model_name=args.model_subdir, top=args.top, host=args.host)
    try:
        if args.check:
            plan = inspect(**arguments)
            print(json.dumps({'status': 'REUSABLE_DUT_ONLY', 'host_sha256': plan['host_sha256'],
                              'dut_objects': len(plan['dut_objects']), 'functional_pass': False}, sort_keys=True))
        else:
            print('RELINKED_NOT_RUN ' + str(build_host(arguments, args.build)))
        return 0
    except (ReuseRejected, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print('MODEL_REUSE_REJECTED: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
