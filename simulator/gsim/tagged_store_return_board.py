#!/usr/bin/env python3
"""Portable explicit ON profile and exact-source tagged-return board replay.

The default is a command/identity plan, with no build or DUT execution. Fresh
runs require freeze, then individually selected stages with --execute. The
published default flag stays OFF. Historical evidence is not a new runner run.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import bound_store_replay_common as portable

if not __debug__:
    raise SystemExit('Assertions must remain enabled')
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).with_suffix('')
sys.path.insert(0, str(PACKAGE))
from result_contract import capture_result, parse
from verify_service import verify_service

CONTRACT_SHA256 = '8964fb0515e34f0ff2c483fbf1b46d500b8e4627a271842c366f9f521572ac22'
C = {}
MODEL = None
STAGES = ('plan', 'verify', 'freeze', 'constructor', 'emit', 'generate', 'compile',
          'sv39', 'negatives', 'bare', 'fixed', 'host-controls')
NEGATIVES = [('read', 'CPU read data mismatch'),
             ('memory', 'final copied/stored memory mismatch'),
             ('trap', 'unexpected CPU trap cause')]
TAGGED_NEGATIVES = ('wrong-handle illegal-handle wrong-ticket early-store-success false-store-write '
    'reordered-read ordered-bypass ready-oldest held-handle held-data held-fault duplicate-cache '
    'early-physical early-integer high-full-token same-index-live-reuse same-index-stale-generation '
    'wrong-pa cancel-without-drain reuse-after-reply-before-complete duplicate-integer stale-after-release '
    'same-index-completion-stale precise-va fault-bits frozen-local-ack sb-live-reuse sb-unbound fp-before-drain').split()
sha = portable.sha

def load(path):
    return json.loads(Path(path).read_text())

def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def checked(root, items):
    for name, digest in items.items():
        path = Path(root) / name
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert sha(path) == digest, ('input drift', str(path))

def contract(root):
    path = root / 'simulator/gsim/tagged_store_return_board/contract.json'
    assert sha(path) == CONTRACT_SHA256, 'board contract changed; review required'
    spec = load(path)
    assert spec['schema'] == 'tagged-store-return-board-contract-v1'
    assert spec['generic_default'] is False
    for name in ('OooParams', 'FpgaNextConfig'):
        text = (root / ('src/main/scala/core/ooo/' + name + '.scala')).read_text()
        assert re.search(r'\btaggedStoreReturns\s*:\s*Boolean\s*=\s*false\b', text)
    for section in ('profile', 'core'):
        assert spec['profile'][section]['taggedStoreReturns'] is True
    assert spec['actual_fabric']['cpu']['taggedStoreReturns'] is True
    assert spec['native_options'][-1] == '--tagged-store-returns'
    checked(root, spec['source_inputs'])
    actual_sources = {str(p.relative_to(root)) for base in ('src', 'third_party')
                      for p in (root / base).rglob('*.scala')}
    assert actual_sources == {n for n in spec['source_inputs'] if n.endswith('.scala')}, 'Scala input set drift'
    for item in [*spec['host_sources'].values(), spec['fixed_header']]:
        checked(root, {item['source']: item['sha256']})
    return spec

def host_materialize(root, destination, spec, fixed=False):
    destination.mkdir(parents=True, exist_ok=False)
    for name, row in spec['host_sources'].items():
        source = spec['fixed_header'] if fixed and name == 'harness/board_ddr_benchmark.h' else row
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / source['source'], target)
        assert sha(target) == source['sha256']

def model_files(model):
    return {p.name: sha(p) for p in sorted(model.iterdir())
            if p.is_file() and p.suffix in ('.fir', '.h', '.cpp', '.o', '.d', '.json', '.txt')}

def model_identity(model, spec):
    assert json.dumps(load(model / 'profile.json'),sort_keys=True) == json.dumps(spec['profile'],sort_keys=True), 'complete constructor changed'
    assert json.dumps(load(model / 'actual-fabric.json'),sort_keys=True) == json.dumps(spec['actual_fabric'],sort_keys=True), 'complete actual fabric changed'
    assert sha(model / 'assembly-contract.json') == spec['assembly_contract_sha256']
    assert (model / 'options.txt').read_text().splitlines() == spec['native_options']

def paths(args):
    return {'source': args.source_root.resolve(), 'model': args.model_root.resolve(),
            'output': args.output.resolve(), 'guest': args.guest_root.resolve()}

def recipe(spec, p, tools):
    """All original constructor/emit/generate/compile/run parameters, unretuned."""
    m, out, guest = p['model'], p['output'], p['guest']
    host, fixed = out / 'host', out / 'fixed-host'
    mill, gsim, cxx = (tools[n] for n in ('mill', 'gsim', 'cxx'))
    flags = spec['cxx_flags'] + ['-I' + str(m)]
    def hflags(h):
        return flags + spec['host_defines'] + ['-I'+str(guest), '-I'+str(h), '-I'+str(h/'harness')]
    rows = []
    def add(stage, label, argv, cwd=None, expected=0, anchor=None):
        rows.append({'stage':stage, 'label':label, 'argv':list(map(str,argv)),
                     'cwd':str(cwd or p['source']), 'expected_exit':expected, 'anchor':anchor})
    add('constructor', 'constructor-on', [mill,'-i','-j','1','IonSoC.test.runMain',
        'ooo.FpgaNextProfileMain',out/'constructor-on',*spec['native_options']])
    add('emit', 'cpu-emit', [mill,'-i','-j','1','IonSoC.test.runMain',
        'ooo.CpuMatchingBoardProfileGsimMain',m,*spec['native_options']])
    add('generate', 'cpu-generate', [gsim,'--threads=1','--cpp-max-size-KB=1024',
        '--dir='+str(m),m/'BoardSocGsim.fir'])
    add('compile','host-syntax',[cxx,*hflags(host),'-fsyntax-only',host/'cpu_passive_bandwidth.cpp'])
    add('compile','host-dependencies',[cxx,*hflags(host),'-M','-MT','unit',host/'cpu_passive_bandwidth.cpp'])
    units = sorted(n for n in spec['qualified_model_files'] if re.fullmatch(r'BoardSocGsim\d+\.cpp', n))
    assert len(units) == 37
    for i,n in enumerate(units):
        unit=m/n
        add('compile','compile-'+str(i),[cxx,*flags,'-MD','-MF',unit.with_suffix('.d'),'-c',unit,'-o',unit.with_suffix('.o')])
    objects = [m/n for n in sorted(spec['qualified_objects'])]
    add('compile','host-link',[cxx,*hflags(host),host/'cpu_passive_bandwidth.cpp',*objects,'-o',out/'run'])
    add('sv39','cpu-sv39',[out/'run',guest/'guest.bin',1,2,65536,2],out/'sv39',anchor='CPU_SV39_PASS')
    for injection, anchor in NEGATIVES:
        add('negatives','negative-'+injection,[out/'run',guest/'guest.bin',1,2,4096,1,'--inject-'+injection],
            out/('negative-'+injection),1,anchor)
    add('bare','bare',[out/'run',guest/'guest.bin',0,2,65536,2],out/'bare',anchor='CPU_SV39_PASS')
    add('fixed','fixed-host-dependencies',[cxx,*hflags(fixed),'-M','-MT','unit',fixed/'cpu_passive_bandwidth.cpp'])
    add('fixed','fixed-host-link',[cxx,*hflags(fixed),fixed/'cpu_passive_bandwidth.cpp',*objects,'-o',out/'fixed-run'])
    add('fixed','fixed',[out/'fixed-run',guest/'guest.bin',1,2,65536,2],out/'fixed',anchor='CPU_SV39_PASS')
    for injection, anchor in NEGATIVES:
        add('fixed','fixed-negative-'+injection,[out/'fixed-run',guest/'guest.bin',1,2,4096,1,'--inject-'+injection],
            out/('fixed-negative-'+injection),1,anchor)
    controls = out / 'controls'
    control_flags = ['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
    for stem, positive, mutations, reject in [
        ('tagged_return','TAGGED_ORACLE_POSITIVE_PASS',TAGGED_NEGATIVES,'TAGGED_ORACLE_REJECT'),
        ('passive','PASS',('invalid-payload sum history phase pa source bucket').split(),'FAIL'),
        ('ledger','PASS',('dirty token reserved wb pa ack-block payload posted-pa posted-duplicate posted-generation posted-missing-install attach-pa attach-ticket attach-duplicate attach-lost-binding').split(),'FAIL')]:
        binary=controls/stem
        defs=[] if stem=='tagged_return' else ['-DREAD_PREFETCH_DIRTY_RETRY=1','-DREAD_PREFETCH_DEMAND_ADOPTION=1']
        add('host-controls',stem+'-build',[cxx,*control_flags,*defs,host/(stem+'_negative.cpp'),'-o',binary])
        add('host-controls',stem+'-positive',[binary],controls,anchor=positive)
        for name in mutations:
            add('host-controls',stem+'-'+name,[binary,name if stem=='tagged_return' else '--'+name],controls,1,reject)
    add('host-controls','getter-build',[cxx,*control_flags,host/'tagged_getter_guard.cpp','-o',controls/'getter'])
    add('host-controls','getter-positive',[controls/'getter'],controls,anchor='TAGGED_GETTER_GUARD_PASS')
    add('host-controls','getter-negative',[controls/'getter','--poison'],controls,1,'INVALID_PAYLOAD_GETTER')
    lawroot=p['source']/'simulator/gsim/bound_store_prefetch/burst_locked'
    add('host-controls','law-build',[cxx,*control_flags,'-I'+str(controls),lawroot/'law_controls_r2.cpp','-o',controls/'law'])
    add('host-controls','law-positive',[controls/'law'],controls,anchor='LAW_CONTROLS_PASS cases=5')
    for option,anchor in [('unlock','interleaved or reordered burst ID'),('held-data','held R payload changed'),
            ('last-release','held LAST payload/RESP changed or burst released early')]:
        add('host-controls','law-'+option,[controls/'law','--inject-'+option],controls,1,anchor)
    return rows

def capture(text,work,name):
 row=capture_result(text,work,C['baseline_cases'][name],load(MODEL/'actual-fabric.json'));row['baseline_kind']='D1_PUBLISHED_EXACT_FULL_PROFILE_REUSED_EVIDENCE'
 row['tagged']=parse(text,'TAGGED_RETURN_PASS')
 assert row['tagged']['namespace']=='7' and row['tagged']['handle_bits']=='3' and row['tagged']['full_token_bits']=='68'
 assert row['tagged']['physical']==row['tagged']['physical_replies']==row['tagged']['cache_replies']
 assert row['tagged']['sb_accepted']==row['tagged']['sb_replies']
 row['cause_attribution']='EXACT_TAGGED_OWNER_LEDGER_AND_ORIGINAL_BYTE_ORACLE'
 row['strictly_better_than_published']=row['inclusive_delta']<0
 return row

def tool_inputs(tools, args):
    """Bind the executable chain and libraries used by the qualified toolchain."""
    if args.tool_bindings:
        extra={name:Path(path).resolve() for name,path in load(args.tool_bindings).items()}
    elif args.toolchain_root:
        root=args.toolchain_root.resolve()
        extra={name:root/path for name,path in {
            'mill_dist':'bin/mill-dist','firtool':'firtool-1.135.0/firtool','java':'jdk21/bin/java',
            'clang_cpp':'sysroot/usr/lib/x86_64-linux-gnu/libclang-cpp.so.19.1',
            'riscv_as':'sysroot/usr/bin/riscv64-unknown-elf-as',
            'riscv_gcc':'sysroot/usr/bin/riscv64-unknown-elf-gcc'}.items()}
        extra['system_llvm']=args.system_llvm.resolve()
    else:
        raise ValueError('supply --toolchain-root or --tool-bindings for the complete tool identity')
    assert set(extra)=={'mill_dist','firtool','java','clang_cpp','riscv_as','riscv_gcc','system_llvm'}
    return portable.tool_binding({**tools,**extra})

def current_inputs(root, spec):
    files = [Path(__file__), root/'simulator/gsim/bound_store_replay_common.py']
    files += [root/'simulator/gsim/bound_store_prefetch/burst_locked'/name for name in ('law_controls_r2.cpp','fake_axi.h')]
    files += [p for p in (root/'simulator/gsim/tagged_store_return_board').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    return {**spec['source_inputs'], **{r['source']:r['sha256'] for r in spec['host_sources'].values()},
            spec['fixed_header']['source']:spec['fixed_header']['sha256'],
            **{str(p.relative_to(root)):sha(p) for p in files}}

def main(argv=None):
    global C, MODEL
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('stage',nargs='?',default='plan',choices=STAGES)
    portable.add_paths(parser,ROOT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--guest-root',type=Path,required=True)
    parser.add_argument('--baseline-model',type=Path,help='Original d1 OFF model for read-only generated semantic binding')
    parser.add_argument('--tool-bindings',type=Path,help='JSON map of seven supplemental tool/library names to paths')
    parser.add_argument('--system-llvm',type=Path,default=Path('/usr/lib/x86_64-linux-gnu/libLLVM.so.19.1'))
    parser.add_argument('--execute',action='store_true',help='Execute only the selected stage after an explicit freeze')
    args=parser.parse_args(argv)
    if args.source_root.resolve()!=ROOT:
        parser.error('invoke this entry from the selected source checkout; --source-root must match it')
    C=contract(args.source_root.resolve());p=paths(args);MODEL=p['model']
    tools=portable.tool_paths(args,parser);checked(p['guest'],C['guest'])
    commands=recipe(C,p,tools);inputs=current_inputs(p['source'],C)
    plan={'schema':'tagged-store-return-portable-v1','status':'PLAN_ONLY_NO_DUT_EXECUTION',
          'generic_default':False,'explicit_profile':'ON','source_inputs':inputs,
          'tools':tool_inputs(tools,args),'paths':{k:str(v) for k,v in p.items()},
          'guest':C['guest'],'commands':commands,'limitations':C['limitations'],
          'historical_qualification_inherited':False,'portable_launcher_dynamically_executed':False}
    if args.stage=='verify':
        model_identity(MODEL,C)
        checked(MODEL,C['qualified_model_files'])
        assert sorted(x.name for x in MODEL.glob('BoardSocGsim*.cpp')) == sorted(n for n in C['qualified_model_files'] if n.endswith('.cpp'))
        checked(MODEL,C['qualified_objects'])
        for name,old in [('mill','mill_wrapper'),('gsim','gsim'),('cxx','clang')]:
            assert sha(tools[name])==C['qualified_tools'][old]['sha256'],('qualified tool mismatch',name)
        if 'activate' in tools:assert sha(tools['activate'])==C['qualified_activation_sha256']
        for name,row in plan['tools'].items():
            if name not in ('mill','gsim','cxx','activate'):assert row['sha256']==C['qualified_tools'][name]['sha256'],('qualified supplemental tool mismatch',name)
        plan['status']='PASS_READ_ONLY_QUALIFIED_MODEL_INPUT_BRIDGE'
    if args.stage in ('plan','verify') or args.preflight_only:
        print(json.dumps(plan,indent=2));return
    receipt=p['output']/'receipt.json'
    if args.stage=='freeze':
        assert not args.execute, 'freeze is read-only toward tools and DUT'
        assert not p['output'].exists() and not p['model'].exists(), 'use fresh output and model paths'
        assert p['output']!=p['model'] and not p['output'].is_relative_to(p['model'])
        p['output'].mkdir(parents=True)
        plan.update(status='FROZEN_NO_EXECUTION',stages={},results={},artifacts={},executed=[])
        write(receipt,plan);print('FROZEN_NO_EXECUTION');return
    if not args.execute:parser.error('executing a selected stage requires --execute; plan is the default')
    state=load(receipt)
    assert state['schema']==plan['schema'] and 'failure' not in state
    for key in ('source_inputs','tools','paths','guest','commands'):
        assert state[key]==plan[key],('frozen input drift',key)
    assert args.stage not in state['stages'],'no implicit stage rerun'
    def save():write(receipt,state)
    def guard():
        checked(p['source'],state['source_inputs']);checked(p['guest'],state['guest'])
        portable.check_tools(state['tools'])
        for filename,digest in state['artifacts'].items():assert sha(filename)==digest,('artifact drift',filename)
    def bind(directory):
        for f in directory.rglob('*'):
            if f.is_file():state['artifacts'][str(f)]=sha(f)
    def prior(name):assert state['stages'].get(name)=='PASS',('missing stage',name)
    def run(row):
        guard();log=p['output']/(row['label']+'.log');assert not log.exists()
        Path(row['cwd']).mkdir(parents=True,exist_ok=True)
        start=time.monotonic()
        with log.open('x') as stream:
            proc=subprocess.Popen(portable.command_args(row['argv'],tools),cwd=row['cwd'],stdout=stream,stderr=subprocess.STDOUT,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'})
            state['portable_launcher_dynamically_executed']=True;save()
            _,code,usage=os.wait4(proc.pid,0);proc.returncode=os.waitstatus_to_exitcode(code)
        text=log.read_text();ok=proc.returncode==row['expected_exit'] and (not row['anchor'] or row['anchor'] in text)
        ok=ok and not re.search(r'ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer',text)
        state['executed'].append({**row,'exit':proc.returncode,'seconds':time.monotonic()-start,
            'max_rss_KiB':usage.ru_maxrss,'log_sha256':sha(log),'status':'PASS' if ok else 'FAIL'})
        save();assert ok,(row['label'],text[-3000:]);return text
    with (p['output']/'.stage.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            guard()
            if args.stage=='emit':prior('constructor');p['model'].mkdir(parents=True,exist_ok=False)
            elif args.stage=='generate':prior('emit');model_identity(MODEL,C)
            elif args.stage=='compile':
                prior('generate');model_identity(MODEL,C)
                assert args.baseline_model,'--baseline-model required for actual generated semantic binding'
                assert not list(MODEL.glob('*.o'))
                host_materialize(p['source'],p['output']/'host',C)
                import generated_semantic_audit as audit
                report=audit.audit(args.baseline_model.resolve(),MODEL,p['output']/'host')
                write(p['output']/'host-semantics.json',report);bind(p['output']/'host')
                actual=sorted(x.name for x in MODEL.glob('BoardSocGsim*.cpp'))
                expected=sorted(n for n in C['qualified_model_files'] if n.endswith('.cpp'))
                assert actual==expected,'official split translation units differ; review before compiling'
            elif args.stage=='sv39':prior('compile')
            elif args.stage=='negatives':prior('sv39')
            elif args.stage=='bare':prior('negatives')
            elif args.stage=='fixed':prior('bare');host_materialize(p['source'],p['output']/'fixed-host',C,True);bind(p['output']/'fixed-host')
            elif args.stage=='host-controls':
                if not (p['output']/'host').exists():host_materialize(p['source'],p['output']/'host',C)
                controls=p['output']/'controls';controls.mkdir()
                fixed=controls/'on-host/harness';fixed.mkdir(parents=True)
                shutil.copyfile(p['source']/C['fixed_header']['source'],fixed/'board_ddr_benchmark.h')
                bind(p['output']/'host')
            for row in commands:
                if row['stage']!=args.stage:continue
                text=run(row)
                if row['label'] in ('cpu-sv39','bare','fixed'):
                    name='sv39' if row['label']=='cpu-sv39' else row['label']
                    state['results'][name]=capture(text,Path(row['cwd']),name)
                    if name=='fixed':
                        service=verify_service(Path(row['cwd'])/'axi-events.tsv')
                        assert service['no_interleaving'] and service['transactions']>0
                        state['results'][name]['service']=service
                if row['label'].startswith('compile-'):
                    obj=Path(row['argv'][-1]);dep=obj.with_suffix('.d')
                    assert obj.is_file() and dep.is_file()
                    state['artifacts'][str(obj)]=sha(obj);state['artifacts'][str(dep)]=sha(dep)
                    portable.record_dependencies(dep,p['source'],state['artifacts']);save()
                if row['label'].endswith('dependencies'):
                    dep=p['output']/(row['label']+'.d');dep.write_text(text)
                    portable.record_dependencies(dep,p['source'],state['artifacts'])
            if args.stage=='constructor':assert json.dumps(load(p['output']/'constructor-on/profile.json'),sort_keys=True)==json.dumps(C['profile'],sort_keys=True)
            if args.stage in ('emit','generate','compile'):
                model_identity(MODEL,C);bind(MODEL)
            for name in ('run','fixed-run','host-semantics.json'):
                if (p['output']/name).is_file():state['artifacts'][str(p['output']/name)]=sha(p['output']/name)
            guard();state['stages'][args.stage]='PASS';state['status']='PASS_'+args.stage.upper()+'_ONLY';save()
            print(state['status'])
        except BaseException as error:
            state.update(status='STOPPED_FIRST_FAILURE',failure={'stage':args.stage,'message':str(error)})
            save();raise

if __name__=='__main__':main()
