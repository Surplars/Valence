import copy, json, tempfile, unittest, subprocess
from pathlib import Path
from unittest.mock import patch
import resume_diagnostic as r

class TailTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.out=self.root/'diagnostic-run/synthesis';self.out.mkdir(parents=True)
        (self.root/'diagnostic.json').write_text(json.dumps({'configuration':{'clock_profile':'boot50-dynamic'}}))
        (self.out/'raw-synthesized-unqualified.dcp').write_bytes(b'raw')
        (self.out/'raw-synthesized-unqualified.json').write_text(json.dumps({'synthesis_tool_sha256':r.TAIL_RAW_PRODUCER_SHA}))
        self.current=dict(status='DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM',mode='post-only',control_lemma=1,
            original_manifest_sha256=r.sha(self.root/'diagnostic.json'),profile_sha256='profile',project_sha256='project',ooc_sha256={'all3':'realfixture'},recovery_tool_sha256={'current':'tools'})
        self.files={'failed_checkpoint':self.out/r.TAIL_FAILED,'failed_log':self.root/'failed.log',
                    'run_evidence':self.out/'resume-ooc-evidence-1543940431769.json','bus_skew_scope':self.out/'bus-skew-scope.json'}
        self.files['failed_checkpoint'].write_bytes(b'failed-checkpoint')
        self.files['failed_log'].write_text('COMMON_CDC_DYNAMIC_SOURCE_SCOPES scopes=153\nCOMMON_MANAGEMENT_BOUNDED scoped_reset_assertion_only functional_recovery_removal_timed\ncommon_skew_end\nnative_dynamic_performance_targets\nDYNAMIC_TARGET fixed clock changed u_soc/rawUartClock\n')
        previous=dict(self.current,recovery_tool_sha256=r.TAIL_ORIGIN_TOOLS)
        self.files['run_evidence'].write_text(json.dumps(previous))
        self.scope=dict(budget_ns=4.0,**{'from':['lane/s[0]/C'],'to':['lane/d[0]/D']})
        self.files['bus_skew_scope'].write_text(json.dumps(dict(phase='synthesis',profile_sha256='profile',scopes=[self.scope])))
        self.bound={key:(r.sha(file),file.stat().st_size) for key,file in self.files.items()}
        self.request=self.root/'request.json';self.request.write_text(json.dumps(dict(schema='common-post-synth-tail-request-v1',files={k:str(v) for k,v in self.files.items()})))
        for name,value in [('TAIL_BOUND',self.bound),('TAIL_FROZEN_HELPERS',{}),('TAIL_RAW_SHA',r.sha(self.out/'raw-synthesized-unqualified.dcp')),('TAIL_MANIFEST_SHA',r.sha(self.root/'diagnostic.json')),('TAIL_RAW_SEAL',(r.sha(self.out/'raw-synthesized-unqualified.json'),(self.out/'raw-synthesized-unqualified.json').stat().st_size))]:
            patcher=patch.object(r,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.check=patch.object(r,'check',return_value=self.current);self.check.start();self.addCleanup(self.check.stop)
        self.tools=patch.object(r,'tail_tools',return_value={'reviewed':'new-tools'});self.tools.start();self.addCleanup(self.tools.stop)
    def rebind(self,key):
        file=self.files[key];self.bound[key]=(r.sha(file),file.stat().st_size)
    def prepare(self):return r.prepare_tail(self.root,self.request)
    def retained(self):
        rows=[dict(self.scope,kind=k,from_type='pin',to_type='pin',datapath_only=k=='max_delay') for k in ['bus_skew','max_delay']]
        (self.out/'tail-retained-constraints.json').write_text(json.dumps(dict(schema_version=1,rows=rows)));return rows
    def test_exact_fixture_passes_and_new_helper_is_bound(self):
        record=self.prepare();self.assertEqual(record['mode'],'post-synth-tail-only');self.assertFalse(record['qualification']);self.assertIn('dynamic/performance_targets.tcl',r.TAIL_EXTRA_TOOLS)
    def test_every_failed_input_mutation_rejected(self):
        for key,path in self.files.items():
            with self.subTest(key=key):
                old=path.read_bytes();path.write_bytes(old+b'x')
                with self.assertRaisesRegex(ValueError,'input changed'):self.prepare()
                path.write_bytes(old)
    def test_wrong_raw_manifest_and_raw_producer_rejected(self):
        for path in [self.out/'raw-synthesized-unqualified.dcp',self.root/'diagnostic.json',self.out/'raw-synthesized-unqualified.json']:
            with self.subTest(path=path):
                old=path.read_bytes();path.write_text('{}')
                with self.assertRaises(ValueError):self.prepare()
                path.write_bytes(old)
    def test_historical_tool_omission_or_substitution_rejected(self):
        file=self.files['run_evidence'];saved=file.read_text()
        for mode in ['omit','substitute']:
            data=json.loads(saved)
            if mode=='omit':data['recovery_tool_sha256'].pop('common_cdc.tcl')
            else:data['recovery_tool_sha256']['common_cdc.tcl']='invented-current-tool'
            file.write_text(json.dumps(data));self.rebind('run_evidence')
            with self.assertRaisesRegex(ValueError,'historical producer'):self.prepare()
    def test_marker_missing_or_reordered_rejected(self):
        file=self.files['failed_log'];lines=file.read_text().splitlines()
        for values in [lines[:-1],lines[1:],list(reversed(lines))]:
            file.write_text('\n'.join(values));self.rebind('failed_log')
            with self.assertRaisesRegex(ValueError,'marker'):self.prepare()
    def test_wrong_source_profile_and_non_tail_scope_rejected(self):
        file=self.files['bus_skew_scope'];data=json.loads(file.read_text());data['phase']='implementation';file.write_text(json.dumps(data));self.rebind('bus_skew_scope')
        with self.assertRaisesRegex(ValueError,'scope'):self.prepare()
    def test_wrong_frozen_helper_rejected(self):
        file=self.root/'helper';file.write_text('changed')
        with patch.object(r,'TAIL_FROZEN_HELPERS',{'helper':'wrong'}):
            with self.assertRaisesRegex(ValueError,'helper'):self.prepare()
    def test_retained_scope_endpoint_budget_type_and_flag_negatives(self):
        rows=self.retained();self.assertEqual(r.retained_scope_check(self.root),1)
        mutations=[lambda x:x.pop(),lambda x:x[0].update(budget_ns=5),lambda x:x[1].update(to=['other/D']),lambda x:x[1].update(datapath_only=False),lambda x:x[0].update(from_type='port')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed=copy.deepcopy(rows);mutate(changed)
                (self.out/'tail-retained-constraints.json').write_text(json.dumps(dict(schema_version=1,rows=changed)))
                with self.assertRaises(ValueError):r.retained_scope_check(self.root)
    def test_no_seal_without_native_checks_and_fresh_outputs(self):
        (self.out/'post-synth-tail-start.json').write_text(json.dumps(self.prepare()))
        with self.assertRaises(OSError):r.seal_tail(self.root,self.request)
        (self.out/'post-synth-tail-native.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Native tail'):r.seal_tail(self.root,self.request)
    def test_success_seal_and_diagnostic_hash_binding(self):
        (self.out/'post-synth-tail-start.json').write_text(json.dumps(self.prepare()))
        (self.out/'post-synth-tail-native.json').write_text(json.dumps(dict(status='TARGET_CHECKS_RETURNED',version='2025.2',part='xczu15eg-ffvb1156-2-i',top='soc_top_common_ddr')))
        self.retained()
        for name in ['synthesized.dcp','dynamic-performance-target-clocks.rpt','tail-retained.xdc','utilization.rpt']:(self.out/name).write_bytes(b'native-output')
        record=r.seal_tail(self.root,self.request);self.assertEqual(record['retained_bus_scopes'],1)
        stage=dict(profile_sha256='profile',outputs_sha256={'post-synth-tail-provenance.json':r.sha(self.out/'post-synth-tail-provenance.json')})
        r.verify_tail(self.root,stage)
        stage['outputs_sha256']['post-synth-tail-provenance.json']='forged'
        with self.assertRaisesRegex(ValueError,'sealed'):r.verify_tail(self.root,stage)
        with self.assertRaises(FileExistsError):r.seal_tail(self.root,self.request)
    def test_tail_branch_has_no_collect_or_synthesis_and_target_precedes_checkpoint(self):
        text=Path(r.__file__).with_suffix('.tcl').read_text();a=text.index('    if {$phase eq "post-synth-tail"} {');b=text.index('    } elseif {$phase eq "place-route"}',a);branch=text[a:b]
        self.assertNotIn('source $valence(post_synth_constraints)',branch)
        self.assertNotIn('common_cdc::collect',branch)
        self.assertLess(branch.index('native_dynamic_performance_targets'),branch.index('write_checkpoint synthesized.dcp'))
        self.assertLess(branch.index('retained-tail'),branch.index('write_checkpoint synthesized.dcp'))
        self.assertLess(branch.index('seal-tail'),branch.index('common_receipt'))
        self.assertNotIn('file copy',branch)
    def test_native_tail_control_flow_never_promotes_a_failed_gate(self):
        code=Path(r.__file__).with_suffix('.tcl').read_text()
        for failure in ['none','target','retained','version','mutation']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                base=Path(temp);(base/'diagnostic-run/synthesis').mkdir(parents=True)
                pre=r"""
set ::failure FAILURE
set argv [list config post-synth-tail request.json]
set valence(root) {ROOT}
set valence(diagnosticOnly) 1
set valence(clock_profile) boot50-dynamic
set valence(threads) 8
set valence(profile_sha256) fixture
set valence(python) python
proc source {path} {
 if {$path eq "config"} {return}
 switch -glob $path {
  *producer_common.tcl {
   proc common_record {args} {puts RECORDED}
   proc common_receipt {} {puts RECEIPT}
  }
  *performance_targets.tcl {
   proc native_dynamic_performance_targets {} {
    if {$::failure eq "target"} {error TARGET_NEGATIVE}
    if {$::failure eq "mutation"} {synth_design}
    puts TARGET_DONE
   }
  }
  *post_synth_tail_constraints.tcl {
   proc post_synth_tail_retained_constraints {} {puts EXPORTED}
  }
  default {error "unexpected source $path"}
 }
}
proc set_param {args} {}
proc get_param {args} {return 8}
proc version {args} {if {$::failure eq "version"} {return 2025.1};return 2025.2}
proc current_design {} {return design}
proc get_property {name object} {if {$name eq "PART"} {return xczu15eg-ffvb1156-2-i};if {$name eq "NAME"} {return soc_top_common_ddr};error PROP}
proc open_checkpoint {path} {if {[file tail $path] ne "failed-resume-unqualified-1603981302391.dcp"} {error WRONG_DCP};puts OPENED_EXACT}
proc write_checkpoint {path} {if {$path eq "synthesized.dcp"} {puts CHECKED_WRITE}}
proc report_utilization {args} {puts UTIL}
proc close_project {} {}
proc synth_design {args} {error UNEXPECTED_UNGUARDED_SYNTH}
proc exec {args} {
 if {[lindex $args end] eq "retained-tail"} {
  if {$::failure eq "retained"} {error RETAINED_NEGATIVE}
  puts RETAINED_DONE
 }
 if {[lsearch -exact $args seal-tail]>=0} {puts SEALED}
 return {{} }
}
""".replace('FAILURE',failure).replace('ROOT',str(base))
                result=subprocess.run(['tclsh'],input=pre+'\n'+code,text=True,capture_output=True,cwd=temp)
                if failure=='none':
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertLess(result.stdout.index('TARGET_DONE'),result.stdout.index('CHECKED_WRITE'))
                    self.assertLess(result.stdout.index('RETAINED_DONE'),result.stdout.index('CHECKED_WRITE'))
                    self.assertLess(result.stdout.index('SEALED'),result.stdout.index('RECEIPT'))
                else:
                    self.assertNotEqual(result.returncode,0)
                    self.assertNotIn('CHECKED_WRITE',result.stdout)
                    self.assertNotIn('RECEIPT',result.stdout)

if __name__=='__main__':unittest.main()
