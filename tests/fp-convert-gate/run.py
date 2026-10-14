#!/usr/bin/env python3
"""Standalone FP component gate. Build dependencies with the repository's pinned build first."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('gate',choices=['convert','misc','tag64']);p.add_argument('--out',required=True,type=Path)
p.add_argument('--classpath',help='Fresh same-checkout production, HardFloat, Scala compiler/runtime and Chisel jars, OS path separator delimited')
p.add_argument('--plugin',type=Path,help='Pinned Chisel Scala compiler plugin jar')
p.add_argument('--java',default='java');p.add_argument('--firtool',default='firtool');p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp')
p.add_argument('--reuse-rtl',type=Path,help='Explicit already-qualified RTL directory; skips Scala compilation/emission, hashes all reused RTL')
p.add_argument('--vectors',type=Path,help='Explicit existing deterministic vector file; otherwise regenerate')
p.add_argument('--negative',action='store_true',help='Run candidate-only generated-copy mutation controls after positive test')
a=p.parse_args();here=Path(__file__).resolve().parent;out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
receipt={'gate':a.gate,'status':'RUNNING','full_cpu':False,'synthesis':False,'reuse_rtl':bool(a.reuse_rtl),'commands':[]};sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
def run(cmd,name,negative=False,needle=''):
 r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,env=os.environ,timeout=240);s=r.stdout+r.stderr;(out/(name+'.log')).write_text(s);receipt['commands'].append({'argv':list(map(str,cmd)),'returncode':r.returncode,'log':name+'.log'})
 if negative:
  assert r.returncode!=0 and needle in s and 'ORACLE_BASELINE_MISMATCH' not in s,s
 else:assert r.returncode==0,s
 return s
try:
 fixture=here/'tag64' if a.gate=='tag64' else here
 tb=fixture/('convert_tb.sv' if a.gate=='convert' else 'misc_tb.sv');top='convert_tb' if a.gate=='convert' else 'misc_tb'
 sources=[here/'ConvertHarness.scala'] if a.gate=='convert' else [here/'FloatingPointMiscBaseline.scala',fixture/'MiscHarness.scala']
 if a.reuse_rtl:rtl=a.reuse_rtl.resolve();assert rtl.is_dir()
 else:
  assert a.classpath and a.plugin,'--classpath and --plugin required unless --reuse-rtl is explicit'
  classes=out/'classes';classes.mkdir();rtl=out/'rtl';rtl.mkdir()
  run([a.java,'-Xmx2g','-XX:ActiveProcessorCount=2','-cp',a.classpath,'scala.tools.nsc.Main','-language:reflectiveCalls','-Xplugin:'+str(a.plugin.resolve()),'-classpath',a.classpath,'-d',classes,*sources],'scala')
  ft=shutil.which(a.firtool) or a.firtool;assert Path(ft).is_file(),'firtool executable unavailable';os.environ['CHISEL_FIRTOOL_PATH']=str(Path(ft).resolve().parent)
  run([a.java,'-Xmx2g','-XX:ActiveProcessorCount=2','-cp',str(classes)+os.pathsep+a.classpath,'soc.core.ooo.'+('ConvertEmit' if a.gate=='convert' else 'MiscEmit'),rtl],'emit')
  if a.gate=='convert':rtl=rtl/'harness'
 sv=sorted(rtl.glob('*.sv'));assert sv,'no RTL files';receipt['rtl_sha256']={x.name:sha(x) for x in sv}
 vectors=None
 if a.gate!='tag64':
  vectors=a.vectors.resolve() if a.vectors else out/'vectors/tests/vectors.txt'
  if not a.vectors:run([sys.executable,here/'make_vectors.py',out/'vectors'],'vectors')
  assert vectors.is_file();receipt['vectors_sha256']=sha(vectors)
 def simulate(files,label,negative=False,needle=''):
  binary=out/(label+'.vvp');run([a.iverilog,'-g2012','-s',top,'-o',binary,*files,tb],label+'-compile')
  return run([a.vvp,binary]+(['+vectors='+str(vectors)] if vectors else []),label,negative,needle)
 print(simulate(sv,'positive'))
 if a.negative:
  assert a.gate!='misc','Use convert and tag64 negative gates; misc16 has no additional mutation'
  mutations=['truncate_without_clip','nx_not_suppressed'] if a.gate=='convert' else ['truncate_tag64']
  for mutation in mutations:
   d=out/mutation;d.mkdir();changes=0
   for f in sv:
    s=f.read_text();old=s
    if a.gate=='convert' and f.name.startswith('FloatingPointToIntegerShared_'):
     if mutation=='truncate_without_clip':s,n=re.subn(r'assign io_out32 =.*?;','assign io_out32 = _wide_io_out[31:0];',s,flags=re.S);assert n==1
     else:target='~invalid32 & _wide_io_intExceptionFlags[0]';assert s.count(target)==1;s=s.replace(target,'_wide_io_intExceptionFlags[0]')
    elif mutation=='truncate_tag64' and f.name=='MiscHarness.sv':
     target='.io_request_bits_command_token_tag     (io_token)';assert s.count(target)==4;s=s.replace(target,".io_request_bits_command_token_tag     ({48'b0,io_token[15:0]})",2)
    if old!=s:changes+=1
    (d/f.name).write_text(s)
   assert changes==(2 if a.gate=='convert' else 1),'emitter pattern changed; review mutation instead of weakening it'
   simulate(sorted(d.glob('*.sv')),mutation,True,'CANDIDATE_MISMATCH' if a.gate=='convert' else 'OWNER_CHANGED')
 receipt['status']='PASS_COMPONENT_REUSED_RTL' if a.reuse_rtl else 'PASS_FRESH_COMPONENT'
 receipt['fixtures_sha256']={str(x.relative_to(here)):sha(x) for x in [*sources,tb,here/'make_vectors.py']}
except Exception as e:receipt.update(status='FAIL',error=str(e));raise
finally:(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
