import argparse,contextlib,hashlib,importlib.util,io,json,sys,tempfile,traceback
from pathlib import Path
from unittest.mock import patch
parser=argparse.ArgumentParser()
parser.add_argument('--source-root',type=Path,required=True)
parser.add_argument('--report',type=Path,required=True)
args=parser.parse_args()
ROOT=args.source_root.resolve()
HERE=ROOT/'fpga/next'; LOG=args.report.resolve()
def load(n):
 s=importlib.util.spec_from_file_location('gate_'+n,HERE/(n+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
checks=[]
def checked(name,f):
 f();checks.append(name);print('PASS',name)
def rejected(f):
 try:f()
 except (RuntimeError,SystemExit,ValueError):return
 raise AssertionError('negative accepted')
old=load('board_near_term_a'); exact=load('board_timing64');new=load('board_near_term_a_raw_handoff');export=load('export')
a=old.load_profile();r=exact.load_profile();n=new.load_profile()
checked('existing_A_OFF_exact_68_and_exact64_64',lambda: (_ for _ in ()).throw(AssertionError()) if not(len(a['native_options'])==68 and len(r)==64 and '--tri-speed-raw-clock-handoff' not in a['native_options']) else None)
assert n['native_options']==a['native_options']+['--tri-speed-raw-clock-handoff'];checks.append('new_ON_exact_69')
flag='--tri-speed-raw-clock-handoff'
def preflight(args):
 with tempfile.TemporaryDirectory() as t,patch.object(export.subprocess,'check_output',return_value='767e7683f3d6f5bd1fee257735505b353500d2a5\n'),patch.object(export.subprocess,'run',side_effect=AssertionError('no process execution')),contextlib.redirect_stdout(io.StringIO()) as o:
  export.main(['--output',str(Path(t)/'out'),*args]);return json.loads(o.getvalue())
options=[x for x in a['native_options'] if x!='--selected']
off=preflight(options+a['physical_options']);on=preflight(options+[flag]+a['physical_options'])
assert flag not in off['command'] and on['command'].count(flag)==1
assert off['configuration'].get('tri_speed_raw_clock_handoff',False)==False and on['configuration']['tri_speed_raw_clock_handoff']==True
checks.append('actual_export_preflight_native_flag_and_profile')
for label,args in [('no_tri_speed',[flag]),('duplicate',options+[flag,flag]),('true_value',options+[flag+'=true']),('false_value',options+[flag+'=false']),('abbreviation',options+['--tri-speed-raw-clock-hand'])]:
 with contextlib.redirect_stderr(io.StringIO()): rejected(lambda:preflight(args))
 checks.append(label+'_rejected')
# Exercise actual emit resource admission/filelist, while stubbing external compiler,
# wrapper-port/device staging and Git identity. This certifies exporter logic only.
def emitted(on,missing=False):
 with tempfile.TemporaryDirectory() as t:
  out=Path(t)/'out'; rtl=out/'rtl'
  def fake_run(command,**kwargs):
   rtl.mkdir();(rtl/'ValenceJtagDebugPort.sv').write_text('module ValenceJtagDebugPort; endmodule\n');(rtl/'ValenceBscanDebugPort.sv').write_text('module ValenceBscanDebugPort; endmodule\n');(rtl/'FpgaNextSocTop.sv').write_text('module FpgaNextSocTop; endmodule\n');(rtl/'filelist.f').write_text('FpgaNextSocTop.sv\n')
   # These literal constructor fixtures test exporter admission only; no DUT is emitted.
   profile=json.loads((HERE/'near-term-a-before-mac-platform.json').read_text())
   profile['core']['postedYoungerLoadSealDeferral']=False
   profile['core']['heldAluIssueForwarding']=False
   profile['core']['residentMemoryPayloadReuse']=False
   profile['profile']['triSpeedRawClockHandoff']=on
   profile['profile']['postedYoungerLoadSealDeferral']=False
   profile['profile']['heldAluIssueForwarding']=False
   profile['profile']['residentMemoryPayloadReuse']=False
   (rtl/'profile.json').write_text(json.dumps(profile))
   (rtl/'actual-held-alu-forwarding.json').write_text(json.dumps({
       'heldAluIssueForwarding':False,'core':profile['core'],'backend':profile['core'],'ledger':profile['core']}))
   resident=json.loads((HERE/'resident-memory-source-compat.json').read_text())
   (rtl/'actual-resident-memory.json').write_text(json.dumps({
       'schema':'actual-resident-memory-integration-v1','scope':'actual-constructor-only',
       'residentMemoryPayloadReuse':False,'residentMemoryStartAllowed':False,
       'residentSelectorCount':0,'ordinarySelectorCount':1,'residentSelectorClasses':[],
       'core':profile['core'],'backend':profile['core'],'ledger':profile['core'],
       'coreNames':resident['current_core_names'],'profileNames':resident['current_profile_names'],
       'coreFields':175,'profileFields':92,'executionStages':2,'memoryEntries':4,
       'dynamicQualification':False,'physicalQualification':False}))
   if on and not missing:(rtl/'ValenceMacRawFallingSample.sv').write_bytes((ROOT/'src/main/resources/ethernet/ValenceMacRawFallingSample.sv').read_bytes())
   return type('Result',(),{'returncode':0})()
  with patch.object(export.subprocess,'check_output',return_value='767e7683f3d6f5bd1fee257735505b353500d2a5\n'),patch.object(export.subprocess,'run',side_effect=fake_run),patch.object(export,'check_wrapper_ports',return_value=['STUB_NOT_PORT_QUALIFICATION']),patch.object(export.media_integration,'stage',return_value={'scope':'STUB'}),patch.object(export.board_t1,'stage',return_value={'scope':'STUB'}),patch.object(export.bscan_integration,'stage',return_value={'scope':'STUB'}),contextlib.redirect_stdout(io.StringIO()):
   export.main(['--output',str(out),'--emit',*options,*([flag] if on else [])])
  listed=(out/'synthesis-files.f').read_text();receipt=json.loads((out/'receipt.json').read_text())
  assert ('ValenceMacRawFallingSample.sv' in listed)==on and receipt['tri_speed_raw_clock_handoff']==on
emitted(False);checks.append('OFF_resource_absent_stubbed_emit')
emitted(True);checks.append('ON_resource_required_and_listed_stubbed_emit')
rejected(lambda:emitted(True,True));checks.append('ON_missing_resource_rejected')
# Bind source failure by overriding only module SHA reader, not candidate files.
real_sha=hashlib.sha256
config_bytes=(ROOT/'src/main/scala/core/ooo/FpgaNextConfig.scala').read_bytes()
class ChangedLeafHash:
 def hexdigest(self):return '0'*64
with patch.object(hashlib,'sha256',side_effect=lambda data:ChangedLeafHash() if data==config_bytes else real_sha(data)):
 rejected(new.load_profile)
checks.append('new_source_hash_drift_rejected')
bridge=load('resident_memory_source_bridge'); real=bridge.hashlib.sha256
class BadHash:
 def hexdigest(self):return '0'*64
with patch.object(bridge.hashlib,'sha256',return_value=BadHash()):rejected(bridge.checked_sources)
checks.append('OFF_compat_manifest_drift_rejected')
LOG.write_text(json.dumps({'status':'PASS_BOUNDED_PYTHON_HOST_ENTRY','checks':checks,'count':len(checks),'external_processes_executed':False,'fake_rtl_scope':'resource/filelist exporter only; no port or device qualification'},indent=2)+'\n')
print('PASS_TOTAL',len(checks))
