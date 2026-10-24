#!/usr/bin/env python3
"""Test standard per-module sv2v lowering; original DUT semantics and clock timing unchanged.

Modules with SystemVerilog assignment patterns and explicitly named modules
with recorded Icarus elaboration failures are converted. All others compile
directly in Icarus. A source-bound existing model is required.
This is simulator performance research, not an additional hardware profile.
"""
import argparse
import hashlib
import zipfile
import importlib.util
import json
import re
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('tools_base', HERE / 'i1_msi_epoch_native.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--model-dir', required=True, type=Path)
    ap.add_argument('--kind', required=True, choices=('epoch','fullchain'))
    ap.add_argument('--sv2v', required=True)
    ap.add_argument('--sv2v-archive', type=Path, help='Official locked zip; defaults beside the extracted tool directory')
    ap.add_argument('--lower-module', action='append', default=[], help='Additional original module filename justified by an Icarus elaboration error')
    args = ap.parse_args(); out=args.out.resolve(); model=args.model_dir.resolve()
    if out.exists(): ap.error('fresh evidence directory required')
    out.mkdir(parents=True)
    prior_path=model/'receipt.json'; prior=json.loads(prior_path.read_text())
    expected='PASS_A1_RUNTIME_NATIVE_EPOCH' if args.kind=='epoch' else 'PASS_A1_FULLCHAIN_SMOKE'
    if prior['status']!=expected: ap.error('passing source-bound model required')
    for name,sha in prior['source_sha256'].items():
        if b.sha(ROOT/name)!=sha: ap.error('source drift: '+name)
    rtl=sorted((model/'rtl').glob('*.sv'))
    expected_rtl=prior.get('emitted_rtl_sha256',prior.get('model_artifacts',{}))
    manifest_rtl={name for name in expected_rtl if Path(name).parent==model/'rtl' and name.endswith('.sv')}
    if {str(p) for p in rtl}!=manifest_rtl: ap.error('model RTL inventory differs from receipt')
    guest_artifacts=({str(model/name):sha for name,sha in prior['guest']['artifacts'].items()}
                     if args.kind=='epoch' else
                     {name:sha for name,sha in prior['model_artifacts'].items() if Path(name).parent==model})
    for name,sha in guest_artifacts.items():
        if b.sha(Path(name))!=sha: ap.error('guest/model artifact drift: '+name)
    for p in rtl:
        if b.sha(p)!=expected_rtl.get(str(p)): ap.error('model RTL drift: '+str(p))
    if set(args.lower_module)-{p.name for p in rtl}: ap.error('unknown additional module')
    selected=[p for p in rtl if "'{" in p.read_text() or p.name in args.lower_module]
    if not selected: ap.error('no unsupported assignment pattern to convert')
    remaining=[p for p in rtl if p not in selected]
    tb=HERE/('a1_runtime_cdc_tb.sv' if args.kind=='epoch' else 'a1_dynamic_roundtrip_tb.sv')
    back=[] if args.kind=='epoch' else [ROOT/'fpga/common/dynamic'/(n+'.sv') for n in
         ['behavioral_primitives','native_clock_gate','native_clock_drp','native_dynamic_clock_domain']]+[ROOT/'simulator/cdc/rtl8211f_pin_model.sv']
    frozen={str(p):b.sha(p) for p in [*rtl,tb,*back,Path(__file__),HERE/'i1_msi_epoch_native.py',prior_path]}
    frozen.update(guest_artifacts)
    t={n:b.tool(v)for n,v in [('iverilog','iverilog'),('vvp','vvp'),('sv2v',args.sv2v)]}
    lock_path=ROOT/'scripts/cloud/prescreen/downloads.lock.json'
    lock=json.loads(lock_path.read_text())['artifacts']['sv2v-Linux.zip']
    archive=(args.sv2v_archive or Path(t['sv2v']).parent.parent/'sv2v-Linux.zip').resolve()
    if b.sha(archive)!=lock['sha256']: ap.error('sv2v archive does not match official source lock')
    with zipfile.ZipFile(archive) as z:
        tool_sha=hashlib.sha256(z.read('sv2v-Linux/sv2v')).hexdigest()
    if b.sha(Path(t['sv2v']))!=tool_sha: ap.error('sv2v executable differs from locked archive')
    frozen.update({str(p):b.sha(p) for p in (archive,lock_path)})
    r=dict(status='RUNNING',source_sha256=prior['source_sha256'],frozen_artifacts=frozen,
           original_receipt_sha256=b.sha(prior_path),tools=b.tool_hashes(t),cases=[],
           sv2v_source_lock=lock,sv2v_archive=str(archive),
           fallback='Fail closed; use a1_runtime_native.py or a1_dynamic_native.py in a fresh output directory for full lowering',
           selected_modules=[p.name for p in selected],explicit_additional_modules=args.lower_module,untouched_module_count=len(remaining),
           hardware_semantics_changed=False,physical_qualified=False,board_verified=False)
    defs=['-g2012','-DSTOP_COND=1','-DASSERT_VERBOSE_COND=1','-DENABLE_INITIAL_MEM_=1']
    def run(cmd,name,seconds=180,negative=False,banner=None):
        rc,log=b.run(cmd,out,name,seconds,r)
        if negative:
            if rc==0 or 'independent' not in log: raise RuntimeError('negative control failed '+name)
        elif rc or (banner and banner not in log): raise RuntimeError('failed '+name+': '+log[-2000:])
        return log
    try:
        run([t['iverilog'],*defs,'-E','-o',out/'selected-preprocessed.sv',*selected],'preprocess-selected')
        original=(out/'selected-preprocessed.sv').read_text()
        converted=run([t['sv2v'],'--exclude=SeverityTask',out/'selected-preprocessed.sv'],'lower-selected')
        for token in ('$fatal','$error'):
            if original.count(token)!=converted.count(token): raise RuntimeError('severity task changed')
        modules=lambda text: sorted(re.findall(r'^module\s+(\w+)',text,re.M))
        if modules(original)!=modules(converted): raise RuntimeError('module identity changed')
        (out/'selected.v').write_text(converted)
        run([t['iverilog'],*defs,'-E','-o',out/'all-preprocessed.sv',out/'selected.v',*remaining],'preprocess-hybrid')
        total=(out/'all-preprocessed.sv').read_text()
        r['severity_counts']={token:total.count(token)for token in ('$fatal','$error')}
        # Every original assertion site remains after replacing the selected modules.
        for token in ('$fatal','$error'):
            raw_count=sum(p.read_text().count(token)for p in rtl)
            if total.count(token)!=raw_count: raise RuntimeError('global severity count mismatch')
        top='a1_runtime_cdc_tb' if args.kind=='epoch' else 'dynamic_roundtrip_tb'
        run([t['iverilog'],*defs,'-I',model,'-s',top,'-o',out/'test.vvp',out/'selected.v',*remaining,*back,tb],'compile')
        compile_log=(out/'compile.log').read_text()
        if re.search(r'(port.*expects|padding|pruning)',compile_log,re.I):
            raise RuntimeError('hybrid module-interface width warning')
        r['binary_sha256']=b.sha(out/'test.vvp')
        r['binary_bytes']=(out/'test.vvp').stat().st_size
        r['old_binary_bytes']=(model/'test.vvp').stat().st_size
        if args.kind=='epoch':
            for name,extra in [('positive',[]),('negative-data',['+wrong-data']),('negative-irq',['+wrong-irq'])]:
                log=run([t['vvp'],'-i',out/'test.vvp','+rom='+str(model/'guest.hex'),*extra],name,
                        negative=name.startswith('negative'),banner='A1_RUNTIME_CDC_PASS')
                if name=='positive':
                    def lines(s):return [x for x in s.splitlines()if x.startswith('A1_RUNTIME_CDC_')]
                    if lines(log)!=lines((model/'unrelated.log').read_text()):
                        raise RuntimeError('deterministic architectural ledger differs from full lowering')
        else:
            sy=prior['guest_symbols'];first=prior['first_words']
            run([t['vvp'],'-i',out/'test.vvp',f'+done_pc={sy["guest_done"]:x}',f'+fail_pc={sy["guest_fail"]:x}',
                 f'+rom0_first={first[0]:x}',f'+rom1_first={first[1]:x}','+telemetry_smoke'],'smoke',300,
                 banner='TELEMETRY_SMOKE_PASS')
        if any(b.sha(Path(p))!=sha for p,sha in frozen.items()): raise RuntimeError('artifact drift')
        r['status']='PASS_A1_SELECTIVE_'+args.kind.upper()
    except Exception as exc:
        r['status']='FAIL';r['error']=str(exc);raise
    finally:(out/'receipt.json').write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':main()
