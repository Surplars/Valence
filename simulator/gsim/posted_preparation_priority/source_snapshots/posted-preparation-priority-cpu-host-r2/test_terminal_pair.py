"""Small result-inheritance and input-binding mutations, without a DUT."""
import copy,hashlib,json,tempfile
from pathlib import Path
import pair
from contract import *

def main():
 controls=[]
 def reject(name,fn,reason):
  try:fn()
  except RuntimeError as e:
   assert reason in str(e),(name,str(e));controls.append(dict(name=name,status='REJECTED',reason=str(e)))
  else:raise AssertionError('escaped '+name)
 r=dict(schema='posted-preparation-priority-cpu-case-v1',status='SCOPED_PASS_WITH_BOUNDARY_JOIN_UNKNOWN',side='on',case=21,new_execution=True,guest_changed=False,steps=[dict(exit=x,expected=x,guard=None)for x in(0,0,1)],checks={k:'PASS'for k in pair.ORACLES})
 pair.identity(r,'on',21)
 bad=copy.deepcopy(r);bad['side']='off';reject('wrong_side',lambda:pair.identity(bad,'on',21),'identity mismatch')
 bad=copy.deepcopy(r);bad['steps'].pop();reject('missing_trap_negative',lambda:pair.identity(bad,'on',21),'trap negative missing')
 bad=copy.deepcopy(r);bad['checks'].pop('fault_trap_CSR_SP_GP');reject('missing_fault_oracle',lambda:pair.identity(bad,'on',21),'oracle missing')
 with tempfile.TemporaryDirectory()as d:
  folder=Path(d)
  names={f'{prefix}.{name}.jsonl'for prefix in('positive','trap-negative')for name in pair.run.TRACE_ENV.values()}|{'positive.window.jsonl.lifetimes.jsonl'}
  for n in names:(folder/n).write_text('{}\n')
  art={'artifacts':{n:sha(folder/n)for n in names}};pair.artifacts(art,folder)
  p=folder/'positive.proof.jsonl';p.write_text('{"changed":true}\n');reject('changed_raw',lambda:pair.artifacts(art,folder),'artifact drift');p.write_text('{}\n')
  p.unlink();bad=copy.deepcopy(art);bad['artifacts'].pop(p.name);reject('missing_required_trace',lambda:pair.artifacts(bad,folder),'required raw trace missing')
 with tempfile.TemporaryDirectory()as d:
  folder=Path(d);path=folder/'validation.resources.json';q=dict(stage='validate',out=str(folder),side='on',case=21,measurement=str(path));raw=json.dumps(q)
  vals={k:{}for k in pair.VALIDATION_KEYS};vals['proof_trace']={'histograms':{1:3,10:2,2:1},'unknown':[]}
  record=json.loads(json.dumps(vals));resources={'fresh_process':True};pins={'base':{'files':{n:'f'*64 for n in pair.PARSERS}}}
  m=dict(status='PASS',stage='validate',actual_request=q,actual_stdin_text=raw,actual_stdin_sha256=hashlib.sha256(raw.encode()).hexdigest(),actual_process_argv=[sys.executable,'-B',str(HERE/'stage_measure.py')],resources=resources,result_sha256=pair.digest_result(vals),parser_code_sha256=pins['base']['files'])
  def write(mm,rr):
   path.write_text(json.dumps(mm));rr.update(measurement_path=str(path),measurement_sha256=sha(path),stage_resources=resources)
  write(m,record);pair.measurement(record,folder,'on',21,pins)
  bad=copy.deepcopy(record);bad['proof_trace']['unknown']=[1];reject('altered_parser_result',lambda:pair.measurement(bad,folder,'on',21,pins),'result digest mismatch')
  bad=copy.deepcopy(m);bad['parser_code_sha256']['proof_trace.py']='0'*64;rr=copy.deepcopy(record);write(bad,rr);reject('outdated_parser',lambda:pair.measurement(rr,folder,'on',21,pins),'source mismatch')
  bad=copy.deepcopy(m);bad['actual_request']['case']=19;rr=copy.deepcopy(record);write(bad,rr);reject('wrong_actual_case',lambda:pair.measurement(rr,folder,'on',21,pins),'invocation differs')
  bad=copy.deepcopy(m);bad['status']='FAIL';rr=copy.deepcopy(record);write(bad,rr);reject('failed_parser_process',lambda:pair.measurement(rr,folder,'on',21,pins),'invocation differs')
 a,b=expected_profile('off'),expected_profile('on');pair_profiles(a,b);b['profile']['dmaLineEntries']=8
 reject('non_chain_profile_delta',lambda:pair_profiles(a,b),'profile')
 print(json.dumps(dict(status='PASS_TERMINAL_INHERITANCE_SMALL_CONTROLS',positive_controls=5,controls=controls,DUT_executed=False,parser_reexecuted=False),indent=2))
if __name__=='__main__':main()
