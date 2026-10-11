#!/usr/bin/env python3
"""One source-bound compile, configuration checks, and four ordinary native exports."""
import argparse, copy, gzip, hashlib, importlib.util, json, os, re, shutil, signal, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SOURCE = BASE / 'memory-state-reuse-implementation-20261011-r1/source'
HISTORICAL = BASE / 'posted-preparation-priority-native-r1/execution/on'
OUT = HERE / 'execution'
MIB = 1024 ** 2
MODES = {'off-off': (False, False), 'on-off': (True, False), 'off-on': (False, True), 'on-on': (True, True)}
FLAGS = ['reconstructIssueTokenIndex', 'sharedMemoryAddressState']
CLI_FLAGS = ['--reconstruct-issue-token-index', '--shared-memory-address-state']
FIRTOOL_OPTIONS = ['--format=fir', '--split-verilog', '--strip-debug-info', '--disable-all-randomization', '--default-layer-specialization=disable']

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def inv(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}

def source_inventory():
    return {str(p.relative_to(SOURCE)): sha(p) for p in sorted(SOURCE.rglob('*'))
            if p.is_file() and p.relative_to(SOURCE).parts[0] not in ['.git', 'out', 'build']}

def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args], text=True).strip()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def size(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.exists() else 0

def prepare():
    require(not (HERE / 'plan.json').exists(), 'fresh plan required')
    require(git('status', '--porcelain') == '', 'source must be clean at freeze')
    fixture = 'src/test/scala/ooo/MemoryStateReuseNativeProfiles.scala'
    require(sha(SOURCE / fixture) == sha(HERE / 'fixture/MemoryStateReuseNativeProfiles.scala'), 'native fixture differs')
    historical_profile = read(HISTORICAL / 'profile.json')
    expected = {}
    canonical = {}
    for name, values in MODES.items():
        profile = copy.deepcopy(historical_profile)
        for group in ['profile', 'core', 'storage']:
            require(not set(FLAGS) & profile[group].keys(), 'historical flags already present')
            profile[group].update(dict(zip(FLAGS, values)))
        expected[name] = profile
        canonical[name] = sorted(read(HISTORICAL / 'actual-parameters.json')['canonicalOptions'] +
                                 [flag for flag, enabled in zip(CLI_FLAGS, values) if enabled])
        save(HERE / ('expected-profile-' + name + '.json'), profile)
    tool_receipt = read(BASE / 'toolchain/tool-receipt.json')
    tools = {tool_receipt['files'][name]['path']: tool_receipt['files'][name]['sha256']
             for name in ['mill_dist', 'mill_wrapper', 'firtool']}
    jdk = BASE / 'toolchain/env/cache/coursier/arc/https/cdn.azul.com/zulu/bin/zulu21.48.15-ca-jdk21.0.10-linux_x64.tar.gz/zulu21.48.15-ca-jdk21.0.10-linux_x64'
    require((jdk / 'bin/java').is_file(), 'pinned JDK absent')
    tools[str(jdk / 'bin/java')] = sha(jdk / 'bin/java')
    tools[str(jdk / 'release')] = sha(jdk / 'release')
    freeze = dict(git_head=git('rev-parse', 'HEAD'), git_tree=git('rev-parse', 'HEAD^{tree}'),
                  hardware_commit='4d3f1b57643ac9e59d379192e25e03372f6bd2c5', source_root=str(SOURCE), files=source_inventory())
    save(HERE / 'source-freeze.json', freeze)
    plan = dict(schema='memory-state-reuse-native-plan-v1', status='PREPARED_NO_JAVA_OR_NATIVE_RUN',
                source_freeze_sha256=sha(HERE / 'source-freeze.json'), source_commit=freeze['git_head'], source_tree=freeze['git_tree'],
                tools=tools, java=str(jdk / 'bin/java'), jdk=str(jdk), expected_profiles=expected, canonical_flags=canonical,
                tool_receipt_sha256=sha(BASE / 'toolchain/tool-receipt.json'),
                helpers={str(p.relative_to(HERE)): sha(p) for p in sorted(HERE.rglob('*'))
                         if p.is_file() and p.suffix in ['.py', '.scala']},
                historical_receipt_sha256=sha(HISTORICAL / 'receipt.json'),
                limits=dict(minimum_free_bytes=650*MIB, output_cap_bytes=100*MIB, build_cap_bytes=250*MIB,
                            seconds_per_stage=1800, log_cap_bytes=8*MIB),
                native_simulation=False, GSIM=False, Clang=False, mapped_PPA_STA=False)
    save(HERE / 'plan.json', plan)
    source_guard(plan)
    print(json.dumps({'status': plan['status'], 'source_commit': freeze['git_head'], 'plan_sha256': sha(HERE / 'plan.json')}))

def source_guard(plan):
    require(sha(HERE / 'source-freeze.json') == plan['source_freeze_sha256'], 'source freeze drift')
    frozen = read(HERE / 'source-freeze.json')
    require(source_inventory() == frozen['files'], 'source inventory or bytes drift')
    require(git('rev-parse', 'HEAD') == frozen['git_head'] and git('status', '--porcelain') == '', 'source commit/worktree drift')
    for path, expected in plan['tools'].items():
        require(sha(path) == expected, 'tool drift ' + path)
    for path, expected in plan['helpers'].items():
        require(sha(HERE / path) == expected, 'helper drift ' + path)

def runtime_guard(runtime):
    for path, expected in runtime['directories'].items():
        require(inv(Path(path)) == expected, 'runtime directory drift ' + path)
    for path, expected in runtime['files'].items():
        require(sha(path) == expected, 'runtime file drift ' + path)
    for path in runtime['absent_resources']:
        require(not Path(path).exists(), 'absent runtime resource appeared ' + path)

def bind_runtime():
    manifest = SOURCE / 'out/IonSoC/test/runClasspath.json'
    values = read(manifest)['value']
    paths = []
    for value in values:
        match = re.fullmatch(r'(?:qref:v1|ref:v0):[^:]+:(/.+)', value)
        require(match is not None, 'classpath schema')
        paths.append(Path(match[1]))
    runtime = dict(source_freeze_sha256=sha(HERE / 'source-freeze.json'), classpath_manifest=str(manifest),
                   classpath_manifest_sha256=sha(manifest), paths=[str(p) for p in paths], files={}, directories={}, absent_resources=[])
    for path in paths:
        if path.is_dir():
            runtime['directories'][str(path)] = inv(path)
        elif path.is_file():
            runtime['files'][str(path)] = sha(path)
        else:
            require(path.name in ['resources', 'compile-resources'], 'absent non-resource classpath ' + str(path))
            runtime['absent_resources'].append(str(path))
    runtime['files'][str(manifest)] = sha(manifest)
    save(OUT / 'runtime-binding.json', runtime)
    return runtime

def sample(pgid):
    total = 0
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            stat = (path/'stat').read_text().rsplit(')', 1)[1].split()
            if int(stat[2]) == pgid:
                match = re.search(r'^VmRSS:\s+(\d+)', (path/'status').read_text(), re.M)
                total += int(match[1]) if match else 0
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    return total

def stage(label, command, plan, state, runtime=None, input_gzip=None):
    source_guard(plan)
    if runtime:
        runtime_guard(runtime)
    log = OUT / (label + '.log')
    trace = OUT / (label + '.resources.jsonl')
    start = time.monotonic()
    peak = 0
    reason = None
    feeder = None
    print('RUN ' + label, flush=True)
    with log.open('x') as stream, trace.open('x') as samples:
        process = subprocess.Popen(command, cwd=SOURCE, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.PIPE if input_gzip else None, start_new_session=True)
        if input_gzip:
            def feed():
                try:
                    with gzip.open(input_gzip, 'rb') as source:
                        shutil.copyfileobj(source, process.stdin, MIB)
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()
            feeder = threading.Thread(target=feed)
            feeder.start()
        while True:
            elapsed = time.monotonic() - start
            rss = sample(process.pid)
            peak = max(peak, rss)
            output_bytes = size(OUT)
            build_bytes = size(SOURCE/'out')
            samples.write(json.dumps(dict(elapsed_seconds=elapsed, rss_kib=rss, output_bytes=output_bytes, build_bytes=build_bytes)) + '\n')
            samples.flush()
            if shutil.disk_usage(HERE).free < plan['limits']['minimum_free_bytes']:
                reason = 'disk_floor'
            elif output_bytes > plan['limits']['output_cap_bytes']:
                reason = 'output_cap'
            elif build_bytes > plan['limits']['build_cap_bytes']:
                reason = 'build_cap'
            elif elapsed > plan['limits']['seconds_per_stage']:
                reason = 'wall_timeout'
            elif log.stat().st_size > plan['limits']['log_cap_bytes']:
                reason = 'log_cap'
            if reason or process.poll() is not None:
                break
            time.sleep(1)
        if reason:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        if feeder:
            feeder.join(timeout=5)
    state['steps'].append(dict(label=label, command=command, cwd=str(SOURCE), exit=process.returncode, guard=reason,
                              elapsed_seconds=time.monotonic()-start, observed_peak_process_group_rss_kib=peak,
                              log_sha256=sha(log), resource_sha256=sha(trace), stdin_gzip_sha256=sha(input_gzip) if input_gzip else None))
    save(OUT/'receipt.json', state)
    require(process.returncode == 0 and reason is None, 'stage failed ' + label + ': ' + str(reason))
    print('PASS ' + label, flush=True)

def audit_profile(mode, plan):
    profile = read(OUT/mode/'profile.json')
    actual = read(OUT/mode/'actual-parameters.json')
    require(profile == plan['expected_profiles'][mode], 'full profile drift ' + mode)
    require(actual['entryProfile'] == profile['profile'] and actual['expectedCore'] == profile['core'], 'actual profile drift')
    require(actual['allActualParametersEqualExpected'] is True and actual['hardwareMutation'] is False and actual['qualificationInherited'] is False, 'actual audit flags')
    require(actual['topClass'] == 'soc.core.ooo.FpgaNextSocTop' and actual['canonicalOptions'] == plan['canonical_flags'][mode], 'actual native top/options mismatch')
    for key, group, count in [('coreParameters', 'core', 6), ('cacheConcurrency', 'cache', 3), ('ddrParameters', 'ddr', 2)]:
        require(len(actual[key]) == count and len({x['instancePath'] for x in actual[key]}) == count, 'constructor count ' + key)
        require(all(x['values'] == profile[group] for x in actual[key]), 'constructor values ' + key)
    return actual

def run(slot):
    require(slot, 'coordinator slot grant required')
    plan = read(HERE/'plan.json')
    source_guard(plan)
    require(not OUT.exists(), 'fresh execution directory required')
    require(shutil.disk_usage(HERE).free > 800*MIB, 'insufficient starting reserve')
    tokens = os.environ.get('JAVA_TOOL_OPTIONS', '').split()
    require('-Xmx4g' in tokens and '-XX:ActiveProcessorCount=2' in tokens, 'activate pinned toolchain')
    os.environ['JAVA_HOME'] = plan['jdk']
    os.environ['PATH'] = str(Path(plan['jdk'])/'bin') + os.pathsep + os.environ['PATH']
    OUT.mkdir()
    state = dict(schema='memory-state-reuse-native-execution-v1', status='RUNNING', plan_sha256=sha(HERE/'plan.json'), steps=[], native_simulation=False, GSIM=False, Clang=False, mapped_PPA_STA=False)
    save(OUT/'receipt.json', state)
    try:
        mill = read(BASE/'toolchain/tool-receipt.json')['files']['mill_wrapper']['path']
        stage('shared-scala-compile', [mill, '-i', '-j', '1', 'show', 'IonSoC.test.runClasspath'], plan, state)
        runtime = bind_runtime()
        classpath = os.pathsep.join(runtime['paths'])
        java = plan['java']
        specs = ['MemoryStateReuseConfigSpec', 'PostedPreparationPriorityConfigSpec', 'StorePrefetchLruVictimConfigSpec',
                 'MemoryProofFrontierConfigSpec', 'CanonicalVirtualStoreBoardConfigSpec', 'CanonicalVirtualStoreConfigSpec']
        stage('configuration-spec', [java, '-Dchisel.project.root='+str(SOURCE), '-cp', classpath,
                                    'org.scalatest.tools.Runner', '-o', *sum((['-s', 'ooo.'+spec] for spec in specs), [])], plan, state, runtime)
        state['compile_and_configuration'] = 'PASS'
        save(OUT/'receipt.json', state)
        print('SHARED_COMPILE_AND_CONFIG_PASS ' + str(OUT/'runtime-binding.json'), flush=True)
        firtool = read(BASE/'toolchain/tool-receipt.json')['files']['firtool']['path']
        for mode, values in MODES.items():
            dest = OUT/mode
            stage(mode+'-constructors', [java, '-Dchisel.project.root='+str(SOURCE), '-cp', classpath,
                                        'ooo.MemoryStateReuseNativeMain', str(dest), *mode.split('-')], plan, state, runtime)
            audit_profile(mode, plan)
            raw_path = dest/'FpgaNextSocTop.fir'
            raw = raw_path.read_bytes()
            raw_sha = hashlib.sha256(raw).hexdigest()
            raw_size = len(raw)
            gz_path = dest/'FpgaNextSocTop.fir.gz'
            temp = dest/'FpgaNextSocTop.fir.gz.tmp'
            with temp.open('xb') as stream:
                with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
                    compressed.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            require(gzip.decompress(temp.read_bytes()) == raw, 'FIR lossless compression check')
            temp.replace(gz_path)
            directory_fd = os.open(dest, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            require(sha(raw_path) == raw_sha, 'FIR changed before archive')
            raw_path.unlink()
            del raw
            (dest/'rtl').mkdir()
            stage(mode+'-native', [firtool, '-', *FIRTOOL_OPTIONS, '-o', str(dest/'rtl')], plan, state, runtime, gz_path)
            freeze = read(HERE/'source-freeze.json')
            receipt = dict(status='PASS_RTL_EXPORT_ONLY', git_head=freeze['git_head'], git_tree=freeze['git_tree'],
                           source_sha256=freeze['files'], profile=dict(lsu_entries=4, rob_entries=64, physical_registers=64,
                           memory_proof_frontier=True, store_prefetch_lru_victim=True, posted_preparation_priority=True,
                           reconstruct_issue_token_index=values[0], shared_memory_address_state=values[1]),
                           full_profile=read(dest/'profile.json'), actual_parameters_sha256=sha(dest/'actual-parameters.json'),
                           fir_sha256=raw_sha, fir_bytes=raw_size, compressed_fir_sha256=sha(gz_path), compressed_fir_lossless_verified=True,
                           rtl_sha256={'rtl/'+name: digest for name, digest in inv(dest/'rtl').items()},
                           runtime_binding_sha256=sha(OUT/'runtime-binding.json'), plan_sha256=sha(HERE/'plan.json'),
                           qualification='Native elaboration/lowering only; no mapped PPA/STA')
            save(dest/'receipt.json', receipt)
        source_guard(plan)
        runtime_guard(runtime)
        state['status'] = 'PASS_FOUR_FRESH_NATIVE_EXPORTS_ONLY'
    except BaseException as error:
        state['status'] = 'FAIL'
        state['error'] = str(error)
        raise
    finally:
        save(OUT/'receipt.json', state)
    print(json.dumps({'status': state['status']}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--slot-granted', action='store_true')
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else run(args.slot_granted)
