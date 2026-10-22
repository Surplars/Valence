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
        if (phase!='tail-seal' and (out/'synthesized.dcp').exists()) or (out/'diagnostic-stage.json').exists():
            raise ValueError('Synthesis already completed; do not overwrite it')
        if not (out/'diagnostic-failure.txt').is_file() or not (out/'ip-synthesis.json').is_file():
            raise ValueError('Expected preserved failed stage and successful IP evidence')
    if phase=='implementation' and ('post-synth-tail-provenance.json' in stage.get('outputs_sha256',{}) or (out/'post-synth-tail-provenance.json').exists()):
        verify_tail(root,stage)
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
                recovery_tool_sha256={n:sha(here/n) for n in ('resume_diagnostic.py','resume_diagnostic.tcl','synthesize.tcl','diagnostic.tcl','cached_post_opt.tcl','exact_object_cache.tcl','test_exact_object_cache.tcl','post_synth.tcl','post_opt.tcl','common_cdc.tcl','board_audit.tcl','rom_audit.py','dynamic/dynamic_clock_constraints.tcl','dynamic/performance_targets.tcl')})

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


# Exact Oct 22 failed post-synth cut point, not a general failed-DCP admission.
TAIL_FAILED = "failed-resume-unqualified-1603981302391.dcp"
TAIL_ORIGIN_TOOLS = {'resume_diagnostic.py': '748716ea858da60a2a7099d45ce6d07d954961f3b1eae91b90779f948285b4db', 'resume_diagnostic.tcl': '0919278f804764f84eb72c5feef6f7d20f3904cbf1cffa7df5aa6a8e1c4004b0', 'synthesize.tcl': 'fbe51158a1dde27498073713b01775f077bd3a2cf49f79a04e5a92c233c1503e', 'diagnostic.tcl': '647487bb2472031aacf79c4cc6c34c8178a1bd9555aff6b21feecf16eeafd638', 'cached_post_opt.tcl': '024724a00b33df3ee985142b9eb6e26e7c992ba6c3251fac50be6753c83700df', 'exact_object_cache.tcl': '3e53d34432151cd74f81c24cfc01ee59df252c0f939d6f20a2da31c3967ca158', 'test_exact_object_cache.tcl': '6844b5ba59458c4ca11718b92d95a2affc89c3e3b91809d4ca62ab09cc075043', 'post_synth.tcl': 'e0ed7121068c400e7c8b013db33588731be0581ca1f0e6e97ce6a0281015c68f', 'post_opt.tcl': 'c63ce795842f131a36533deaa08fee76064b24e044b8874aff181659d0c64af5', 'common_cdc.tcl': '75cb49a48404ede21d46f9714427efcafbe129d66208e776e843274970fc7edc', 'board_audit.tcl': '645de72b13b67414f294baa4ee6de463e2e710bf83badce852f3a517d8cbfcb4', 'rom_audit.py': '6e7b503ec00a4ea5f049e44a3459225dc2aa43958371e8842787ca97adcc0ed7', 'dynamic/dynamic_clock_constraints.tcl': 'f76cf4e56fb79025ead6bd83b1dc917c248ee99b0ecd1a557e6faa28c9b2ffa6'}
TAIL_FROZEN_HELPERS = {'fpga/common/dynamic/performance_targets.tcl': '3a8515e50277ab9ead4de7b369b521ef6c53bdabcd58adfc15becbe1a3431460', 'fpga/common/management_constraints.tcl': '12904d9c831418cced8aa606c96261a09a99a2cee391f213dab49bf56b5416fe', 'fpga/common/post_synth.tcl': 'e0ed7121068c400e7c8b013db33588731be0581ca1f0e6e97ce6a0281015c68f', 'fpga/common/producer_common.tcl': '244766c61ff890fac95c9cd70fed3d809237188ddac183d36ec8f88d75f7e71e', 'fpga/common/dci_constraints.tcl': '944117d322db516632b8704a2c392d46747c533720482ad589582f07309d6c39', 'fpga/common/skew_scope.tcl': '06d068f209f3733b5364bd6c5c4e524bdeb8ce66d8d3acdfcbda6b1ddae7e908', 'fpga/common/media_constraints.tcl': 'f075c06c17f7ee834e0bcd2823cd7091b13b87c59ccae3c37c7e1575ca0657a0', 'fpga/common/inactive_zero_state.tcl': '7660ad503d0f56c435535dda2f3f4c6fb4357d2ce1d952a062993e7e06f2fa28', 'fpga/next/native_mac_roles.tcl': '236c0a2cdbb01d7743fde33793da85a51aa5d22f664dd03bcaaa26386cf9ff1e', 'fpga/inorder/bscan_timing_i1.tcl': 'f085e735a29f24420b412b1c81881b349d1a93410a4dc22abba7f7c43af2e4fc', 'fpga/next/check_jtag_chain.tcl': 'cfb30678a3b1e8c49a41038e68e565ce4346ea4b9ff524fb76d3843a50b5057f', 'fpga/zu15eg/trispeed_board_constraints.tcl': '4a2554a1a697df06659de71773afd2597e2d050ce86feaa25416aaf2865f1474', 'fpga/zu15eg/trispeed_quarter_constraints.tcl': '447052e8eab367da87975ee4431068d9cf38f72d44a16a912264a14ce4986051', 'fpga/zu15eg/native_quarter_clock_constraints.tcl': '72576b4b88a36e7c6c6ad66b1a4d6166cca9cec69b5655a44cf546e20f03493c', 'fpga/zu15eg/native-gmac-cdc-constraints.tcl': 'c2ba98162a8d6e753df690339869612b8fe09274987b1bff80304fd6a416c5a4', 'fpga/zu15eg/cdc_constraints.tcl': '0955b07d09c037a3a6fb4a2f3830a87424e07d8aa5ecfd05e4236080105df10d'}
TAIL_RAW_SHA = 'a425a8e2833df7366b00e82bdd874cffb5eb12dd5dcd6ec71946882382aaa6fe'
TAIL_RAW_PRODUCER_SHA = 'f66d4bbbc1952f8e91d6871b2ea74f4f5eec97b378e8c1934787c5ae2e921a7d'
TAIL_RAW_SEAL = ('53ae6e07afbf9b3e79f371fdd5d6fd8d7b9887f4fa9287a245886d4768aaf14a', 991)
TAIL_MANIFEST_SHA = 'd00944bb7b4dfbcdd48acc50986736f61e49c15fe5e5dc66c959bc19e7ce5122'
TAIL_BOUND = {
 'failed_checkpoint': ('14e1e5a04aac7c5f551bf7280c704a828249d8dea8c8a7860c25e20779473a86', 38761263),
 'failed_log': ('9c7dbdd1e83ede208db7ac4be70f8b74e42419c0be9edf290f5e6d6a3d1cba08', 331068),
 'run_evidence': ('b72888bd1d530b75a1dc40c4a1266e9ce240126fe2f2146002d2712a29960bf7', 2368),
 'bus_skew_scope': ('3eb4e18943dbc0436b5bad66347e66e6114acaf066b84dd65e398a07570ac8c0', 603346),
}
TAIL_EXTRA_TOOLS = ('dynamic/performance_targets.tcl','post_synth_tail_constraints.tcl')

def tail_tools():
    here=Path(__file__).resolve().parent
    return {n:sha(here/n) for n in (*TAIL_ORIGIN_TOOLS,*TAIL_EXTRA_TOOLS)}

def tail_inputs(root, request, current):
    request=request.resolve()
    config=json.loads(request.read_text())
    if set(config)!={'schema','files'} or config['schema']!='common-post-synth-tail-request-v1' or set(config['files'])!=set(TAIL_BOUND):
        raise ValueError('Exact tail request schema required')
    out=root/'diagnostic-run/synthesis'
    files={key:Path(value).resolve() for key,value in config['files'].items()}
    for key, (digest,size) in TAIL_BOUND.items():
        file=files[key]
        if not file.is_file() or (size is not None and file.stat().st_size!=size) or sha(file)!=digest:
            raise ValueError('Reviewed failed-run input changed: '+key)
    for key,name in [('failed_checkpoint',TAIL_FAILED),('run_evidence','resume-ooc-evidence-1543940431769.json'),('bus_skew_scope','bus-skew-scope.json')]:
        if files[key]!=(out/name).resolve(): raise ValueError('Wrong reviewed tail input location: '+key)
    if current['original_manifest_sha256']!=TAIL_MANIFEST_SHA or sha(root/'diagnostic.json')!=TAIL_MANIFEST_SHA or sha(out/'raw-synthesized-unqualified.dcp')!=TAIL_RAW_SHA:
        raise ValueError('Tail original raw/manifest changed')
    manifest=json.loads((root/'diagnostic.json').read_text())
    if manifest['configuration']['clock_profile']!='boot50-dynamic': raise ValueError('Tail profile not dynamic')
    for name,digest in TAIL_FROZEN_HELPERS.items():
        if sha(root/name)!=digest: raise ValueError('Historical frozen helper changed: '+name)
    previous=json.loads(files['run_evidence'].read_text())
    if previous.get('mode')!='post-only' or previous.get('control_lemma')!=1 or previous.get('recovery_tool_sha256')!=TAIL_ORIGIN_TOOLS:
        raise ValueError('Wrong historical producer or cut point')
    for key in ('status','original_manifest_sha256','profile_sha256','project_sha256','ooc_sha256'):
        if previous.get(key)!=current[key]: raise ValueError('Historical tail binding changed: '+key)
    raw_seal=out/'raw-synthesized-unqualified.json'
    if (sha(raw_seal),raw_seal.stat().st_size)!=TAIL_RAW_SEAL: raise ValueError('Original raw producer seal changed')
    raw=json.loads(raw_seal.read_text())
    if raw.get('synthesis_tool_sha256')!=TAIL_RAW_PRODUCER_SHA:
        raise ValueError('Historical raw synthesis producer changed')
    log=files['failed_log'].read_text(errors='replace')
    fail='DYNAMIC_TARGET fixed clock changed u_soc/rawUartClock'
    required=('COMMON_CDC_DYNAMIC_SOURCE_SCOPES scopes=153',
              'COMMON_MANAGEMENT_BOUNDED scoped_reset_assertion_only functional_recovery_removal_timed',
              'common_skew_end','native_dynamic_performance_targets',fail)
    position=-1
    for marker in required:
        position=log.find(marker,position+1)
        if position<0: raise ValueError('Missing ordered reviewed tail marker: '+marker)
    scope=json.loads(files['bus_skew_scope'].read_text())
    if scope.get('phase')!='synthesis' or scope.get('profile_sha256')!=current['profile_sha256'] or not scope.get('scopes'):
        raise ValueError('Wrong original exact bus-skew scope')
    return dict(request=str(request), request_sha256=sha(request),
                inputs={key:dict(path=str(file),sha256=sha(file),size=file.stat().st_size) for key,file in files.items()},
                raw_sha256=TAIL_RAW_SHA, raw_seal_sha256=sha(out/'raw-synthesized-unqualified.json'),
                historical_tools=TAIL_ORIGIN_TOOLS, frozen_helpers=TAIL_FROZEN_HELPERS)

def prepare_tail(root, request):
    current=check(root,'synthesis')
    origin=tail_inputs(root,request,current)
    return dict(current,mode='post-synth-tail-only',qualification=False,tail_origin=origin,
                recovery_tool_sha256=tail_tools())

def retained_scope_check(root, exported_path=None):
    out=root/'diagnostic-run/synthesis'
    original=json.loads((out/'bus-skew-scope.json').read_text())['scopes']
    exported=json.loads((exported_path or out/'tail-retained-constraints.json').read_text())
    if exported.get('schema_version')!=1: raise ValueError('Wrong retained constraints schema')
    actual=exported.get('rows')
    if not isinstance(actual,list) or not actual: raise ValueError('Empty native retained constraints')
    def key(row):
        if not row.get('from') or not row.get('to'): raise ValueError('Empty retained scope endpoint')
        return (float(row['budget_ns']),tuple(sorted(row['from'])),tuple(sorted(row['to'])))
    skew={key(row) for row in actual if row['kind']=='bus_skew' and row.get('from_type')=='pin' and row.get('to_type')=='pin'}
    maximum={key(row) for row in actual if row['kind']=='max_delay' and row.get('datapath_only') is True and row.get('from_type')=='pin' and row.get('to_type')=='pin'}
    for row in original:
        if key(row) not in skew or key(row) not in maximum:
            raise ValueError('Original bus-skew/max-delay scope not retained')
    return len(original)

def retained_text_check(root, xdc, output, expected_sha):
    """Text-only preview; no Vivado, checkpoint open, receipt, or qualification."""
    scope=root/'diagnostic-run/synthesis/bus-skew-scope.json'
    if (sha(scope),scope.stat().st_size)!=TAIL_BOUND['bus_skew_scope']:
        raise ValueError('Original scope file changed')
    if not re.fullmatch(r'[0-9a-f]{64}',expected_sha) or sha(xdc)!=expected_sha:
        raise ValueError('Observed exported XDC SHA256 mismatch')
    if output.exists(): raise ValueError('Preserve existing text-preview output')
    try:
        import tkinter
    except ImportError as exc:
        raise ValueError('Text preview needs Python standard tkinter Tcl; no Vivado was started') from exc
    tcl=tkinter.Tcl()
    helper=Path(__file__).resolve().parent/'post_synth_tail_constraints.tcl'
    try:
        tcl.call('source',str(helper))
        rows=tcl.call('post_synth_tail_constraints::read_rows',str(xdc),1)
        tcl.call('post_synth_tail_constraints::write_rows',str(output),rows)
    except tkinter.TclError as exc:
        raise ValueError(str(exc)) from exc
    count=retained_scope_check(root,output)
    data=json.loads(output.read_text())
    return dict(status='TEXT_SCOPE_PRESENCE_ONLY_NOT_NATIVE_QUALIFICATION',
                retained_bus_scopes=count,selected_counts=data['selected_counts'],
                parsed_rows=len(data['rows']),unsupported_rows=len(data['unsupported']),
                xdc_sha256=expected_sha,scope_sha256=sha(scope),output_sha256=sha(output),
                parser_sha256=sha(helper),falsepath_or_exception_dominance_proven=False)

def seal_tail(root, request):
    out=root/'diagnostic-run/synthesis'
    current=check(root,'tail-seal')
    origin=tail_inputs(root,request,current)
    initial=json.loads((out/'post-synth-tail-start.json').read_text())
    if initial!=dict(current,mode='post-synth-tail-only',qualification=False,tail_origin=origin,recovery_tool_sha256=tail_tools()):
        raise ValueError('Tail inputs/tools changed during native work')
    native=json.loads((out/'post-synth-tail-native.json').read_text())
    if native!={'status':'TARGET_CHECKS_RETURNED','version':'2025.2','part':'xczu15eg-ffvb1156-2-i','top':'soc_top_common_ddr'}:
        raise ValueError('Native tail checks did not complete on exact tool/part/top')
    count=retained_scope_check(root)
    outputs=('synthesized.dcp','dynamic-performance-target-clocks.rpt','tail-retained.xdc',
             'tail-retained-constraints.json','post-synth-tail-native.json','utilization.rpt')
    if any(not (out/name).is_file() or not (out/name).stat().st_size for name in outputs):
        raise ValueError('Missing fresh native tail output')
    record=dict(initial,retained_bus_scopes=count,
                outputs_sha256={name:sha(out/name) for name in outputs})
    path=out/'post-synth-tail-provenance.json'
    with path.open('x') as f: json.dump(record,f,indent=2); f.write('\n')
    return record

def verify_tail(root, stage):
    out=root/'diagnostic-run/synthesis'
    path=out/'post-synth-tail-provenance.json'
    record=json.loads(path.read_text())
    if stage.get('outputs_sha256',{}).get(path.name)!=sha(path): raise ValueError('Tail provenance not sealed by diagnostic stage')
    if record.get('profile_sha256')!=stage.get('profile_sha256') or record.get('mode')!='post-synth-tail-only' or record.get('qualification') is not False or record.get('recovery_tool_sha256')!=tail_tools():
        raise ValueError('Tail producer identity changed')
    current={key:record[key] for key in ('status','original_manifest_sha256','profile_sha256','project_sha256','ooc_sha256')}
    if record.get('tail_origin')!=tail_inputs(root,Path(record['tail_origin']['request']),current):
        raise ValueError('Tail origin changed')
    for name,digest in record['outputs_sha256'].items():
        if sha(out/name)!=digest: raise ValueError('Tail output changed: '+name)
    if retained_scope_check(root)!=record.get('retained_bus_scopes'): raise ValueError('Retained scope census changed')

if __name__=='__main__':
    try:
        root=Path(sys.argv[1]).absolute()
        mode=sys.argv[2] if len(sys.argv)>2 else 'synthesis'
        if mode not in ('synthesis','implementation','seal-raw','post-opt','place-route','seal-stage','post-synth-tail','seal-tail','retained-tail','retained-text'): raise ValueError('Invalid recovery mode')
        if mode=='retained-text':
            if len(sys.argv)!=6: raise ValueError('retained-text requires XDC, fresh output JSON, observed XDC SHA256')
            print(json.dumps(retained_text_check(root,Path(sys.argv[3]),Path(sys.argv[4]),sys.argv[5]),indent=2)); sys.exit(0)
        if mode=='retained-tail':
            if len(sys.argv)!=3: raise ValueError('Retained check accepts only root')
            print(json.dumps({'retained_bus_scopes':retained_scope_check(root)})); sys.exit(0)
        if mode in ('post-synth-tail','seal-tail'):
            if len(sys.argv)!=4: raise ValueError('Tail requires exact request JSON')
            print(json.dumps(prepare_tail(root,Path(sys.argv[3])) if mode=='post-synth-tail' else seal_tail(root,Path(sys.argv[3])),indent=2)); sys.exit(0)
        if mode=='post-opt' and len(sys.argv)!=4: raise ValueError('post-opt requires observed optimized SHA256')
        if mode=='place-route':
            if len(sys.argv)!=5: raise ValueError('place-route requires checkpoint path and SHA256')
            print(json.dumps(verify_continuation(root,Path(sys.argv[3]),sys.argv[4]),indent=2)); sys.exit(0)
        if mode=='seal-stage':
            if len(sys.argv)!=5: raise ValueError('seal-stage requires output and stage')
            print(json.dumps(seal_stage(root,Path(sys.argv[3]),sys.argv[4]),indent=2)); sys.exit(0)
        print(json.dumps(prepare_post_opt(root,sys.argv[3]) if mode=='post-opt' else seal_raw(root) if mode=='seal-raw' else check(root,mode),indent=2))
    except (ValueError, OSError) as exc: sys.exit(str(exc))
