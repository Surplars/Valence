#!/usr/bin/env python3
"""Focused source-pinned TX count A/B; fixed GSIM, no PHY/CPU/full regression/Vivado."""
import argparse,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--baseline-root',type=Path,required=True)
 ap.add_argument('--output',type=Path,required=True)
 ap.add_argument('--gsim',type=Path,required=True)
 ap.add_argument('--reuse-baseline',type=Path)
 a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);base=a.baseline_root.resolve()
 os.nice(10)
 env={**os.environ,'JAVA_TOOL_OPTIONS':'-XX:ActiveProcessorCount=2','ASAN_OPTIONS':'detect_leaks=0',
  'UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1','PYTHONDONTWRITEBYTECODE':'1'}
 roots={'baseline':base,'candidate':ROOT}
 extra=['simulator/gsim/harness/ethernet_packet_dma.cpp','simulator/gsim/harness/dma_tx_word_count.cpp',
  'simulator/gsim/harness/dma_packet_stop.cpp','simulator/gsim/harness/dma_coherent_ddr.h']
 def inputs(root):
  return {str(p.relative_to(root)):sha(p) for p in [*root.glob('src/**/*.scala'),*[root/n for n in extra]]}
 frozen={arm:inputs(root) for arm,root in roots.items()}
 differing=[n for n,h in frozen['baseline'].items() if h!=frozen['candidate'].get(n)]
 assert differing==['src/main/scala/ip/dma/EthernetPacketDma.scala'],differing
 assert subprocess.check_output(['git','diff','--name-only','--','src/main/scala'],cwd=base,text=True)==''
 receipt=dict(status='RUNNING',source_inputs=frozen,source_production_difference=differing,
  gsim_sha256=sha(a.gsim),runner_sha256=sha(Path(__file__)),commands=[],arms={},comparison={},
  scope='direct DMA and existing four-case packet STOP/coherent copy fixture only; no whole CPU, PHY, CDC, Linux or physical qualification',
  physical_results=False)
 reused=None
 if a.reuse_baseline:
  reused=json.loads((a.reuse_baseline/'receipt.json').read_text())
  for arm in roots:
   assert {n:h for n,h in reused['source_inputs'][arm].items() if n.startswith('src/')}=={
    n:h for n,h in frozen[arm].items() if n.startswith('src/')},'RTL or fixture changed; cannot reuse'
  ancestor=reused;ancestor_path=a.reuse_baseline/'receipt.json';chain=[]
  for _ in range(8):
   chain.append(dict(path=str(ancestor_path),sha256=sha(ancestor_path)))
   for arm in roots:
    assert {n:h for n,h in ancestor['source_inputs'][arm].items() if n.startswith('src/')}=={
     n:h for n,h in frozen[arm].items() if n.startswith('src/')}
   if any(c['label']=='scala-configuration' and c['exit']==0 for c in ancestor['commands']):break
   expected=ancestor['reused_prior_receipt_sha256']
   ancestor_path=next(p for p in a.reuse_baseline.parent.glob('*/receipt.json') if sha(p)==expected)
   ancestor=json.loads(ancestor_path.read_text())
  else:raise AssertionError('missing source-identical successful Scala configuration ancestry')
  receipt['scala_qualification_receipt_chain']=chain
  receipt['reused_prior_receipt_sha256']=sha(a.reuse_baseline/'receipt.json')
  receipt['prior_failure_preserved']=reused.get('failure','')
 def save():(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 def run(label,cmd,cwd=ROOT,expected=0,anchor=None):
  assert all(inputs(root)==frozen[arm] for arm,root in roots.items()),'source drift'
  start=time.monotonic();log=out/(label+'.log')
  with log.open('x') as h:p=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,stdout=h,stderr=subprocess.STDOUT,timeout=2400)
  text=log.read_text(errors='replace')
  receipt['commands'].append(dict(label=label,exit=p.returncode,seconds=round(time.monotonic()-start,3),log_sha256=sha(log)));save()
  if p.returncode!=expected or (anchor and anchor not in text):raise RuntimeError(label+'\n'+text[-5000:])
  print(label,'PASS',flush=True);return text
 def mill(label,root,main,*args):return run(label,['mill','-i','-j','2','IonSoC.test.runMain',main,*args],cwd=root)
 def build(label,directory,top,driver,defines):
  sources=sorted(p for p in directory.glob('*.cpp') if re.fullmatch(re.escape(top)+r'\d+\.cpp',p.name))
  assert sources
  flags=['clang++-19','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
   *['-D'+k+'='+str(v) for k,v in defines.items()],'-I'+str(directory),'-I'+str(ROOT/'simulator/gsim/harness')]
  binary=directory/label
  run(label+'-compile',[*flags,*sources,ROOT/'simulator/gsim/harness'/driver,'-ldl','-o',binary]);return binary
 save()
 try:
  if not reused:run('scala-configuration',['mill','-i','-j','2','IonSoC.test.testOnly','ip.EthernetPacketDmaSpec','ip.DmaParamsSpec'])
  configs=[(f'm{m}-p{p}',m,p,0x80200000) for m in [64,128,256,512,1024,2048,4096,8192,16384] for p in [0,4]]
  configs.append(('m2048-p4-high',2048,4,0x100200000))
  for arm,root in roots.items():
   if arm=='baseline' and reused and reused['source_inputs']['baseline']==frozen['baseline'] and set(reused['arms'].get('baseline',{}))=={c[0] for c in configs}|{'stop'}:
    rows=json.loads(json.dumps(reused['arms']['baseline']));receipt['arms'][arm]=rows
    logs={}
    for cmd in reused['commands']:
     if cmd['label'].startswith('baseline-') and cmd['label'].endswith('-test') and cmd['exit']==0:
      p=a.reuse_baseline/(cmd['label']+'.log');assert sha(p)==cmd['log_sha256'];logs[str(p)]=sha(p)
    assert len(logs)==22,len(logs)
    for name,_,_,_ in configs:
     p=a.reuse_baseline/'baseline/matrix'/name
     assert sha(p/'EthernetPacketDma.fir')==rows[name]['fir_sha256']
     assert sha(p/('baseline-'+name))==rows[name]['binary_sha256']
    stop=a.reuse_baseline/'baseline/stop';binary=stop/'baseline-stop'
    assert sha(binary)==rows['stop']['binary_sha256'] and sha(stop/'DmaPacketStopGsim.fir')==rows['stop']['fir_sha256']
    receipt['source_identical_baseline_positive_logs_reused']=logs;save()
    direct=a.reuse_baseline/'baseline/matrix/m2048-p4/baseline-m2048-p4'
    run('baseline-byte-negative',[direct,'--corrupt-expected'],expected=1,anchor='TX word count independent byte oracle mismatch')
    for mutation,anchor in [('tx-byte','packet TX independent generation byte oracle mismatch'),('rx-byte','CPU independent cache byte oracle mismatch'),
     ('stale-owner','packet completion generation/owner oracle mismatch')]:
     run('baseline-stop-negative-'+mutation,[binary,'--mutate='+mutation],expected=1,anchor=anchor)
    print('BASELINE_POSITIVES_REUSED_EXACT_SOURCE_LOG_FIR_BINARY_HASHES',flush=True)
    continue
   matrix=out/arm/'matrix'
   if arm=='baseline' and reused:
    old=a.reuse_baseline/'baseline/matrix';matrix.mkdir(parents=True)
    cached={}
    for source in old.rglob('*'):
     if source.is_file() and source.suffix in ['.fir','.h','.cpp','.json']:
      target=matrix/source.relative_to(old);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
      assert sha(target)==sha(source);cached[str(source.relative_to(old))]=sha(source)
    receipt['reused_baseline_model_material_sha256']=cached;save()
   else:mill(arm+'-matrix-emit',root,'ip.DmaTxWordCountGsimMain',matrix)
   rows={};receipt['arms'][arm]=rows;save()
   for name,m,posted,ram_base in configs:
    d=matrix/name;fir=d/'EthernetPacketDma.fir'
    graph=['--dump-json','--dump-assign-tree','--dump-stages=AfterSplitNodes,AliasAnalysis'] if name=='m2048-p4' else []
    if not (d/'EthernetPacketDma0.cpp').exists():run(arm+'-'+name+'-generate',[a.gsim,'--threads=1',*graph,'--dir='+str(d),fir])
    defines=dict(DMA_MAX_FRAME=m,TX_POSTED_SLOTS=posted,DMA_RAM_BYTES='65536ULL',
     DMA_HOST_MEMORY_BYTES=65536,DMA_RAM_BASE=hex(ram_base)+'ULL')
    binary=build(arm+'-'+name,d,'EthernetPacketDma','dma_tx_word_count.cpp',defines)
    text=run(arm+'-'+name+'-test',[binary],anchor='TX_WORD_COUNT_FOCUSED_PASS')
    metrics=[l for l in text.splitlines() if l.startswith('TX_WORD_COUNT_METRICS ')]
    assert len(metrics)==(28 if posted else 25),(name,len(metrics))
    fir_text=fir.read_text();reg=re.search(r'regreset txWordCount : UInt<(\d+)>',fir_text)
    assert bool(reg)==(arm=='candidate')
    if reg:assert int(reg.group(1))==(m//8).bit_length()
    rows[name]=dict(metrics=metrics,cases=len(metrics),fir_sha256=sha(fir),binary_sha256=sha(binary),
     count_register_bits=int(reg.group(1)) if reg else 0)
    save()
    if name in ['m2048-p0','m2048-p4']:
     original=build(arm+'-'+name+'-original',d,'EthernetPacketDma','ethernet_packet_dma.cpp',defines)
     original_text=run(arm+'-'+name+'-original-test',[original],anchor='ETHERNET_PACKET_DMA_PASS')
     rows[name]['original_oracle_metrics']=[l for l in original_text.splitlines() if '_PASS ' in l]
    if name=='m2048-p4':
     run(arm+'-byte-negative',[binary,'--corrupt-expected'],expected=1,anchor='TX word count independent byte oracle mismatch')
   stop=out/arm/'stop';mill(arm+'-stop-emit',root,'ooo.DmaPacketStopGsimMain',stop,'0','1')
   run(arm+'-stop-generate',[a.gsim,'--threads=1','--dir='+str(stop),stop/'DmaPacketStopGsim.fir'])
   binary=build(arm+'-stop',stop,'DmaPacketStopGsim','dma_packet_stop.cpp',dict(DMA_LINE_ENTRIES=1,DMA_LINE_YIELD_CYCLES=0))
   text=run(arm+'-stop-test',[binary],anchor='DMA_PACKET_STOP_LINE_PASS cases=4')
   rows['stop']=dict(metrics=[l for l in text.splitlines() if l.startswith('PACKET_LINE_CASE ')],
    fir_sha256=sha(stop/'DmaPacketStopGsim.fir'),binary_sha256=sha(binary))
   assert len(rows['stop']['metrics'])==4
   for mutation,anchor in [('tx-byte','packet TX independent generation byte oracle mismatch'),('rx-byte','CPU independent cache byte oracle mismatch'),
    ('stale-owner','packet completion generation/owner oracle mismatch')]:
    run(arm+'-stop-negative-'+mutation,[binary,'--mutate='+mutation],expected=1,anchor=anchor)
  for name,row in receipt['arms']['baseline'].items():
   candidate=receipt['arms']['candidate'][name]
   assert row['metrics']==candidate['metrics'],('A/B cycle/request/response mismatch',name)
   if 'original_oracle_metrics' in row:assert row['original_oracle_metrics']==candidate['original_oracle_metrics']
  receipt['comparison']=dict(exact_metrics_equal=True,matrix_models_per_arm=19,
   direct_scenarios_per_arm=sum(v['cases'] for v in receipt['arms']['candidate'].values() if 'cases' in v),
   stop_scenarios_per_arm=4,byte_and_stop_negatives_per_arm=4,
   new_count_bits_by_max_frame={str(m):(m//8).bit_length() for m in [64,128,256,512,1024,2048,4096,8192,16384]},
   default_new_register_bits=9,mapped_area_timing='NOT_MEASURED; register-bit estimate only')
  receipt['status']='PASS_FOCUSED_TX_WORD_COUNT_AB_AND_STOP';save();print(json.dumps(receipt['comparison'],indent=2),flush=True)
 except BaseException as e:
  receipt.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
if __name__=='__main__':main()
