#!/usr/bin/env python3
"""Strict local inputs only; each execution creates a new directory. No downloads."""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, datetime
ROOT = pathlib.Path(__file__).resolve().parent
JAR_HASH = 'bc39264c090bfaedd0ac7d9cb1f73d66d9f532e07fa478a247bb7a495bfa78a4'
PART = 'xczu15eg-ffvb1156-2-i'
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('manifest',type=pathlib.Path)
    ap.add_argument('--tool-root',type=pathlib.Path,required=True,help='Existing verified prescreen output directory')
    ap.add_argument('--java-home',type=pathlib.Path,help='Installed JDK root; otherwise use JAVA_HOME, then javac on PATH')
    ap.add_argument('--output-root',type=pathlib.Path,required=True,help='Writable output directory; every run creates a fresh child')
    args=ap.parse_args()
    cache=args.tool_root.resolve()
    jar=cache/'downloads/rapidwright-2025.1.3-standalone-lin64.jar'
    output=args.output_root.resolve()
    require(output.is_dir(),'Output root must already exist')
    manifest=args.manifest.resolve();raw=manifest.read_bytes();m=json.loads(raw)
    require(m.get('schema')==1,'Expected manifest schema 1')
    require(bool(m.get('run_id')),'Missing original run identifier')
    require(m.get('part')==PART,'Only installed exact part is supported')
    require(m.get('matched_export') is True,'Manifest must attest DCP/EDIF/reports are from the same run')
    entries=m['files'];require(len(entries)>=3,'Need DCP, EDIF and report')
    byrole={};files={}
    for e in entries:
        name=e['path'];p=(manifest.parent/name).resolve()
        require(p.is_relative_to(manifest.parent),'Manifest files must stay within bundle')
        require(name not in files and p.is_file(),'Duplicate or missing input: '+name)
        require(e['role'] in ('dcp','edif','report'),'Unsupported role')
        require(sha(p)==e['sha256'],'Input SHA-256 mismatch: '+name)
        files[name]=(p,e['sha256']);byrole.setdefault(e['role'],[]).append(name)
    require(len(byrole.get('dcp',[]))==1 and len(byrole.get('edif',[]))==1 and byrole.get('report'),'Require one DCP, one EDIF and at least one report')
    nets=m.get('critical_nets',[]);require(nets,'No report-supported critical nets selected')
    selected=[]
    for n in nets:
        name=n['name'];report=n['report'];line=n['line']
        require(isinstance(name,str) and name and not any(c in name for c in '\r\n\t'),'Invalid net name')
        require(report in byrole['report'],'Critical net source is not a matched report')
        lines=files[report][0].read_text(errors='strict').splitlines()
        require(isinstance(line,int) and 1<=line<=len(lines) and name in lines[line-1],'Exact net absent from cited report line')
        require(name not in selected,'Duplicate critical net');selected.append(name)
    require(jar.is_file() and sha(jar)==JAR_HASH,'Installed jar hash mismatch')
    home=args.java_home or (pathlib.Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else None)
    compiler=(home/'bin/javac') if home else shutil.which('javac')
    require(compiler is not None,'No installed JDK found; use --java-home, JAVA_HOME, or PATH')
    javac=pathlib.Path(compiler).resolve();java=javac.with_name('java')
    require(javac.is_file() and java.is_file(),'Installed JDK must contain javac and java')
    provenance={}
    if m.get('source_manifest_sha256'):
        source=manifest.parent/'manifest.json'
        require(sha(source)==m['source_manifest_sha256'],'Original source manifest hash mismatch')
        provenance[str(source)]=sha(source)
        for e in json.loads(source.read_bytes())['files']:
            p=(manifest.parent/e['path']).resolve()
            require(p.is_relative_to(manifest.parent) and p.is_file(),'Source manifest file missing/outside bundle')
            require(p.stat().st_size==e['bytes'] and sha(p)==e['sha256'],'Source manifest bytes/hash mismatch: '+e['path'])
            provenance[str(p)]=e['sha256']
    run=pathlib.Path(tempfile.mkdtemp(prefix='run-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-',dir=output))
    print('Output directory:',run,flush=True)
    inp=run/'inputs';inp.mkdir();staged={}
    (run/'manifest.json').write_bytes(raw)
    if provenance:shutil.copyfile(manifest.parent/'manifest.json',run/'source-manifest.json')
    shutil.copyfile(ROOT/'InspectCheckpoint.java',run/'InspectCheckpoint.java')
    shutil.copyfile(pathlib.Path(__file__).resolve(),run/'runner.py')
    for i,(name,(p,digest)) in enumerate(files.items()):
        q=inp/(str(i)+'-'+p.name);shutil.copyfile(p,q);q.chmod(0o444);staged[name]=q
        require(sha(q)==digest,'Copy verification failed')
    (run/'critical-nets.txt').write_text('\n'.join(selected)+'\n')
    env=os.environ.copy();env['RAPIDWRIGHT_PATH']=str(cache/'rapidwright')
    env.pop('JAVA_TOOL_OPTIONS',None);env.pop('_JAVA_OPTIONS',None);env.pop('JDK_JAVA_OPTIONS',None)
    status={'runner_sha256':sha(run/'runner.py'),'java_source_sha256':sha(run/'InspectCheckpoint.java'),'source_manifest_verified_files':len(provenance)-1 if provenance else 0,'status':'FAILED','run_id':m['run_id'],'manifest_sha256':hashlib.sha256(raw).hexdigest(),'jar_sha256':JAR_HASH,'inputs_preserved':False,'scope':'read-only; no timing qualification'}
    try:
        with (run/'compile.log').open('w') as log:
            subprocess.run([str(javac),'-cp',str(jar),'-d',str(run),str(run/'InspectCheckpoint.java')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90,check=True)
        command=[str(java),'-Xmx4g','-XX:ActiveProcessorCount=2','-cp',str(jar)+os.pathsep+str(run),'InspectCheckpoint',str(staged[byrole['dcp'][0]]),str(staged[byrole['edif'][0]]),str(run/'critical-nets.txt'),PART]
        (run/'command.json').write_text(json.dumps(command,indent=2)+'\n')
        with (run/'analysis.log').open('w') as log:
            subprocess.run(command,cwd=run,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600,check=True)
        status['status']='PASS_READ_ONLY_INSPECTION'
    finally:
        status['inputs_preserved']=all(sha(p)==digest and sha(staged[name])==digest for name,(p,digest) in files.items()) and manifest.read_bytes()==raw and all(sha(p)==h for p,h in provenance.items())
        if not status['inputs_preserved']:status['status']='FAILED_INPUT_INTEGRITY'
        status['outputs']={p.name:sha(p) for p in run.iterdir() if p.is_file()}
        (run/'receipt.json').write_text(json.dumps(status,indent=2)+'\n')
    require(status['inputs_preserved'],'Input integrity changed')
if __name__=='__main__':
    try:main()
    except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
