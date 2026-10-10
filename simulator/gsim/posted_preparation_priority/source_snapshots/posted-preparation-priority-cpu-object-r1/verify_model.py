"""Dispatch only between explicitly verified new compilation and literal-byte donor reuse."""
import argparse,json,subprocess,sys,hashlib
from pathlib import Path
H=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(path,digest):
 path=Path(path);assert sha(path)==digest,'model receipt drift';r=json.loads(path.read_text())
 names={'posted-preparation-priority-compiled-object-v1':'compile_stage.py','posted-preparation-priority-literal-object-model-v1':'object_stage.py'}
 assert r.get('schema') in names,'unsupported model schema';name=names[r['schema']]
 pins=json.loads((H/'VERIFIER-PINS.json').read_text());assert sha(H/name)==pins[name],'verifier drift'
 q=subprocess.run([sys.executable,'-B',str(H/name),'verify','--receipt',str(path),'--sha256',digest],capture_output=True,text=True);assert q.returncode==0,q.stderr[-4000:];return json.loads(q.stdout)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--receipt',required=True);p.add_argument('--sha256',required=True);a=p.parse_args();print(json.dumps(verify(a.receipt,a.sha256),indent=2))
