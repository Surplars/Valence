import pathlib,subprocess,os,json,hashlib,time,re,argparse
parser=argparse.ArgumentParser(description="Held bare preparation only; reuses qualified current pool backend models")
parser.add_argument('--backend-results',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[3]
out=args.output.resolve();out.mkdir(exist_ok=False)
runroot=args.backend_results.resolve();src=root/'simulator/gsim/harness/pool_bare_preparation.cpp'
while True:
 r=json.load(open(runroot/'receipt.json'))
 if r['status']!='RUNNING':break
 time.sleep(2)
assert r['status']=='PASS_CURRENT_POOL_BACKEND',r.get('failure',r['status'])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
s=(runroot/'observed_backend.cpp').read_text();anchor='    Tables tables; Bytes actual, expected;';assert s.count(anchor)==1;s=s.replace(anchor,'    bool independentBare=false;\n'+anchor)
anchor='e.pa=tables.physical(e.address)';assert s.count(anchor)==1;s=s.replace(anchor,'e.pa=independentBare?e.address:tables.physical(e.address)')
(out/'bare_backend.cpp').write_text(s)
r={'status':'RUNNING','scope':'Current-profile backend held preparation only; bare posted launch intentionally excluded; software identity/Sv39 selected by completed CSR writes','backend_receipt_sha256':sha(runroot/'receipt.json'),'driver_sha256':sha(src),'adapted_host_sha256':sha(out/'bare_backend.cpp'),'commands':[],'metrics':{}}
def run(label,cmd,negative=False):
 with (out/(label+'.log')).open('w') as f:p=subprocess.run(list(map(str,cmd)),stdout=f,stderr=f,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'},timeout=300)
 t=(out/(label+'.log')).read_text();r['commands'].append({'label':label,'exit':p.returncode,'log_sha256':sha(out/(label+'.log'))});save()
 if negative:assert p.returncode==1 and 'independent bare resident address mismatch' in t,t[-3000:]
 else:assert p.returncode==0,t[-3000:]
 print(label,'PASS',flush=True);return t
def save():(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
try:
 for arm in ['baseline','pool']:
  d=runroot/arm;objects=sorted(d.glob('ReadyStoreQuery77BackendGsim[0-9]*.o'));assert objects
  run(arm+'-compile',[os.environ['GSIM_CXX'],'-std=c++20','-O1','-g0','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(out),'-I'+str(d),'-I'+str(root/'simulator/gsim/ready_store_query77'),src,*objects,'-ldl','-o',out/arm])
  t=run(arm+'-positive',[out/arm]);r['metrics'][arm]=re.findall(r'^(?:C1_METRICS|POOL_BARE_PREPARATION_CASE).*$',t,re.M);save()
  run(arm+'-negative',[out/arm,'--mutate-bare-address'],True)
 assert r['metrics']['baseline']==r['metrics']['pool'],r['metrics']
 r['status']='PASS_CURRENT_POOL_BARE_PREPARATION';save()
except BaseException as e:r.update(status='FAILED_PRESERVE_EVIDENCE',failure=str(e));save();raise
