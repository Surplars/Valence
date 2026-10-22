#!/usr/bin/env python3
"""One reviewed failed run only; no IP regeneration or qualification."""
import hashlib
import json
import re
from pathlib import Path
import sys

EXPECTED = {
 'blk_mem_gen_0': ('fdf865e38ea41769b3fbd906965e9c455f328b3ee9e79ec625c1e860be623364', 260014),
 'clk_wiz_common': ('0efc15aa18f0a65f3881c80d4fa535a3cd77a33ba9503ca882de66b09cb5bcf7', 12473),
 'ddr4_0': ('4664ca919bb8f3bb81a2a2dd8c57d9809bb94980d91f71e8342201262847986a', 5050922),
}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_dcps(project, expected=EXPECTED):
    result = {}
    for name, (digest, size) in expected.items():
        p = project/'common_board.runs'/(name+'_synth_1')/(name+'.dcp')
        if not p.is_file() or p.stat().st_size != size or sha(p) != digest:
            raise ValueError('OOC DCP changed or missing: '+str(p))
        result[str(p)] = digest
    return result

def frozen(root):
    sys.path.insert(0, str(root/'fpga/common'))
    import diagnostic
    _, manifest, profile = diagnostic.check(root/'diagnostic.json')
    return diagnostic, manifest, profile

def raw_binding(root, profile):
    out=root/'diagnostic-run/synthesis'
    return dict(status='DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM',
                original_manifest_sha256=sha(root/'diagnostic.json'),
                profile_sha256=profile,
                raw_sha256=sha(out/'raw-synthesized-unqualified.dcp'))

def seal_raw(root):
    _, manifest, profile=frozen(root)
    record=raw_binding(root,profile)
    if manifest['configuration']['clock_profile'] == 'boot50-dynamic':
        project=root/'diagnostic-run/synthesis/project'
        actual={}
        for name in EXPECTED:
            file=project/'common_board.runs'/(name+'_synth_1')/(name+'.dcp')
            if not file.is_file(): raise ValueError('Missing freshly synthesized dynamic OOC: '+name)
            actual[name]=(sha(file), file.stat().st_size)
        record['dynamic_ooc']=actual
        record['ip_synthesis_sha256']=sha(root/'diagnostic-run/synthesis/ip-synthesis.json')
        record['project_sha256']=sha(project/'common_board.xpr')
    record['synthesis_tool_sha256']=sha(Path(__file__).resolve().parent/'synthesize.tcl')
    path=root/'diagnostic-run/synthesis/raw-synthesized-unqualified.json'
    if path.exists(): raise ValueError('Do not replace raw checkpoint provenance')
    path.write_text(json.dumps(record,indent=2)+'\n')
    return record

def check(root, phase='synthesis'):
    diagnostic, manifest, profile=frozen(root)
    out = root/'diagnostic-run/synthesis'
    if phase=='implementation':
        stage=json.loads((out/'diagnostic-stage.json').read_text())
        if stage.get('profile_sha256')!=profile or stage.get('outputs_sha256',{}).get('synthesized.dcp')!=sha(out/'synthesized.dcp'):
            raise ValueError('Missing or changed checked synthesis checkpoint')
    else:
        if (out/'synthesized.dcp').exists() or (out/'diagnostic-stage.json').exists():
            raise ValueError('Synthesis already completed; do not overwrite it')
        if not (out/'diagnostic-failure.txt').is_file() or not (out/'ip-synthesis.json').is_file():
            raise ValueError('Expected preserved failed stage and successful IP evidence')
    project=out/'project'
    if not (project/'common_board.xpr').is_file(): raise ValueError('Missing original project')
    if manifest['configuration']['clock_profile'] == 'boot50-dynamic':
        recorded=json.loads((out/'raw-synthesized-unqualified.json').read_text())
        for key,value in raw_binding(root,profile).items():
            if recorded.get(key)!=value: raise ValueError('Dynamic raw binding changed: '+key)
        if recorded.get('ip_synthesis_sha256')!=sha(out/'ip-synthesis.json') or recorded.get('project_sha256')!=sha(project/'common_board.xpr'):
            raise ValueError('Dynamic original IP/project evidence changed')
        if set(recorded.get('dynamic_ooc',{}))!=set(EXPECTED): raise ValueError('Dynamic OOC census changed')
        dcps=verify_dcps(project,recorded['dynamic_ooc'])
    else:
        dcps=verify_dcps(project)
    raw=out/'raw-synthesized-unqualified.dcp'
    if phase=='synthesis' and raw.exists():
        recorded=json.loads((out/'raw-synthesized-unqualified.json').read_text())
        for key,value in raw_binding(root,profile).items():
            if recorded.get(key)!=value: raise ValueError('Raw checkpoint binding changed: '+key)
    here=Path(__file__).resolve().parent
    return dict(status=diagnostic.STATUS, profile_sha256=profile, control_lemma=1,
                mode='implementation' if phase=='implementation' else 'post-only' if raw.exists() else 'top-synthesis',
                original_manifest_sha256=sha(root/'diagnostic.json'),
                project_sha256=sha(project/'common_board.xpr'), ooc_sha256=dcps,
                recovery_tool_sha256={n:sha(here/n) for n in ('resume_diagnostic.py','resume_diagnostic.tcl','synthesize.tcl','diagnostic.tcl','cached_post_opt.tcl','exact_object_cache.tcl','test_exact_object_cache.tcl','post_synth.tcl','post_opt.tcl','common_cdc.tcl','board_audit.tcl','rom_audit.py','dynamic/dynamic_clock_constraints.tcl')})

CACHE_TOOLS = ('resume_diagnostic.py', 'resume_diagnostic.tcl', 'exact_object_cache.tcl',
         'cached_post_opt.tcl', 'test_exact_object_cache.tcl','post_synth.tcl','post_opt.tcl','common_cdc.tcl','board_audit.tcl','rom_audit.py','dynamic/dynamic_clock_constraints.tcl')

def verify_checkpoint(root, expected):
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('An explicit observed optimized checkpoint SHA256 is required')
    checkpoint = root/'diagnostic-run/implementation/optimized-unqualified.dcp'
    if not checkpoint.is_file() or sha(checkpoint) != expected:
        raise ValueError('Preserved optimized checkpoint missing or changed')
    return checkpoint

def prepare_post_opt(root, expected):
    record = check(root, 'implementation')
    checkpoint = verify_checkpoint(root, expected)
    here = Path(__file__).resolve().parent
    record.update(mode='cached-post-opt-only', optimized_checkpoint=str(checkpoint),
                  optimized_checkpoint_sha256=expected,
                  cache_overlay_sha256={n: sha(here/n) for n in CACHE_TOOLS},
                  qualification=False)
    return record



# Exact reviewed producer for the already-running adbe39c post-opt job.
REVIEWED_POST_PRODUCER = {'resume_diagnostic.py': 'f1900f81232ea204b0551156e88526954a9e48c389937e76fe919af63c9c1f81', 'resume_diagnostic.tcl': 'e3eb26d531a3431210eb53f1252f32b15acd36699b91abafd10d3177e1c75487'}
STAGES = {'optimized-checked-unqualified.dcp':'optimized', 'placed.dcp':'placed',
          'physical-optimized-unqualified.dcp':'physical', 'routed.dcp':'routed'}
POST_PROOFS = ('exact_object_cache.tcl','cached_post_opt.tcl','test_exact_object_cache.tcl',
               'post_synth.tcl','post_opt.tcl','common_cdc.tcl','board_audit.tcl','rom_audit.py','dynamic/dynamic_clock_constraints.tcl')

REVIEWED_PLACED_SHA = "2ad8c0d79f096627ee8e0c794f5cd4addb97b209f8aad1c286df06a789f5f35a"
REVIEWED_PLACED_TOOLS = {'exact_object_cache.tcl': '3e53d34432151cd74f81c24cfc01ee59df252c0f939d6f20a2da31c3967ca158', 'cached_post_opt.tcl': '024724a00b33df3ee985142b9eb6e26e7c992ba6c3251fac50be6753c83700df', 'test_exact_object_cache.tcl': '6844b5ba59458c4ca11718b92d95a2affc89c3e3b91809d4ca62ab09cc075043', 'post_synth.tcl': 'e26c26e3b59cc13aacbc0447c87947c6a6e787d16a55c6832730d78c8cb89e5d', 'post_opt.tcl': '58e4a82a92509e1c99ea7d1b1686484dde658e2261418c3fb1836a3c941f678c', 'common_cdc.tcl': '3e7e9689f355afa803aa623080a9880dac3ab77470085eaf58284c1313b82095', 'board_audit.tcl': '8d910a801831ef449003cebf00bf4bdb375ebf1bb1d059a3bb9af073fd1fd070', 'resume_diagnostic.py': 'bcaa3926681346d8c34f4fb926bd7280beaf3a63f3d1a623c3ba4698f676c7cc', 'resume_diagnostic.tcl': '5232228d730524235c687b74e619b061d710085261819edd23a7242fca253870', 'diagnostic.tcl': 'e159f6c199c11eba3c235627ac23b245392186ab4cd7832e64d117b4faa25af8'}

def continuation_tools():
    here=Path(__file__).resolve().parent
    return {n:sha(here/n) for n in (*POST_PROOFS,'resume_diagnostic.py','resume_diagnostic.tcl','diagnostic.tcl')}

def verify_continuation(root, checkpoint, expected, depth=0):
    if depth>6: raise ValueError('Continuation chain too deep')
    root=root.resolve(); checkpoint=checkpoint.resolve()
    if not checkpoint.is_relative_to(root/'diagnostic-run') or checkpoint.name not in STAGES:
        raise ValueError('Checkpoint outside reviewed diagnostic stage paths')
    if not re.fullmatch(r'[0-9a-f]{64}',expected) or sha(checkpoint)!=expected:
        raise ValueError('Continuation checkpoint SHA changed')
    current=check(root,'implementation')
    tools=continuation_tools()
    if checkpoint.name=='optimized-checked-unqualified.dcp':
        previous=json.loads((checkpoint.parent/'provenance.json').read_text())
        if previous.get('mode')!='cached-post-opt-only': raise ValueError('Not checked post-opt provenance')
        for key in ('original_manifest_sha256','profile_sha256','project_sha256','ooc_sha256'):
            if previous.get(key)!=current[key]: raise ValueError('Post-opt input provenance mismatch: '+key)
        verify_checkpoint(root,previous.get('optimized_checkpoint_sha256',''))
        recorded=previous.get('cache_overlay_sha256',{})
        for name in POST_PROOFS:
            if recorded.get(name)!=tools[name]: raise ValueError('Post-opt proof tool changed: '+name)
        producer={n:recorded.get(n) for n in REVIEWED_POST_PRODUCER}
        if producer not in (REVIEWED_POST_PRODUCER,{n:tools[n] for n in REVIEWED_POST_PRODUCER}):
            raise ValueError('Unreviewed post-opt producer pair')
        provenance=checkpoint.parent/'provenance.json'
    else:
        provenance=Path(str(checkpoint)+'.provenance.json')
        previous=json.loads(provenance.read_text())
        if previous.get('checkpoint_sha256')!=expected or previous.get('stage')!=STAGES[checkpoint.name]:
            raise ValueError('Stage seal mismatch')
        if previous.get('tool_sha256')!=tools:
            if not (checkpoint.name=='placed.dcp' and expected==REVIEWED_PLACED_SHA and previous.get('tool_sha256')==REVIEWED_PLACED_TOOLS):
                raise ValueError('Continuation tool identity changed')
        origin=Path(previous['input_checkpoint'])
        verify_continuation(root,origin,previous['input_sha256'],depth+1)
        if previous.get('input_provenance_sha256')!=sha(origin.parent/'provenance.json' if origin.name=='optimized-checked-unqualified.dcp' else Path(str(origin)+'.provenance.json')):
            raise ValueError('Continuation source provenance changed')
    return dict(status=current['status'],mode='place-route',qualification=False,
                original_manifest_sha256=current['original_manifest_sha256'],profile_sha256=current['profile_sha256'],
                input_checkpoint=str(checkpoint),input_sha256=expected,input_provenance_sha256=sha(provenance),
                start_stage=STAGES[checkpoint.name],tool_sha256=tools)

def seal_stage(root, out, stage):
    out=out.resolve()
    if not out.is_relative_to(root.resolve()/'diagnostic-run'): raise ValueError('Invalid output location')
    initial=json.loads((out/'provenance.json').read_text())
    validated=verify_continuation(root,Path(initial['input_checkpoint']),initial['input_sha256'])
    if validated!=initial: raise ValueError('Initial continuation provenance changed')
    names={v:k for k,v in STAGES.items()}
    if stage not in ('placed','physical','routed'): raise ValueError('Invalid stage to seal')
    checkpoint=out/names[stage]
    record=dict(validated,stage=stage,checkpoint_sha256=sha(checkpoint))
    seal=Path(str(checkpoint)+'.provenance.json')
    with seal.open('x') as f: json.dump(record,f,indent=2)
    return record

if __name__=='__main__':
    try:
        root=Path(sys.argv[1]).absolute()
        mode=sys.argv[2] if len(sys.argv)>2 else 'synthesis'
        if mode not in ('synthesis','implementation','seal-raw','post-opt','place-route','seal-stage'): raise ValueError('Invalid recovery mode')
        if mode=='post-opt' and len(sys.argv)!=4: raise ValueError('post-opt requires observed optimized SHA256')
        if mode=='place-route':
            if len(sys.argv)!=5: raise ValueError('place-route requires checkpoint path and SHA256')
            print(json.dumps(verify_continuation(root,Path(sys.argv[3]),sys.argv[4]),indent=2)); sys.exit(0)
        if mode=='seal-stage':
            if len(sys.argv)!=5: raise ValueError('seal-stage requires output and stage')
            print(json.dumps(seal_stage(root,Path(sys.argv[3]),sys.argv[4]),indent=2)); sys.exit(0)
        print(json.dumps(prepare_post_opt(root,sys.argv[3]) if mode=='post-opt' else seal_raw(root) if mode=='seal-raw' else check(root,mode),indent=2))
    except (ValueError, OSError) as exc: sys.exit(str(exc))
