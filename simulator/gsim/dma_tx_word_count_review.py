"""Run only review-gap drivers against hash-verified saved default GSIM models."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,re,subprocess,sys,time
r=Path(__file__).resolve().parents[2]
if len(sys.argv)>1 and sys.argv[1]=='--guard-probe':
 b=oldout=out=None
else:
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--baseline-root',type=Path,required=True)
 ap.add_argument('--prior',type=Path,required=True)
 ap.add_argument('--output',type=Path,required=True)
 ap.add_argument('--gsim',type=Path,required=True)
 args=ap.parse_args()
 b=args.baseline_root.resolve();oldout=args.prior.resolve();out=args.output.resolve()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def loadmodule():
 spec=importlib.util.spec_from_file_location('runner',r/'simulator/gsim/dma_tx_word_count.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
if len(sys.argv)>1 and sys.argv[1]=='--guard-probe':
 data=json.loads(Path(sys.argv[2]).read_text());m=loadmodule()
 m.validate_source_pair(data['frozen'])
 m.validate_reuse(data['reused'],data['frozen'],data['gsim'],data['baseline'])
 print('REUSE_GUARD_PASS');sys.exit(0)
out.mkdir(parents=True,exist_ok=False)
old=json.loads((oldout/'receipt.json').read_text());m=loadmodule()
baseline=subprocess.check_output(['git','rev-parse','HEAD'],cwd=b,text=True).strip()
gsim=args.gsim.resolve()
assert baseline==m.BASELINE_COMMIT and sha(gsim)==old['gsim_sha256']
for arm,root in [('baseline',b),('candidate',r)]:
 current={str(p.relative_to(root)):sha(p) for p in root.glob('src/**/*.scala')}
 expected={n:h for n,h in old['source_inputs'][arm].items() if n.startswith('src/')}
 assert current==expected,'saved-model Scala source set or hash mismatch'
 oracle='simulator/gsim/harness/ethernet_packet_dma.cpp'
 assert sha(root/oracle)==old['source_inputs'][arm][oracle],'saved-model independent oracle mismatch'

record=dict(status='RUNNING',baseline_commit=baseline,prior_receipt_sha256=sha(oldout/'receipt.json'),
 gsim_sha256=sha(gsim),commands=[],models={},metrics={},scope='saved default M2048 posted0/4 models; test drivers only; no emission/full matrix/STOP rerun/Vivado',
 sources={n:sha(r/n) for n in ['simulator/gsim/dma_tx_word_count.py','simulator/gsim/harness/dma_tx_word_count.cpp',
 'simulator/gsim/harness/ethernet_packet_dma.cpp','src/main/scala/ip/dma/EthernetPacketDma.scala']})
env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1','PYTHONDONTWRITEBYTECODE':'1'}
def save():(out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
def run(label,cmd,expected=0,anchor=None):
 log=out/(label+'.log');t=time.monotonic()
 with log.open('x') as f:p=subprocess.run(list(map(str,cmd)),stdout=f,stderr=subprocess.STDOUT,env=env,timeout=600)
 text=log.read_text(errors='replace')
 record['commands'].append(dict(label=label,exit=p.returncode,seconds=round(time.monotonic()-t,3),log_sha256=sha(log)));save()
 assert p.returncode==expected and (anchor is None or anchor in text),(label,text[-5000:])
 print(label,'PASS',flush=True);return text
save()
try:
 # Probe the actual public validation functions in separate processes with forged receipts.
 good=dict(frozen=copy.deepcopy(old['source_inputs']),reused=old,gsim=sha(gsim),baseline=baseline)
 variants={'matching':(good,0,'REUSE_GUARD_PASS')}
 def variant(name,change,anchor):
  d=copy.deepcopy(good);change(d);variants[name]=(d,1,anchor)
 variant('simulator',lambda d:d['reused'].update(gsim_sha256='0'*64),'reused simulator hash mismatch')
 variant('baseline-head',lambda d:d.update(baseline='0'*40),'baseline HEAD is not the pinned commit')
 variant('receipt-commit',lambda d:d['reused'].update(baseline_commit='0'*40),'receipt baseline commit mismatch')
 key=next(iter(old['source_inputs']['candidate']))
 variant('reuse-added-source',lambda d:d['reused']['source_inputs']['candidate'].update({'src/extra.scala':'0'*64}),'reused source sets or hashes changed')
 variant('reuse-missing-source',lambda d:d['reused']['source_inputs']['baseline'].pop(key),'reused source sets or hashes changed')
 variant('reuse-changed-hash',lambda d:d['reused']['source_inputs']['candidate'].update({key:'0'*64}),'reused source sets or hashes changed')
 variant('pair-extra-candidate',lambda d:d['frozen']['candidate'].update({'src/extra.scala':'0'*64}),'asymmetric source file sets')
 variant('pair-extra-baseline',lambda d:d['frozen']['baseline'].update({'src/extra.scala':'0'*64}),'asymmetric source file sets')
 for name,(data,code,anchor) in variants.items():
  path=out/('forged-'+name+'.json');path.write_text(json.dumps(data))
  run('guard-'+name,[sys.executable,'-B',__file__,'--guard-probe',path],code,anchor)
 for arm in ['baseline','candidate']:
  record['metrics'][arm]={}
  for posted in [0,4]:
   name=f'm2048-p{posted}';expected=old['arms'][arm][name]['fir_sha256']
   options=sorted(oldout.parent.glob(f'*/{arm}/matrix/{name}/EthernetPacketDma.fir'))
   matches=[p for p in options if sha(p)==expected and (p.parent/(arm+'-'+name)).is_file()
    and sha(p.parent/(arm+'-'+name))==old['arms'][arm][name]['binary_sha256']]
   assert matches,(arm,name)
   directory=matches[-1].parent
   sources=sorted(p for p in directory.glob('*.cpp') if re.fullmatch(r'EthernetPacketDma\d+\.cpp',p.name))
   assert sources
   # Record the retained translation units/headers alongside the qualified FIR.
   # No model generation or vendor rebuild occurs in this supplemental run.
   record['models'][arm+'-'+name]=dict(fir=str(directory/'EthernetPacketDma.fir'),fir_sha256=expected,
    generated_files={p.name:sha(p) for p in sorted(directory.iterdir()) if p.suffix in ['.cpp','.h']})
   binary=out/(arm+'-'+name)
   cmd=['clang++-19','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
    '-DDMA_MAX_FRAME=2048','-DTX_POSTED_SLOTS='+str(posted),'-DDMA_RAM_BYTES=65536ULL',
    '-DDMA_HOST_MEMORY_BYTES=65536','-DDMA_RAM_BASE=0x80200000ULL','-I'+str(directory),
    '-I'+str(r/'simulator/gsim/harness'),*sources,r/'simulator/gsim/harness/dma_tx_word_count.cpp','-ldl','-o',binary]
   run(arm+'-'+name+'-compile',cmd)
   text=run(arm+'-'+name+'-positive',[binary,'--review-gaps'],anchor='TX_WORD_COUNT_REVIEW_GAPS_PASS')
   metrics=[s for s in text.splitlines() if s.startswith('TX_WORD_COUNT_METRICS ')]
   assert len(metrics)==(9 if posted else 6)
   record['metrics'][arm][name]=metrics;save()
   for mutation,anchor in [('busy-address','busy legacy descriptor/status changed'),('busy-length','busy legacy descriptor/status changed'),
     ('busy-start','busy legacy descriptor/status changed')]+([('boundary','posted exact TLAST byte offset mismatch'),
     ('controls','illegal posted descriptor side effects')] if posted else []):
    run(arm+'-'+name+'-negative-'+mutation,[binary,'--review-gaps','--mutate='+mutation],1,anchor)
 assert record['metrics']['baseline']==record['metrics']['candidate'],'review A/B metrics differ'
 record.update(status='PASS_DMA_REVIEW_GAPS_AND_REUSE_GUARDS',positive_scenarios_per_arm=15,
  expected_driver_failures_per_arm=8,expected_guard_failures=8,exact_ab_metrics=True)
 save();print(json.dumps({k:v for k,v in record.items() if k not in ['commands','models','metrics']},indent=2))
except BaseException as e:
 record.update(status='FAILED_PRESERVE_EVIDENCE',error=str(e));save();raise
