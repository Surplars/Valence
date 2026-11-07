#!/usr/bin/env python3
"""Focused APLIC guest-routing acceptance, plus existing APLIC/IMSIC/UART regressions.

Use a supplied GSIM and C++ compiler. --runtime-manifest and --scala-cache allow
an offline native Scala compile from already installed, hash-pinned dependencies.
Without them the standard Mill test module is used. No downloads or physical flows.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    'src/main/scala/ip/bus/RegisterPort.scala',
    'src/main/scala/ip/bus/TwoMasterRegisterArbiter.scala',
    'src/main/scala/ip/interrupt/Aplic.scala',
    'src/main/scala/ip/interrupt/Imsic.scala',
    'src/main/scala/ip/uart/UartConsole.scala',
    'src/main/scala/platform/CommonInterruptFabric.scala',
    'src/test/scala/ip/AiaGuestGsim.scala',
    'src/main/scala/core/ooo/system/HypervisorGuestInterrupts.scala',
    'src/test/scala/ip/AiaGuestRoutingGsim.scala',
    'src/test/scala/ip/AiaGuestParamsSpec.scala',
    'src/test/scala/ip/ImsicParamsSpec.scala',
    'src/test/scala/ip/AplicGsim.scala',
    'src/test/scala/ip/AplicBoundaryGsim.scala',
    'src/test/scala/ip/ImsicGsim.scala',
    'src/test/scala/ip/AiaSupervisorUartGsim.scala',
]

INPUTS = SOURCES + ['simulator/gsim/aia_guest_acceptance.py'] + [
    'simulator/gsim/harness/'+s+'.cpp' for s in ['aia_guest','aia_guest_routing','aia_genmsi_order','aplic','aplic_boundary','imsic','aia_supervisor_uart']]

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--gsim', type=Path, required=True)
    p.add_argument('--cxx', type=Path, required=True)
    p.add_argument('--runtime-manifest', type=Path)
    p.add_argument('--scala-cache', type=Path)
    p.add_argument('--mill', default='mill -i -j2')
    p.add_argument('--boundaries', action='store_true', help='also qualify maximum identities/guests and address-space ends')
    p.add_argument('--max-sources', action='store_true', help='with --boundaries, attempt resource-intensive 1023-source APLIC runtime')
    args = p.parse_args()
    if args.max_sources and not args.boundaries: p.error('--max-sources requires --boundaries')
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    record = dict(status='RUNNING', commands=[], sources={s: sha(ROOT/s) for s in INPUTS},
                  tools={str(t): sha(t) for t in [args.gsim,args.cxx]},
                  physical_timing_qualified=False, cpu_virtualization_qualified=False)
    def save(): (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    def run(argv, log, negative=None):
        argv = list(map(str,argv)); start=time.monotonic()
        with log.open('w') as f:
            result = subprocess.run(argv,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=600,
                                    env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        record['commands'].append(dict(argv=argv,exit=result.returncode,seconds=time.monotonic()-start,
                                       log=str(log.relative_to(out))))
        save(); text=log.read_text()
        if negative:
            if result.returncode!=1 or negative not in text: raise RuntimeError('negative control: '+str(log))
        elif result.returncode: raise RuntimeError('command failed: '+str(log))
        return text
    try:
        save()
        if args.runtime_manifest:
            assert args.scala_cache, '--scala-cache required with --runtime-manifest'
            manifest=json.loads(args.runtime_manifest.read_text())
            for path,digest in manifest.items():
                assert sha(path)==digest, 'dependency hash mismatch: '+path
            cache=args.scala_cache.resolve()
            def jar(fragment):
                matches=list(cache.rglob(fragment)); assert len(matches)==1,(fragment,matches)
                return str(matches[0])
            compiler=[jar('scala-'+x+'-2.13.17.jar') for x in ['compiler','library','reflect']]
            plugin=jar('chisel-plugin_2.13.17-7.3.0.jar')
            classes=out/'classes'; classes.mkdir()
            record['runtime_dependencies']=manifest
            record['scala_tools']={p:sha(p) for p in compiler+[plugin]}
            cp=':'.join(manifest)
            run(['java','-Xmx2g','-XX:ActiveProcessorCount=2','-cp',':'.join(compiler),
                 'scala.tools.nsc.Main','-classpath',cp,'-Xplugin:'+plugin,
                 '-language:reflectiveCalls','-d',classes,*[ROOT/s for s in SOURCES]],out/'compile.log')
            runtime=str(classes)+':'+cp
            java=['java','-Xmx2g','-XX:ActiveProcessorCount=2','-cp',runtime]
            run([*java,'org.scalatest.tools.Runner','-o','-s','ip.AiaGuestParamsSpec',
                 '-s','ip.ImsicParamsSpec'],out/'config.log')
            emit=lambda main,folder,params: [*java,main,folder,*params]
        else:
            run([*shlex.split(args.mill),'IonSoC.test.testOnly','ip.AiaGuestParamsSpec',
                 'ip.ImsicParamsSpec'],out/'config.log')
            emit=lambda main,folder,params: [*shlex.split(args.mill),'IonSoC.test.runMain',main,folder,*params]
        cases=[('genmsi-order','ip.AiaGuestGsimMain','AiaGuestGsim','aia_genmsi_order.cpp',['2'],{}),
               ('guest','ip.AiaGuestGsimMain','AiaGuestGsim','aia_guest.cpp',['2'],{}),
               ('aplic','ip.AplicGsimMain','Aplic','aplic.cpp',['31'],{'APLIC_SOURCES':31}),
               ('imsic','ip.ImsicGsimMain','Imsic','imsic.cpp',['127','2'],
                {'IMSIC_IDENTITIES':127,'IMSIC_GUESTS':2}),
               ('uart','ip.AiaSupervisorUartGsimMain','AiaSupervisorUartGsim','aia_supervisor_uart.cpp',[],{}),
               ('routing','ip.AiaGuestRoutingGsimMain','AiaGuestRoutingGsim','aia_guest_routing.cpp',[],{})]
        if args.boundaries:
            for name,identities,guests,machine,supervisor in [
                ('imsic-max-guests',63,63,'24000000','28000000'),
                ('imsic-max-identities',2047,0,'24000000','28000000'),
                ('imsic-top-machine',63,0,'fffffffffffff000','28000000'),
                ('imsic-top-supervisor',63,2,'24000000','ffffffffffffc000'),
                ('imsic-adjacent',63,1,'2000','0'),
                ('imsic-padding',63,62,'24000000','28000000')]:
                cases.append((name,'ip.ImsicGsimMain','Imsic','imsic.cpp',
                              [str(identities),str(guests),machine,supervisor],
                              {'IMSIC_IDENTITIES':identities,'IMSIC_GUESTS':guests,
                               'IMSIC_MACHINE_BASE':'0x'+machine+'ULL',
                               'IMSIC_SUPERVISOR_BASE':'0x'+supervisor+'ULL'}))
            for sources in ([1,255,1023] if args.max_sources else [1,255]):
                cases.insert(0,('aplic-boundary-'+str(sources),'ip.AplicBoundaryGsimMain','Aplic',
                              'aplic_boundary.cpp',[str(sources),'ffffffffffffc000','fffffffffff000'],
                              {'APLIC_SOURCES':sources,'APLIC_BASE':'0xffffffffffffc000ULL',
                               'APLIC_MSI_BASE':'0x00fffffffffff000ULL'}))
            for guests in [0,1,3,63]:
                cases.append(('guest-boundary-'+str(guests),'ip.AiaGuestGsimMain','AiaGuestGsim',
                              'aia_guest.cpp',[str(guests)],{'AIA_GUEST_BOUNDARY':guests}))
        for name,main,top,harness,params,defines in cases:
            folder=out/name; folder.mkdir()
            run(emit(main,folder,params),folder/'emit.log')
            fir=folder/(top+'.fir')
            if fir.stat().st_size % 4096==0: fir.write_bytes(fir.read_bytes()+b'\n')
            run([args.gsim,'--threads=1','--dir='+str(folder),fir],folder/'generate.log')
            cpp=sorted(folder.glob(top+'[0-9]*.cpp')); assert cpp
            binary=folder/'run'
            run([args.cxx,'-std=c++20','-O1','-fbracket-depth=4096','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                 *['-D'+k+'='+str(v) for k,v in defines.items()],'-I'+str(folder),*cpp,
                 ROOT/'simulator/gsim/harness'/harness,'-ldl','-o',binary],folder/'link.log')
            text=run([binary],folder/'run.log'); print(text,end='',flush=True)
            assert 'PASS' in text, 'missing completion marker: '+name
            if name=='genmsi-order':
                run([binary,'--wrong-order'],folder/'negative.log', negative='independent cross-domain genmsi order')
            if name.startswith('aplic-boundary'):
                run([binary,'--wrong-address'],folder/'negative.log', negative='independent boundary MSI address')
            if name.startswith('imsic'):
                run([binary,'--inject-mismatch'],folder/'negative.log', negative='CSR response mismatch')
            if name=='guest':
                run([binary,'--wrong-address'],folder/'negative.log',
                    negative='independent guest MSI destination oracle')
            if name=='routing':
                run([binary,'--wrong-guest'],folder/'negative.log',
                    negative='independent APLIC IMSIC guest routing oracle')
        assert record['sources']=={s:sha(ROOT/s) for s in INPUTS},'source changed during regression'
        record['status']='PASS_FINITE_AIA_GUEST'
    except BaseException as e:
        record['status']='FAIL'; record['error']=repr(e); raise
    finally:
        record['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*')
                             if p.is_file() and p.name!='receipt.json'}
        save()
if __name__=='__main__': main()
