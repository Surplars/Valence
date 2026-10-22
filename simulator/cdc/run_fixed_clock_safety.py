#!/usr/bin/env python3
"""Source-bound Icarus component regression; never emits, modifies, or builds Scala.
Every child is bounded, grouped, and reaped. Negative controls must hit the
specified ordinary scoreboard assertion, not merely exit unsuccessfully.
"""
import argparse, hashlib, json, os, pathlib, shutil, signal, subprocess, time
HERE = pathlib.Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument('--repo', type=pathlib.Path, required=True, help='Valence checkout that produced the pinned emission receipt')
p.add_argument('--rtl', type=pathlib.Path)
p.add_argument('--emission', type=pathlib.Path)
p.add_argument('--out', type=pathlib.Path, default=HERE / 'results')
a = p.parse_args(); a.repo = a.repo.resolve()
a.rtl = (a.rtl or a.repo / 'out/cmu-frequency-r24/platform-r2-rtl').resolve()
a.emission = (a.emission or a.repo / 'out/cmu-frequency-r24/platform-r2-emission.json').resolve()
a.out = a.out.resolve(); a.out.mkdir(parents=True, exist_ok=False)
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def run(cmd, name, timeout=30):
    started = time.monotonic()
    proc = subprocess.Popen([str(x) for x in cmd], cwd=a.out, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try: output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True; os.killpg(proc.pid, signal.SIGKILL); output, _ = proc.communicate()
    log = a.out / (name + '.log'); log.write_bytes(output)
    return dict(command=[str(x) for x in cmd], returncode=proc.returncode,
                seconds=round(time.monotonic()-started, 6), timed_out=timed_out,
                reaped=proc.poll() is not None, log=str(log), log_sha256=sha(log)), output.decode(errors='replace')
sources = ['src/main/scala/ip/clock/FixedClockSafetyGuard.scala',
           'src/main/scala/ip/bus/CdcDataChannels.scala',
           'src/main/scala/ip/bus/ClockDomainCrossing.scala']
rtl_names = ['FixedClockSafetyGuard.sv', 'CdcMailbox_40.sv', 'CdcMailbox_41.sv', 'CdcLevel.sv', 'CdcResetRelease.sv']
emission = json.loads(a.emission.read_text())
assert emission['status'] == 'PASS_EMIT_ONLY' and emission['returncode'] == 0
binding = {'emission_receipt': str(a.emission), 'emission_sha256': sha(a.emission),
           'source_sha256': {}, 'rtl_sha256': {}, 'tools_sha256': {}, 'test_sha256': {}}
frozen = a.out / 'frozen-rtl'; frozen.mkdir(exist_ok=True)
for rel in sources:
    actual = sha(a.repo / rel)
    assert actual == emission['source_sha256'][rel], f'Source changed since emission: {rel}'
    binding['source_sha256'][rel] = actual
for name in rtl_names:
    actual = sha(a.rtl / name)
    assert actual == emission['rtl_sha256'][name], f'RTL changed since emission: {name}'
    shutil.copyfile(a.rtl / name, frozen / name)
    assert sha(frozen/name) == actual
    binding['rtl_sha256'][name] = actual
native = a.repo.parent / 'native-tools'
iverilog = native / 'bin/iverilog'; vvp = native / 'root/usr/bin/vvp'
for rel in ['bin/iverilog', 'root/usr/bin/iverilog', 'root/usr/bin/vvp',
            'root/usr/lib/x86_64-linux-gnu/ivl/ivl', 'root/usr/lib/x86_64-linux-gnu/ivl/ivlpp',
            'root/usr/lib/x86_64-linux-gnu/ivl/vvp.tgt']:
    binding['tools_sha256'][str(native/rel)] = sha(native/rel)
for path in [HERE/'fixed_clock_safety_tb.sv', pathlib.Path(__file__).resolve()]:
    binding['test_sha256'][path.name] = sha(path)
    shutil.copyfile(path, a.out/path.name)
versions = []
for exe, label in [(iverilog, 'iverilog-version'), (vvp, 'vvp-version')]:
    result, _ = run([exe, '-V'], label); versions.append(result)
compile_result, output = run([iverilog, '-g2012', '-s', 'fixed_clock_safety_tb', '-o', a.out/'guard.vvp',
                              a.out/'fixed_clock_safety_tb.sv', *[frozen/n for n in rtl_names]], 'compile')
if compile_result['returncode'] or compile_result['timed_out']:
    print(output); raise SystemExit('Icarus compilation failed')
positives = ['arm_exact','backpressure','unsafe_arm','arm_just_raised','arm_just_revoked','brief_revoke','disarm_then_change','disarm_at_change',
             'wrong_epoch','duplicate_active','duplicate_retired','zero_epoch','reset_command','reset_receipt','reset_fault','pause_receipt']
cases = [(x, 'none', None) for x in positives] + [
    ('arm_exact','tag','FAIL_TAG'), ('arm_exact','guarded','FAIL_WINDOW guarded'),
    ('arm_exact','drop_receipt','FAIL_CONSERVATION'), ('brief_revoke','fault','FAIL_WINDOW fault')]
results = []
for case, injection, expected_error in cases:
    name = case if injection == 'none' else 'negative_' + injection
    result, output = run([vvp, a.out/'guard.vvp', f'+CASE={case}', f'+INJECT={injection}'], name, timeout=30)
    passed = (not result['timed_out'] and result['reaped'] and
              ((result['returncode'] == 0 and f'PASS case={case} ' in output and 'FAIL_' not in output)
               if expected_error is None else
               (result['returncode'] != 0 and expected_error in output and 'PASS case=' not in output)))
    result.update(name=name, case=case, injection=injection, expected_failure=expected_error,
                  status='PASS' if passed else 'FAIL')
    results.append(result); print(name, result['status'], f"{result['seconds']:.3f}s")
    if not passed: print(output)
for rel, digest in binding['source_sha256'].items(): assert sha(a.repo/rel) == digest
for name, digest in binding['rtl_sha256'].items(): assert sha(a.rtl/name) == digest
receipt = dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL',
               scope='Isolated actual FixedClockSafetyGuard with emitted CDC dependencies; no dynamic-platform, physical-clock, MMCM, timing-closure, or production frequency-whitelist qualification.',
               binding=binding, versions=versions, compile=compile_result, cases=results,
               positive_cases=len(positives), negative_controls=len(cases)-len(positives),
               timeout_seconds_per_process=30, all_processes_reaped=all(r['reaped'] for r in results))
(a.out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print('Receipt:', a.out/'receipt.json')
raise SystemExit(0 if receipt['status']=='PASS' else 1)
