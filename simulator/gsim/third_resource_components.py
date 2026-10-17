#!/usr/bin/env python3
"""Short cache-write-data and fixed-caller PMP GSIM components, no CPU or physical run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import run as common


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True)
    p.add_argument('--component', choices=['cache', 'cache512', 'pmp', 'pmp-high-address'], required=True)
    p.add_argument('--posted', choices=['0', '1'], default='1')
    p.add_argument('--negative', choices=['miss-uses-live-request', 'hit-uses-stale-fill',
                                        'refill-ignores-byte-mask', 'posted-uses-refill-bytes'])
    p.add_argument('--build-run', action='store_true')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        p.error('tag must contain only letters, digits, underscore or hyphen')
    if a.component == 'cache512' and a.posted != '1':
        p.error('cache512 fixture requires posted=1')
    if a.negative and (a.component != 'cache' or a.posted != '1'):
        p.error('source negatives require cache and posted=1')
    cases = {'miss-uses-live-request': 'miss-merge', 'hit-uses-stale-fill': 'all-hit-masks',
             'refill-ignores-byte-mask': 'miss-merge', 'posted-uses-refill-bytes': 'posted-banks'}
    # A negative must run in an explicitly prepared disposable source copy. Never mutate production here.
    if a.negative:
        sys.path.insert(0, str(common.HERE / 'cache_write_data'))
        from make_source_negative import MUTATIONS
        old, new, _ = MUTATIONS[a.negative]
        text = (common.ROOT / 'src/main/scala/core/ooo/cache/NonBlockingCoherentLineCache.scala').read_text()
        if text.count(new) != 1 or old in text:
            p.error('requested exact source mutant is absent; see validation document')
    if not a.build_run:
        print('THIRD_RESOURCE_COMPONENT_READY component=' + a.component)
        return
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    gsim, cxx = common.setup(False)
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'PYTHONDONTWRITEBYTECODE': '1'}
    commands = []
    def run(name, cmd, directory=out, negative=False, anchors=()):
        log = directory / (name + '.log')
        with log.open('x') as stream:
            result = subprocess.run(list(map(str, cmd)), cwd=common.ROOT, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=900)
        text = log.read_text()
        commands.append({'name': name, 'exit': result.returncode,
                         'log': str(log.relative_to(out)),
                         'sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        if (result.returncode == 0) == negative or any(x not in text for x in anchors):
            raise RuntimeError(str(log) + '\n' + text[-4000:])
        if any(x in text for x in ['ERROR: AddressSanitizer', 'runtime error:',
                                  'UndefinedBehaviorSanitizer', 'NEGATIVE_CONTROL_ESCAPED']):
            raise RuntimeError('invalid sanitizer/control result: ' + str(log))
    def model(d, main, top, args):
        run('emit', ['mill', '-i', 'IonSoC.test.runMain', main, d, *args], d)
        run('generate', [gsim, '--threads=1', '--cpp-max-size-KB=1024', '--dir='+str(d), d/(top+'.fir')], d)
    def compile_host(d, top, host, defines=()):
        units = sorted(d.glob(top+'[0-9]*.cpp'))
        if not units: raise RuntimeError('no GSIM translation units')
        run('compile', [cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', *defines, '-I'+str(d), *units,
                        host, '-ldl', '-o', d/'run'], d)
    if a.component in ('cache', 'cache512'):
        large = a.component == 'cache512'
        top = 'CacheWriteData512Gsim' if large else 'CacheWriteDataGsim'
        model(out, 'ooo.'+top+'Main', top, [a.posted, '1', '0' if a.negative else '1', '1', '1'])
        sys.path.insert(0, str(common.HERE / 'posted_cache_rebuild'))
        from ports import emit_driver
        driver = out/'driver.cpp'
        emit_driver(driver)
        driver.write_text(driver.read_text().replace('PostedStoreCacheGsim', top))
        compile_host(out, top, driver)
        fixture = 'cache_write_data_512_fixture.py' if large else 'cache_write_data_fixture.py'
        args = [sys.executable, common.HERE/'cache_write_data'/fixture,
                '--executable', out/'run', '--output', out/'host-results']
        if not large: args += ['--enabled', a.posted]
        if a.negative: args += ['--case', cases[a.negative], '--expect-physical-byte-failure']
        run('test', args)
        result = json.loads((out/'host-results/result.json').read_text())
        expected = 'EXPECTED_PHYSICAL_BYTE_ORACLE_FAILURE' if a.negative else 'PASS'
        if result['status'] != expected: raise RuntimeError('unexpected fixture status')
    else:
        configs = [('walker'+str(i), 'FixedPmpWalkerGsim', 'pmp_fixed_walker.cpp', [str(i)],
                    ['-DMAX_LEVELS='+str(i)], 'FIXED_CALLER_WALKER_PASS') for i in (3,4,5)]
        configs += [('cache'+str(i), 'FixedPmpLineCacheGsim', 'pmp_fixed_line_cache.cpp',
                     ['no-prefetch',str(i),'parallel-addresses','--banked-cache-tags','--banked-instruction-data'],
                     ['-DPACKET_WORDS='+str(i)], 'FIXED_CALLER_CACHE_PASS') for i in (2,4)]
        configs += [('prefetch', 'FixedPmpLineCacheGsim', 'pmp_fixed_line_prefetch.cpp',
                     ['prefetch','4','parallel-addresses','--banked-cache-tags','--banked-instruction-data'],
                     ['-DPACKET_WORDS=4'], 'GSIM instruction prefetch: PASS')]
        if a.component == 'pmp-high-address':
            configs = [(name, top, host, args + ['lines=16', 'compact-tags',
                        '--ram-base=2147549184', '--ram-bytes=2147483648'],
                        defines + ['-DCACHE_LINES=16', '-DCACHE_BASE=2147549184ULL',
                        '-DCOMPACT_TAG_TEST=1'] + ([] if name == 'prefetch' else ['-DCROSS4G_TEST=1']),
                        anchor) for name, top, host, args, defines, anchor in configs
                       if not name.startswith('walker')]
        for name, top, host, args, defines, anchor in configs:
            d = out/name; d.mkdir()
            model(d, 'ooo.'+top+'Main', top, args)
            compile_host(d, top, common.HERE/'harness'/host, defines)
            run('positive', [d/'run'], d, anchors=(anchor,))
            if name.startswith('walker'):
                run('observer-negative', [d/'run','--inject-raw-denied'], d, True,
                    ('REACHED raw-permission-observer','WALKER_RAW_BYTE_ORACLE'))
            elif name != 'prefetch':
                run('service-negative', [d/'run','--inject-mismatch'], d, True,
                    ('REACHED cache-service-corruption','GSIM instruction line cache: FAIL'))
    (out/'receipt.json').write_text(json.dumps({'status':'PASS_COMPONENT_ONLY',
        'component':a.component,'negative':a.negative,'commands':commands,
        'full_cpu':False,'physical_metrics':'UNMEASURED'}, indent=2)+'\n')

if __name__ == '__main__':
    main()
