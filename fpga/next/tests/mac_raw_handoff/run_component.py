from pathlib import Path
import argparse,datetime,hashlib,json,subprocess,time,resource,shutil,os,sys
parser=argparse.ArgumentParser(description="Focused native MAC lifecycle gate; digital BUFGCE model, no physical qualification")
parser.add_argument('--rtl-on',type=Path,required=True)
parser.add_argument('--rtl-off',type=Path,required=True)
parser.add_argument('--baseline-rtl',type=Path)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--iverilog',type=Path)
parser.add_argument('--vvp',type=Path)
parser.add_argument('--prepare-only',action='store_true')
args=parser.parse_args()
R=args.output.resolve(); assert not R.exists(),"fresh work directory required"
R.mkdir(parents=True); (R/'tests').mkdir()
HERE=Path(__file__).resolve().parent
for n in ('mac_handoff_tb.sv','mac_ports.svh','BUFGCE.sv','prepare_native.py','audit_simulation_bridge.py'):
 shutil.copy2(HERE/n,R/'tests'/n)
for name,path in [('rtl-on',args.rtl_on),('rtl-off',args.rtl_off)]+([('rtl-baseline',args.baseline_rtl)] if args.baseline_rtl else []):
 assert path.is_dir(),str(path); (R/name).mkdir()
 for p in path.glob('*.sv'): shutil.copy2(p,R/name/p.name)
 assert list((R/name).glob('*.sv')),"missing RTL"
subprocess.run([sys.executable,str(R/'tests/prepare_native.py')],check=True)
subprocess.run([sys.executable,str(R/'tests/audit_simulation_bridge.py')],check=True)
assert (R/'tests/mac_ports.svh').read_bytes()==(HERE/'mac_ports.svh').read_bytes(),"component interface drift"
if args.prepare_only:
 print('PASS_PORTABLE_PREPARATION_ONLY');sys.exit(0)
assert args.iverilog and args.vvp,"provide both explicit Icarus executable paths"
IVERILOG=args.iverilog.resolve(); VVP=args.vvp.resolve()
assert IVERILOG.is_file() and VVP.is_file()
O=R/'results'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');O.mkdir(parents=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
receipt={'status':'RUNNING','base_commit':'767e7683f3d6f5bd1fee257735505b353500d2a5','results':[],'physical_qualification':False,'vendor_primitive_models':False,'simulator':'Icarus native SystemVerilog','simulation_adaptations':json.loads((R/'tests/simulation-adaptations.json').read_text()),'input_sha256':{str(p.relative_to(R)):sha(p) for p in sorted((R/'tests').glob('*')) if p.is_file()} ,'rtl_sha256':{p.name:sha(p) for p in sorted((R/'rtl-on').glob('*.sv'))}}

def save(): (O/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
def run(label,argv,timeout=60):
 start=time.monotonic();before=resource.getrusage(resource.RUSAGE_CHILDREN)
 with (O/(label+'.log')).open('w') as f:
  p=subprocess.Popen(list(map(str,argv)),cwd=R,stdout=f,stderr=subprocess.STDOUT)
  receipt['active_process']={'label':label,'pid':p.pid};save();rc=p.wait(timeout=timeout)
 after=resource.getrusage(resource.RUSAGE_CHILDREN);text=(O/(label+'.log')).read_text()
 receipt['results'].append({'name':label,'exit':rc,'seconds':time.monotonic()-start,'user_s':after.ru_utime-before.ru_utime,'system_s':after.ru_stime-before.ru_stime,'max_rss_kib':after.ru_maxrss,'argv':list(map(str,argv)),'log_sha256':sha(O/(label+'.log'))})
 save();return rc,text

def simulate(label,files,marker=None):
 binary=O/(label+'.vvp');rc,text=run(label+'-compile',[IVERILOG,'-g2012','-I',R/'tests','-s','mac_handoff_tb','-o',binary,R/'tests/BUFGCE.sv',*files,R/'tests/mac_handoff_tb.sv'])
 assert rc==0,label+' compile failed'
 rc,text=run(label+'-simulate',[VVP,binary]);print(label,rc,text[-2000:],flush=True)
 if marker:assert rc!=0 and marker in text and 'MAC_HANDOFF_LIFECYCLE_PASS' not in text,label+' negative did not reject'
 else:assert rc==0 and 'MAC_HANDOFF_LIFECYCLE_PASS' in text,label+' failed'
 receipt['results'][-1]['expected_outcome']='negative_rejected' if marker else 'PASS';save()
try:
 files=sorted((R/'simulation-rtl').glob('*.sv'));simulate('positive',files)
 controls={
  'missing-pending':('TriSpeedManagedGmac.sv','& ~_rxConfig_destination_valid & _ingress_empty & ~_rawHandoff_rxPending','& ~_rxConfig_destination_valid & _ingress_empty','ACK_OWNER_ORACLE'),
  'rx-extra-edge':('MacRawHandoff.sv','reg  [10:0] managed;','reg [10:0] extra;\n  always @(posedge rxClock or posedge rxReset) if(rxReset) extra<=0; else extra<=_falling_sampled[10:0];\n  reg  [10:0] managed;','RX_ENABLED_EDGE_ORACLE'),
  'rx-step-misaligned':('TriSpeedManagedGmac.sv','.io_byteStep        (_rawHandoff_rxPayload[10])','.io_byteStep        (_ingress_delayed[10])','RX_ENABLED_EDGE_ORACLE'),
  'tx-extra-edge':('MacRawHandoff.sv','assign txByteStep = _falling_sampled[11];','reg txExtra; always @(posedge rawClock or posedge rawReset) if(rawReset) txExtra<=0; else txExtra<=_falling_sampled[11];\n  assign txByteStep = txExtra;','TX_EPOCH_ORACLE')}
 for label,(name,old,new,marker) in controls.items():
  directory=O/label;directory.mkdir();original=(R/'simulation-rtl'/name).read_text();assert original.count(old)==1,(label,'mutation anchor')
  mutated=original.replace(old,new)
  if label=='rx-extra-edge':mutated=mutated.replace('managed <= _falling_sampled[10:0];','managed <= extra;')
  path=directory/name;path.write_text(mutated);simulate(label,[path if p.name==name else p for p in files],marker)
 # Clock-edge audit is deliberately separate from functional simulation.
 # Zero-delay functional models cannot certify same-edge physical hold safety.
 sample=(R/'rtl-on/ValenceMacRawFallingSample.sv').read_text();handoff=(R/'rtl-on/MacRawHandoff.sv').read_text();top=(R/'rtl-on/TriSpeedManagedGmac.sv').read_text()
 def clock_audit(sample,handoff):
  assert 'always @(negedge rawClock or posedge rawReset)' in sample,'FALLING_CLOCK_STRUCTURE'
  assert 'else sampled <= payload;' in sample and 'output reg [11:0] sampled' in sample,'FALLING_REGISTER_STRUCTURE'
  assert 'always @(posedge rxClock or posedge rxReset)' in handoff,'MANAGED_REGISTER_STRUCTURE'
  assert 'managed <= _falling_sampled[10:0];' in handoff,'FALLING_NOT_BYPASSED'
  assert '.rawClock (rawClock)' in handoff and '~rawClock' not in handoff+sample,'NO_LOGIC_CLOCK_INVERTER'
 clock_audit(sample,handoff)
 rejected=0
 for label,s,h in [('positive-edge-shadow',sample.replace('negedge rawClock','posedge rawClock'),handoff),('shadow-bypass',sample,handoff.replace('managed <= _falling_sampled[10:0];','managed <= rawRxPayload;'))]:
  try:clock_audit(s,h)
  except AssertionError as e:receipt['results'].append({'name':label,'expected_outcome':'structural_negative_rejected','marker':str(e)});rejected+=1
 assert rejected==2
 if args.baseline_rtl:
  off={p.name:sha(p) for p in (R/'rtl-off').glob('*.sv')};base={p.name:sha(p) for p in (R/'rtl-baseline').glob('*.sv')};assert len(off)==44 and off==base,'DEFAULT_OFF_DIFF'
  receipt['default_off']={'status':'BYTE_IDENTICAL','files':len(off),'baseline':'explicit immutable pre-change component RTL','sha256':off}
 else:
  receipt['default_off']={'status':'NOT_REPEATED_NO_BASELINE_INPUT','historical_receipt_sha256':'7ffb960c4c5174874259f29800826af9999f1247d13b63b6af2476e2d3bf216f'}
 receipt['structure']={'falling_raw_bits':12,'managed_rx_positive_bits':11,'source_clock_inversion_rtl':'real negedge; no LUT clock','device_ff_mapping_verified':False,'physical_timing_verified':False}
 receipt['status']='PASS_FOCUSED_NATIVE_MAC_LIFECYCLE'
except BaseException as e:receipt['status']='FAIL';receipt['error']=str(e);raise
finally:
 receipt.pop('active_process',None);save();print('RECEIPT',O/'receipt.json',flush=True)
