import importlib.util,pathlib,json,hashlib,threading,sys,os
root=pathlib.Path.cwd();out=root/'out/cmu-frequency-r20/managed-stop-final';p=root/'simulator/gsim/common/managed_control_epoch_native.py'
s=importlib.util.spec_from_file_location('checked_runner',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=m.sources();rec={'status':'RUNNING','cases':[],'source_sha256':before,'python':{'path':sys.executable,'sha256':sha(pathlib.Path(sys.executable))},'test_sha256':sha(pathlib.Path(__file__))}
t=threading.Timer(.2,lambda:(out/'stop.request').write_text('CONTROLLED_STOP_FINAL_SELFTEST'));t.start()
try:m.run([sys.executable,'-c','import time; time.sleep(30)'],out,'stop-selftest',2,rec);raise AssertionError('stop not observed')
except KeyboardInterrupt:pass
finally:t.join()
c=rec['cases'][-1];assert c['stop_requested'] and c['interrupted'] and c['process_group_killed'] and c['child_reaped'] and c['returncode']==-9 and not c['timed_out']
try:os.kill(c['pid'],0);raise AssertionError('child still exists')
except ProcessLookupError:rec['child_pid_absent_after_reap']=True
assert m.sources()==before
rec['status']='PASS_SOURCE_BOUND_CONTROLLED_STOP';m.checkpoint(out,rec);print(rec['status'])
