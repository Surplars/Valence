#!/usr/bin/env python3
"""One new combined CPU versus saved d5805c6. Explicit emission/build gates.
Source preflight is default. Frozen components+independent graph required before
GSIM. Historical hosts/objects/receipts stay immutable, and failures are retained.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode=True
import advisory_owner_cpu as old
import certified_ingress_components as components
import certified_ingress_cpu_host as host
import certified_ingress_off_fir as off
import advisory_owner_trace as trace
import advisory_owner_bare_rom as bare
import advisory_owner_cpu_smoke as smoke
import certified_ingress_noncanonical_cpu as noncanonical
prior,common,raw,row=old.prior,old.common,old.raw,old.row
need,sha,read,save=old.need,old.sha,old.read,old.save
CONTROL='full-r1-m3-advisory-owner'
CANDIDATE='full-r1-m3-certified-ingress'
MAIN='soc.core.ooo.CertifiedIngressCpuGsimMain'
REFERENCE=common.BUILD/'advisory-owner-cpu-recovery-20261025-r1/receipt.json'
REFERENCE_SHA='53fc456014e4d9b6c922bebe01fa5b2a2c8eac1e907e35ab437dc9a8f84c6036'

def inputs():return components.inputs()

def history(tools):
    need(sha(REFERENCE)==REFERENCE_SHA,'sealed d580 runtime receipt drift')
    r=read(REFERENCE);need(r['status']=='PASS_ADVISORY_OWNER_WITH_HOT_GAIN' and r['tools']==tools,'saved tool/runtime qualification mismatch')
    m=r['models'][CONTROL];path=Path(r['model_paths'][CONTROL])
    need(prior.verify_build(path,tools['compiler']['command'],Path(m['first_build']['host']))==m['first_build'],'sealed CPU build mismatch')
    bound={'artifacts':{str(REFERENCE):REFERENCE_SHA,**{str(REFERENCE.parent/p):v for p,v in r['artifacts'].items()}}}
    need(row.unchanged_artifacts(bound),'saved artifacts drift')
    return path,m,bound

def emit(a,tools,baseline,sealed,binding):
    need(a.compile_receipt,'one unified compile receipt required')
    compiled=row.scala.verify_receipt(a.compile_receipt,common.ROOT)
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    before=inputs();r={'schema':'certified-ingress-emission-v1','status':'RUNNING','inputs':before,'tools':tools,
        'compile_receipt':str(a.compile_receipt),'compile_receipt_sha256':sha(a.compile_receipt),'new_DUT_builds':0,'history':binding}
    try:
        for p in (CONTROL,CANDIDATE):
            target=out/p;target.mkdir()
            common.run([tools['java']['path'],'-cp',os.pathsep.join(compiled['runClasspathEntries']),MAIN,target,p],log=target/'elaborate.log',timeout=300)
        r['off']=off.validate((baseline/(raw.TOP+'.fir')).read_bytes(),(out/CONTROL/(raw.TOP+'.fir')).read_bytes())
        for kind in ('config','core'):
            x,y,z=row.effective(out/CONTROL)[kind],row.effective(out/CANDIDATE)[kind],sealed['effective_parameters'][kind]
            need(set(x)==set(z)|{'certifiedLoadIngress'} and x['certifiedLoadIngress']=='false' and all(x[k]==v for k,v in z.items()),'OFF parameter drift')
            need(row.differences(x,y)=={'certifiedLoadIngress':['false','true']},'not exact single-flag candidate')
        r['status']='PASS_CERTIFIED_INGRESS_EMISSION_AWAIT_GRAPH_AND_COMPONENTS'
    except BaseException as e:r.update(status='FAIL',error=f'{type(e).__name__}: {e}');raise
    finally:
        r['inputs_unchanged']=inputs()==before
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='emit-receipt.json'}
        save(out/'emit-receipt.json',r)
    return r

def build_once(model,tools,adapters):
    # prior.build_candidate installs its real-header gate exactly ONCE. Restore
    # original callable even on failure; later host-only compiles are never wrapped.
    original=common.run
    try:return prior.build_candidate(model,tools,adapters)
    finally:common.run=original

def collect(model,candidate):
    if not candidate:return old.collect(model)
    log=model/'test.log'
    r={k:raw.parse(log,p,raw.VM_CASES,row.PASS) for k,p in raw.VM_PREFIXES.items()}
    routes={};owners={name:[] for name in raw.VM_CASES};seen=set()
    for line in log.read_text().splitlines():
        if line.startswith('CERTIFIED_INGRESS_ROUTE '):
            d=dict(x.split('=',1) for x in line.split()[1:]);key=(d['guest'],int(d['index']),int(d['tag']));need(key not in routes,'duplicate direct route owner');routes[key]=d
        if line.startswith('CHECKED_FLOW_OWNER '):
            d=dict(x.split('=',1) for x in line.split()[1:]);guest=d.pop('guest');d={k:int(v) for k,v in d.items()};key=(guest,d['index'],d['tag']);need(key not in seen,'duplicate full owner');seen.add(key);owners[guest].append(d)
    hist={}
    for name,rows in owners.items():
        groups={k:[] for k in raw.FLOW_HISTOGRAMS};first=True
        for o in rows:
            route=routes[(name,o['index'],o['tag'])];direct=int(route['direct']);need(direct in (0,1),'invalid direct classification')
            need((o['upstream']==o['checked'] if direct else o['upstream']<o['checked']) and o['checked']<o['physical']<o['reply'],'direct/fallback nonflow timestamps')
            need(not direct or o['prechecked'] and not o['write'],'noncertified direct owner')
            if o['prechecked']:group='prechecked_latency'
            elif not o['write']:group='raw_load_latency'
            elif first:group='cold_store_latency';first=False
            else:group='raw_store_latency'
            groups[group].append(o)
        hist[name]={k:{stage:dict(Counter(o[right]-o[left] for o in entries)) for stage,left,right in
            [('upstream_checked','upstream','checked'),('checked_physical','checked','physical'),('physical_reply','physical','reply'),('upstream_physical','upstream','physical')]} for k,entries in groups.items()}
        need(rows and all(rows[i-1]['physical']<rows[i]['physical'] for i in range(1,len(rows))),'single ordered physical stream')
    need(len(routes)==len(seen),'unmatched route observations')
    r.update(latency_owners=owners,owner_stage_histograms=hist)
    load=model/'load-host/test.log'
    r['load_cases']=raw.parse(load,'LOAD_SUPPLY_METRIC ',raw.LOAD_CASES,'LOAD_SUPPLY_PASS')
    r['proof_metrics']=raw.parse(load,'ELASTIC_PROOF_METRIC ',raw.LOAD_CASES,'LOAD_SUPPLY_PASS')
    r['load_owners']=prior.load_owners(load)
    r['certified_routes']=routes_to_json(routes)
    load_routes={};load_owners={}
    for line in load.read_text().splitlines():
        if line.startswith(('CERTIFIED_LOAD_ROUTE ','CERTIFIED_LOAD_OWNER ')):
            d=dict(x.split('=',1) for x in line.split()[1:]);guest=d.pop('guest');d={k:int(v) for k,v in d.items()}
            key=(guest,d['index'],d['tag']);target=load_routes if line.startswith('CERTIFIED_LOAD_ROUTE ') else load_owners
            need(key not in target,'duplicate full load timestamp owner');target[key]=d
    for key,o in load_owners.items():
        if not o['retired']:continue
        route=load_routes[key];direct=route['direct']
        need(route['epoch']==o['epoch'] and route['start']==o['start'] and route['checked']==o['checked'],
             'load full-tag route/timestamp join mismatch')
        need(o['start']<=o['upstream'] and (o['upstream']==o['checked'] if direct else o['upstream']<o['checked']) and
             o['checked']<o['physical']<o['reply']<o['complete']<=o['retire'], 'load register residence/order violation')
        need(not direct or o['prechecked'],'uncertified load shortcut')
    need(load_owners,'missing exact load residence owners')
    r['certified_load_owner_timestamps']=[{'guest':k[0],**v} for k,v in load_owners.items()]
    return r

def routes_to_json(routes):return [{'guest':k[0],'index':k[1],'tag':k[2],**v} for k,v in routes.items()]

def build_run(a,tools,baseline,sealed,binding):
    out=common.BUILD/a.tag;ep=out/'emit-receipt.json';e=read(ep)
    need(e['status']=='PASS_CERTIFIED_INGRESS_EMISSION_AWAIT_GRAPH_AND_COMPONENTS' and e['inputs']==inputs() and e['inputs_unchanged'] and e['tools']==tools,'frozen emission required')
    compile_path=Path(e['compile_receipt']);row.scala.verify_receipt(compile_path,common.ROOT)
    for kind,path,status in [('structure',a.structure_receipt,'PASS_CERTIFIED_INGRESS_SOURCE_AND_STRUCTURE'),('component',a.component_receipt,'PASS_CERTIFIED_INGRESS_COMPONENTS')]:
        need(path,'missing '+kind+' gate');r=read(path)
        need(r['status']==status and r['compile_receipt_sha256']==sha(compile_path),'wrong '+kind+' approval')
        need(r['inputs'] and all(sha(common.ROOT/p)==v for p,v in r['inputs'].items()),kind+' source drift')
        if kind=='structure':need(r['emit_receipt_sha256']==sha(ep),'graph wrong emission')
        else:need(r['tool_epoch']==tools and r['inputs_unchanged'],'component wrong epoch')
        need(row.unchanged_artifacts({'artifacts':{str(path.parent/p):v for p,v in r['artifacts'].items()}}),kind+' artifact drift')
    need(not (out/'receipt.json').exists(),'fresh attempt only; keep failures')
    before=inputs();r={'schema':'certified-ingress-one-new-cpu-v1','status':'RUNNING','inputs':before,'tools':tools,'models':{},'new_DUT_builds':0,'history':binding}
    try:
        control=out/CONTROL;(control/'load-host').mkdir()
        for name,flags in [('test.log',[]),('load-host/test.log',['--trace'])]:
            binary=baseline/('run' if name=='test.log' else 'load-host/run')
            common.run([binary,*flags],env=prior.base.runtime_env(),log=control/name,timeout=180)
            need((control/name).read_bytes()==(baseline/name).read_bytes(),'saved control replay changed')
        r['models'][CONTROL]=collect(control,False)
        model=out/CANDIDATE;adapters=host.adapters(model)
        record={'effective_parameters':row.effective(model),'host_adapters':adapters};r['models'][CANDIDATE]=record
        record['first_build']=build_once(model,tools,adapters);r['new_DUT_builds']=1;save(out/'receipt.json',r)
        common.run([model/'run'],env=prior.base.runtime_env(),log=model/'test.log',timeout=180)
        record['second_host']=prior.load_host(model,tools,record['first_build'],adapters['load'])
        common.run([model/'load-host/run','--trace'],env=prior.base.runtime_env(),log=model/'load-host/test.log',timeout=180)
        record.update(collect(model,True));record['negative']=raw.negative(model)
        # Same immutable Bare program/service, no trace equality assumption ON.
        r['bare']={}
        for label,path,first in [('control',baseline,sealed['first_build']),('candidate',model,record['first_build'])]:
            plan=trace.prepare(path,out/('bare-'+label),{'bare':bare.HOST})
            result=trace.run_prepared(plan,tools,first);r['bare'][label]=result
        r['native_atomic_fp']=smoke.run({'owner_only':{'path':baseline,'first_build':sealed['first_build']},
            'combined':{'path':model,'first_build':record['first_build']}},tools,out/'native-atomic-fp')
        r['noncanonical']=noncanonical.run({'control':{'path':baseline,'first_build':sealed['first_build']},
            'candidate':{'path':model,'first_build':record['first_build']}},tools,out/'noncanonical')
        # Strict architectural invariants, performance is observed rather than required.
        a0,b0=r['models'][CONTROL],record
        for x,y in zip(a0['cases'],b0['cases']):
            for k in ('name','retired','bootstrap_retired','roi_retired','placement'):
                need(x[k]==y[k],'fixed VM architectural identity '+k)
        for x,y in zip(a0['forwarding'],b0['forwarding']):
            for k in ('architectural_stores','physical_stores','store_replies','store_completions',
                      'forwarded_loads','forwarded_retired','alias_forwards','architectural_loads',
                      'upstream_loads','physical_loads','load_replies'):
                need(x[k]==y[k],'VM ownership/architectural traffic '+k)
        bare_metrics={label:bare.old_bare.metrics(Path(value['runs']['bare']['functional_log']))
                      for label,value in r['bare'].items()}
        for label,value in bare_metrics.items():
            need(value['final']['proof_query_accept']==value['final']['proof_query_offer']==0,
                 'Bare must never acquire a virtual certificate')
        for k in ('retired','oracle_loads','oracle_stores','physical_loads','physical_stores','physical_replies'):
            need(bare_metrics['control']['final'][k]==bare_metrics['candidate']['final'][k],'Bare architecture/traffic '+k)
        r['bare_metrics']=bare_metrics
        for x,y in zip(a0['load_cases'],b0['load_cases']):
            for k in raw.LOAD_INVARIANTS:need(x[k]==y[k],'fixed-work/service drift '+k)
        r['performance']=[{'name':y['name'],'old_roi':x['roi_work_cycles'],'new_roi':y['roi_work_cycles'],
            'old_work_plus_drain':x['work_cycles']+x['drain_cycles'],'new_work_plus_drain':y['work_cycles']+y['drain_cycles'],
            'old_start_complete':x['roi_start_to_complete_hist'],'new_start_complete':y['roi_start_to_complete_hist']}
            for x,y in zip(a0['load_cases'],b0['load_cases'])]
        r['status']='PASS_CERTIFIED_INGRESS_FOCUSED_CPU_AWAIT_INDEPENDENT_REVIEW'
    except BaseException as error:r.update(status='FAIL',error=f'{type(error).__name__}: {error}');raise
    finally:
        r['inputs_unchanged']=inputs()==before;r['history_unchanged']=row.unchanged_artifacts(binding)
        if not r['inputs_unchanged'] or not r['history_unchanged']:r['status']='FAIL_INPUT_DRIFT'
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'receipt.json'};save(out/'receipt.json',r)
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tag',required=True)
    for k in ('compile','tool','structure','component'):p.add_argument('--'+k+'-receipt',type=Path,required=k=='tool')
    g=p.add_mutually_exclusive_group();g.add_argument('--emit',action='store_true');g.add_argument('--build-run',action='store_true')
    a=p.parse_args();need(re.fullmatch(r'[A-Za-z0-9_-]+',a.tag),'fresh safe tag')
    for k,v in vars(a).items():
        if k.endswith('_receipt') and v is not None:setattr(a,k,v.resolve())
    tools=prior.epoch.tool_binding(a.tool_receipt);baseline,sealed,binding=history(tools)
    if a.emit:r=emit(a,tools,baseline,sealed,binding)
    elif a.build_run:r=build_run(a,tools,baseline,sealed,binding)
    else:r={'status':'PREFLIGHT_ONLY_NO_BUILD','new_DUT_builds':0}
    print(json.dumps({'status':r['status'],'new_DUT_builds':r.get('new_DUT_builds',0)}))
if __name__=='__main__':main()
