#!/usr/bin/env python3
"""One identity-only fetch horizon CPU versus sealed 6b223f0. Explicit emission/build gates.
Source preflight is default. Frozen components+independent graph required before
GSIM. Historical hosts/objects/receipts stay immutable, and failures are retained.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode=True
import advisory_owner_cpu as old
import certified_ingress_cpu as certified
import identity_fetch_horizon_cpu_host as host
import identity_fetch_horizon_off_fir as off
import advisory_owner_bare_rom as bare
import advisory_owner_cpu_smoke as smoke
import certified_ingress_noncanonical_cpu as noncanonical
prior,common,raw,row=old.prior,old.common,old.raw,old.row
need,sha,read,save=old.need,old.sha,old.read,old.save
CONTROL='full-r1-m3-certified-ingress'
CANDIDATE='full-r1-m3-identity-fetch-horizon'
MAIN='soc.core.ooo.IdentityFetchHorizonCpuGsimMain'
REFERENCE=common.BUILD/'certified-ingress-cpu-20261025-r4/receipt.json'
REFERENCE_SHA='9547f0e498e985d97c3d1b22a808e6468c82c32bea3d9708e3931e10fff2c37b'

BASE_COMMIT='6b223f03c362b4a31d8dc95ef811cb21a21ef858'
HISTORICAL_BASE='d5805c648aae30cf6c7004fdd0c5a86a4a84b988'
ARCHIVE=common.ROOT.parent/'certified-ingress-final-recovery-20261025-r1'
POSTCOMMIT=ARCHIVE/'payload/postcommit-binding.json'
SAFE_RAM={'base':0x80200000,'bytes':128*1024,'end_exclusive':0x80220000}

def inputs():
    # Freeze the full local Python/host oracle dependency closure, not only new files.
    files=row.scala.compile_source_paths(common.ROOT)
    files += list(common.HERE.rglob('*.py'))+list((common.HERE/'harness').rglob('*'))
    files += list((common.HERE/'m2_data_translation').rglob('*'))
    files += list((common.HERE/'a1_fetch_supply').rglob('*'))
    files += list((common.HERE/'config').rglob('*'))
    files += [host.INVENTORY]
    files += [common.ROOT/'fpga/common/scala_compile_receipt.py']
    return {str(p.relative_to(common.ROOT)):sha(p) for p in sorted(set(files)) if p.is_file()}

def history(tools):
    need(sha(REFERENCE)==REFERENCE_SHA,'sealed 6b223f0 runtime receipt drift')
    r=read(REFERENCE)
    need(r['status']=='PASS_CERTIFIED_INGRESS_FOCUSED_CPU_AWAIT_INDEPENDENT_REVIEW' and
         r['inputs_unchanged'] and r['history_unchanged'] and r['tools']==tools,
         'saved runtime qualification/epoch mismatch')
    post=read(POSTCOMMIT)
    need(post['schema']=='certified-ingress-final-commit-binding-v1' and
         post['status']=='PASS_CLEAN_BUNDLE_CLONE_EXACT_SOURCE' and
         post['final_commit']==BASE_COMMIT and post['historical_base']==HISTORICAL_BASE and
         post['precommit_receipts_unchanged'] is True and post['postcommit_hardware_rerun'] is False,
         'historical precommit/postcommit identity mismatch')
    compile_path=common.ROOT/post['compile_receipt'];compiled=read(compile_path)
    need(sha(compile_path)==post['compile_receipt_sha256'] and
         compiled['sourceCommit']==HISTORICAL_BASE, 'historical compile identity drift')
    need({str(Path(k).relative_to(compiled['sourceRoot'])):v for k,v in compiled['sourceInputs'].items()}
         ==post['compile_inputs_sha256'],'postcommit compile-input map does not bind historical receipt')
    need(sha(Path(compiled['sourceManifest']['path']))==compiled['sourceManifest']['sha256'],
         'historical compile source manifest drift')
    pinned=ARCHIVE/'pinned-source'
    need(subprocess.check_output(['git','-C',str(pinned),'rev-parse','HEAD'],text=True).strip()==BASE_COMMIT,
         'historical pinned clone commit differs')
    bound={'artifacts':{str(REFERENCE):REFERENCE_SHA,str(POSTCOMMIT):sha(POSTCOMMIT),
        str(compile_path):sha(compile_path),
        compiled['sourceManifest']['path']:compiled['sourceManifest']['sha256'],**{str(REFERENCE.parent/p):v for p,v in r['artifacts'].items()}}}
    for key in ('compile_inputs_sha256','precommit_source_sha256','source_files_sha256'):
        need(post[key], 'empty historical source map '+key)
        for name,digest in post[key].items():
            target=pinned/name
            need(sha(target)==digest, 'postcommit clone source mismatch '+name)
            bound['artifacts'][str(target)]=digest
    # Original frozen working-tree manifest is verified against final clone,
    # never rewritten to pretend the historical compile happened after commit.
    for name,digest in r['inputs'].items():
        need(sha(pinned/name)==digest,'historical runtime input differs from final clone '+name)
    m=r['models'][CONTROL];path=REFERENCE.parent/CONTROL
    need(prior.verify_build(path,tools['compiler']['command'],Path(m['first_build']['host']))==m['first_build'],
         'sealed CPU build mismatch')
    need(row.unchanged_artifacts(bound),'saved artifacts drift')
    return path,m,bound

def emit(a,tools,baseline,sealed,binding):
    need(a.compile_receipt,'one unified compile receipt required')
    compiled=row.scala.verify_receipt(a.compile_receipt,common.ROOT)
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    before=inputs();r={'schema':'identity-fetch-horizon-emission-v1','status':'RUNNING','inputs':before,'tools':tools,
        'compile_receipt':str(a.compile_receipt),'compile_receipt_sha256':sha(a.compile_receipt),'new_DUT_builds':0,'history':binding,'safe_ram':SAFE_RAM}
    save(out/'emit-receipt.json',r)
    try:
        for p in (CONTROL,CANDIDATE):
            target=out/p;target.mkdir()
            common.run([tools['java']['path'],'-cp',os.pathsep.join(compiled['runClasspathEntries']),MAIN,target,p],log=target/'elaborate.log',timeout=300)
        r['off']=off.validate((baseline/(raw.TOP+'.fir')).read_bytes(),(out/CONTROL/(raw.TOP+'.fir')).read_bytes())
        for kind in ('config','core'):
            x,y,z=row.effective(out/CONTROL)[kind],row.effective(out/CANDIDATE)[kind],sealed['effective_parameters'][kind]
            need(set(x)==set(z)|{'fetchThirdPacketLookahead'} and x['fetchThirdPacketLookahead']=='false' and all(x[k]==v for k,v in z.items()),'OFF parameter drift')
            need(row.differences(x,y)=={'fetchThirdPacketLookahead':['false','true']},'not exact single-flag candidate')
        r['status']='PASS_IDENTITY_FETCH_HORIZON_EMISSION_AWAIT_GRAPH_AND_COMPONENTS'
    except BaseException as e:r.update(status='FAIL',error=f'{type(e).__name__}: {e}');raise
    finally:
        r['inputs_unchanged']=inputs()==before
        if not r['inputs_unchanged']:r['status']='FAIL_INPUT_DRIFT'
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='emit-receipt.json'}
        save(out/'emit-receipt.json',r)
    need(r['status'].startswith('PASS_'),r['status'])
    return r

def build_once(model,tools,adapters):
    # prior.build_candidate installs its real-header gate exactly ONCE. Restore
    # original callable even on failure; later host-only compiles are never wrapped.
    original=common.run
    need(original.__module__==common.__name__ and original.__name__=='run',
         'nested compiler gate forbidden; invoke runner directly')
    try:return prior.build_candidate(model,tools,adapters)
    finally:common.run=original

def collect(model,candidate):
    return certified.collect(model,True)

def build_run(a,tools,baseline,sealed,binding):
    out=common.BUILD/a.tag;ep=out/'emit-receipt.json';e=read(ep)
    need(e['status']=='PASS_IDENTITY_FETCH_HORIZON_EMISSION_AWAIT_GRAPH_AND_COMPONENTS' and e['inputs']==inputs() and e['inputs_unchanged'] and e['tools']==tools,'frozen emission required')
    need(e['safe_ram']==SAFE_RAM and e['new_DUT_builds']==0,'emission contract drift')
    need(e['artifacts'] and row.unchanged_artifacts({'artifacts':{
        str(out/p):v for p,v in e['artifacts'].items()}}),'emission artifact drift')
    compile_path=Path(e['compile_receipt'])
    need(sha(compile_path)==e['compile_receipt_sha256'],'emission compile binding drift')
    row.scala.verify_receipt(compile_path,common.ROOT)
    gates={}

    for kind,path,status in [('structure',a.structure_receipt,'PASS_IDENTITY_FETCH_HORIZON_SOURCE_AND_STRUCTURE'),('component',a.component_receipt,'PASS_IDENTITY_FETCH_HORIZON_COMPONENTS')]:
        need(path,'missing '+kind+' gate');r=read(path)
        need(r['status']==status and r['compile_receipt_sha256']==sha(compile_path),'wrong '+kind+' approval')
        need(r['inputs'] and all(sha(common.ROOT/p)==v for p,v in r['inputs'].items()),kind+' source drift')
        need(r['tool_epoch']==tools and r['inputs_unchanged'],kind+' wrong epoch/source freeze')
        if kind=='structure':need(r['emit_receipt_sha256']==sha(ep),'graph wrong emission')
        need(r['artifacts'],'empty '+kind+' evidence')
        need(row.unchanged_artifacts({'artifacts':{str(path.parent/p):v for p,v in r['artifacts'].items()}}),kind+' artifact drift')
        gates[kind]={'path':str(path),'sha256':sha(path),
                     'artifacts':{str(path.parent/p):v for p,v in r['artifacts'].items()}}
    need(not (out/'receipt.json').exists(),'fresh attempt only; keep failures')
    before=inputs();r={'schema':'identity-fetch-horizon-one-new-cpu-v1','status':'RUNNING','inputs':before,'tools':tools,'models':{},'new_DUT_builds':0,'history':binding,'safe_ram':SAFE_RAM}
    r.update(gates=gates,emit_receipt_sha256=sha(ep),compile_receipt_sha256=sha(compile_path),
             new_DUT_build_attempts=0,scope='focused host-serviced CPU only; no physical timing or board claim')
    save(out/'receipt.json',r)
    try:
        control=out/CONTROL;(control/'load-host').mkdir()
        for name,flags in [('test.log',[]),('load-host/test.log',['--trace'])]:
            binary=baseline/('run' if name=='test.log' else 'load-host/run')
            common.run([binary,*flags],env=prior.base.runtime_env(),log=control/name,timeout=180)
            need((control/name).read_bytes()==(baseline/name).read_bytes(),'saved control replay changed')
        r['models'][CONTROL]=collect(control,False)
        model=out/CANDIDATE;adapters=host.adapters(model)
        record={'effective_parameters':row.effective(model),'host_adapters':adapters};r['models'][CANDIDATE]=record
        r['new_DUT_build_attempts']=1;save(out/'receipt.json',r)
        record['first_build']=build_once(model,tools,adapters);r['new_DUT_builds']=1;save(out/'receipt.json',r)
        common.run([model/'run'],env=prior.base.runtime_env(),log=model/'test.log',timeout=180)
        record['second_host']=prior.load_host(model,tools,record['first_build'],adapters['load'])
        common.run([model/'load-host/run','--trace'],env=prior.base.runtime_env(),log=model/'load-host/test.log',timeout=180)
        record.update(collect(model,True));record['negative']=raw.negative(model)
        # Independent passive fetch owners for both cached control and the ONE
        # new candidate. Only hosts are compiled here; no second DUT generation.
        r['fetch_capture']={};r['bare']={}
        for label,path,first,source_adapters,enabled in [
            ('control',baseline,sealed['first_build'],sealed['host_adapters'],False),
            ('candidate',model,record['first_build'],adapters,True)]:
            sources={'vm':Path(source_adapters['vm']['adapter']),
                     'load':Path(source_adapters['load']['adapter']),'bare':bare.HOST}
            plan=host.prepare_capture(path,out/('fetch-capture-'+label),sources)
            result=host.run_capture(plan,tools,first)
            analysis=host.collect_capture(plan,enabled)
            need(analysis['status']=='PASS_IDENTITY_FETCH_HORIZON_DIRECT_OLD_CAPTURE' and
                 analysis['enabled']==enabled,'independent full-owner capture gate')
            need(set(analysis['trajectories'])=={'vm-'+n for n in raw.VM_CASES}|
                 {'load-'+n for n in raw.LOAD_CASES}|{'bare-bare'},'incomplete capture guest set')
            for kind,original_log in [('vm',path/'test.log'),('load',path/'load-host/test.log')]:
                need(Path(result['runs'][kind]['functional_log']).read_bytes()==original_log.read_bytes(),
                     'passive capture changed functional trajectory '+label+' '+kind)
            r['fetch_capture'][label]={'run':result,'analysis':analysis}
            r['bare'][label]=result
        r['native_atomic_fp']=smoke.run({'owner_only':{'path':baseline,'first_build':sealed['first_build']},
            'combined':{'path':model,'first_build':record['first_build']}},tools,out/'native-atomic-fp')
        r['noncanonical']=noncanonical.run({'control':{'path':baseline,'first_build':sealed['first_build']},
            'candidate':{'path':model,'first_build':record['first_build']}},tools,out/'noncanonical')
        # Strict architectural invariants, performance is observed rather than required.
        a0,b0=r['models'][CONTROL],record
        for key,expected in [('cases',raw.VM_CASES),('load_cases',raw.LOAD_CASES)]:
            need([v['name'] for v in a0[key]]==list(expected) and
                 [v['name'] for v in b0[key]]==list(expected),'complete ordered guest set '+key)
        need(len(a0['forwarding'])==len(b0['forwarding'])==len(raw.VM_CASES),'forwarding guest count')
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
            'old_work':x['work_cycles'],'new_work':y['work_cycles'],
            'old_drain':x['drain_cycles'],'new_drain':y['drain_cycles'],
            'old_work_plus_drain':x['work_cycles']+x['drain_cycles'],'new_work_plus_drain':y['work_cycles']+y['drain_cycles'],
            'old_start_complete':x['roi_start_to_complete_hist'],'new_start_complete':y['roi_start_to_complete_hist']}
            for x,y in zip(a0['load_cases'],b0['load_cases'])]
        r['performance'] += [{'name':y['name'],'old_roi':x['roi_cycles'],'new_roi':y['roi_cycles'],
            'old_work':x['work_cycles'],'new_work':y['work_cycles'],
            'old_drain':x['drain_cycles'],'new_drain':y['drain_cycles'],
            'old_work_plus_drain':x['work_cycles']+x['drain_cycles'],
            'new_work_plus_drain':y['work_cycles']+y['drain_cycles'],
            'old_physical_fetch_requests':x['physical_fetch_requests'],
            'new_physical_fetch_requests':y['physical_fetch_requests']}
            for x,y in zip(a0['cases'],b0['cases'])]
        row.scala.verify_receipt(compile_path,common.ROOT)
        need(all(sha(Path(g['path']))==g['sha256'] and row.unchanged_artifacts(g)
                 for g in gates.values()),'gate receipt/artifact drift during run')
        need(prior.epoch.tool_binding(a.tool_receipt)==tools,'tool epoch drift during run')
        r['status']='PASS_IDENTITY_FETCH_HORIZON_FOCUSED_CPU_AWAIT_INDEPENDENT_REVIEW'
    except BaseException as error:r.update(status='FAIL',error=f'{type(error).__name__}: {error}');raise
    finally:
        r['inputs_unchanged']=inputs()==before;r['history_unchanged']=row.unchanged_artifacts(binding)
        if not r['inputs_unchanged'] or not r['history_unchanged']:r['status']='FAIL_INPUT_DRIFT'
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'receipt.json'};save(out/'receipt.json',r)
    need(r['status'].startswith('PASS_'),r['status'])
    return r

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tag',required=True)
    for k in ('compile','tool','structure','component'):p.add_argument('--'+k+'-receipt',type=Path)
    g=p.add_mutually_exclusive_group();g.add_argument('--emit',action='store_true');g.add_argument('--build-run',action='store_true')
    a=p.parse_args();need(re.fullmatch(r'[A-Za-z0-9_-]+',a.tag),'fresh safe tag')
    for k,v in vars(a).items():
        if k.endswith('_receipt') and v is not None:setattr(a,k,v.resolve())
    if not a.emit and not a.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY_NO_BUILD','source_files':len(inputs()),'new_DUT_builds':0}));return
    need(a.tool_receipt,'qualified tool receipt required')
    tools=prior.epoch.tool_binding(a.tool_receipt);baseline,sealed,binding=history(tools)
    if a.emit:r=emit(a,tools,baseline,sealed,binding)
    elif a.build_run:r=build_run(a,tools,baseline,sealed,binding)
    else:r={'status':'PREFLIGHT_ONLY_NO_BUILD','new_DUT_builds':0}
    print(json.dumps({'status':r['status'],'new_DUT_builds':r.get('new_DUT_builds',0)}))
if __name__=='__main__':main()
