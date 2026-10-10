"""One fresh process per stage, so waited-child maxRSS has no previous-stage maximum."""
import hashlib,json,resource,sys,time
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent/'posted-preparation-priority-cpu-prep-r1'
def usage(who):
 r=resource.getrusage(who);return dict(maxrss_KiB=r.ru_maxrss,user_seconds=r.ru_utime,system_seconds=r.ru_stime)
def main():
 raw_request=sys.stdin.read();q=json.loads(raw_request)
 if Path(q['measurement']).exists():raise RuntimeError('fresh stage measurement required')
 start=time.monotonic();r={'schema':'cpu-host-measured-stage-v1','stage':q['stage'],'status':'RUNNING','actual_process_argv':list(sys.orig_argv),'actual_stdin_text':raw_request,'actual_stdin_sha256':hashlib.sha256(raw_request.encode()).hexdigest(),'actual_request':q}
 try:
  if q['stage']=='command':
   sys.path.insert(0,str(P));import model
   r['result']=model.execute(q['cmd'],Path(q['log']),q['seconds'],cwd=Path(q['cwd']),expected=q['expected'],extra_env=q['extra_env'],artifact_limit_bytes=q['artifact_limit_bytes'])
  elif q['stage']=='validate':
   sys.path.insert(0,str(H));import run
   r['result']=run.validate_output(Path(q['out']),q['side'],q['case'])
   r['result_sha256']=hashlib.sha256(json.dumps(json.loads(json.dumps(r['result'])),sort_keys=True,separators=(',',':')).encode()).hexdigest()
   r['parser_code_sha256']={n:hashlib.sha256((H/n).read_bytes()).hexdigest()for n in ('parser.py','canonical_trace.py','admission_trace.py','admission_trace_v1.py','dmmu_trace.py','unissued_trace.py','window_trace.py','proof_trace.py','lru_trace.py')}
  else:raise RuntimeError('unsupported measured stage')
  r['status']='PASS'
 except BaseException as e:r['status']='FAIL';r['error']=str(e)
 finally:
  r['resources']=dict(wall_seconds=time.monotonic()-start,self=usage(resource.RUSAGE_SELF),waited_children=usage(resource.RUSAGE_CHILDREN),fresh_process=True,units='Linux KiB; child maximum includes waited descendants; self measured separately')
  Path(q['measurement']).write_text(json.dumps({k:v for k,v in r.items()if k!='result'},indent=2)+'\n')
  print(json.dumps(r))
 return 0 if r['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
