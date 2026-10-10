"""Fixed preset host contracts; runtime/native qualification stays separately bound."""
import contextlib,copy,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import export as exporter
import performance
ROOT=Path(__file__).resolve().parents[2]
EXPECTED=json.loads((ROOT/'simulator/gsim/posted_board_lineage/expected-profile.json').read_text())
PROFILES=json.loads((ROOT/'fpga/next/performance-profile.json').read_text())
CONTROLS={'on':[], 'legacy-posted':['--disable-posted-prefetch'], 'off':['--disable-posted']}
FLAGS={'on':['--posted-store-merge','--posted-prefetch-coexistence','--posted-prefetch-head-offer'],
       'legacy-posted':['--posted-store-merge'], 'off':[]}

class PerformancePresetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'native'
    def preflight(self,*options,entry=performance.main):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):entry(['--output',str(self.output),*options])
        self.assertFalse(self.output.exists());return json.loads(stream.getvalue())
    def test_exact_complete_profiles_and_native_commands(self):
        for mode,control in CONTROLS.items():
            result=self.preflight(*control)
            self.assertEqual(result['status'],'PREFLIGHT_ONLY')
            self.assertEqual(result['command'],['mill','-i','IonSoC.test.runMain','ooo.FpgaNextMain',
                str(self.output/'rtl'),*EXPECTED['native_reference']['command'][5:],*FLAGS[mode],'--canonical-virtual-store-overlap'])
            profile=result['configuration'];self.assertEqual(profile,PROFILES[mode]);self.assertEqual(len(profile),66)
            digest=performance.LEGACY_PROFILE_SHA256 if mode=='legacy-posted' else performance.PROFILE_SHA256[mode=='on']
            self.assertEqual(hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode()).hexdigest(),digest)
            for flag in ('translated_response_empty_flow','prechecked_data_flow'):self.assertFalse(profile[flag])
            self.assertEqual(profile['posted_store_merge'],mode!='off')
            self.assertEqual(profile['posted_prefetch_coexistence'],mode=='on')
            self.assertEqual(profile['posted_prefetch_head_offer'],mode=='on')
    def test_controls_change_only_three_named_features(self):
        off=self.preflight('--disable-posted')
        for mode in ('on','legacy-posted'):
            value=self.preflight(*CONTROLS[mode]);profile=value['configuration']
            for key in ('posted_store_merge','posted_prefetch_coexistence','posted_prefetch_head_offer'):
                suffix='-'+key.replace('_','-')
                self.assertEqual(profile['name'].count(suffix),int(profile[key]))
                profile['name']=profile['name'].replace(suffix,'');profile[key]=False
            self.assertEqual(profile,off['configuration'])
            self.assertEqual(value['command'],off['command'][:-1]+FLAGS[mode]+['--canonical-virtual-store-overlap'])
    def test_disable_posted_closes_all_dependencies(self):
        result=self.preflight('--disable-posted')
        for flag in FLAGS['on']:self.assertNotIn(flag,result['command'])
    def test_contradictory_controls_overrides_and_abbreviations_rejected(self):
        overrides=[['--disable-posted','--disable-posted-prefetch']]
        overrides += [[flag] for flag in ['--reference','--storage-candidate','--posted-store-merge',
            '--posted-prefetch-coexistence','--posted-prefetch-head-offer','--prechecked-data-flow',
            '--translated-response-empty-flow','--lsu-entries=2','--data-translation-entries=8',
            '--dma-line-entries=2','--dma-line-yield-cycles=4','--prefetch-candidate-cycles=3',
            '--prefetch-break-on-store','--experimental-trispeed-ethernet','--experimental-jtag-bscan=1',
            '--disable','--disable-posted-prefetch-head-offer','--out','--']]
        for options in overrides:
            with self.subTest(options=options),contextlib.redirect_stderr(io.StringIO()),mock.patch.object(exporter,'main') as call:
                with self.assertRaises(SystemExit) as error:performance.main(['--output',str(self.output),*options])
                self.assertEqual(error.exception.code,2);call.assert_not_called()
    def test_legal_but_unqualified_expansion_fails_before_output_or_mill(self):
        variants=[tuple('2' if item=='4' else item for item in performance.OPTIONS)]
        variants += [tuple(item for item in performance.OPTIONS if item!=flag) for flag in
            ('--prepared-store-lookahead','--physical-load-ingress-flow','--virtual-ram-load-precheck',
             '--fetch-previous-packet','--load-order-older-retire')]
        variants += [(*performance.OPTIONS,'--translated-response-empty-flow')]
        for variant in variants:
            with self.subTest(variant=variant),mock.patch.object(performance,'OPTIONS',variant),\
                    mock.patch.object(exporter,'sources') as sources,mock.patch.object(exporter.subprocess,'run') as emit,\
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):performance.main(['--output',str(self.output),'--emit'])
                sources.assert_not_called();emit.assert_not_called();self.assertFalse(self.output.exists())
    def test_new_feature_false_drift_rejected(self):
        original=exporter.main
        def omit_head(args,expected_profile_sha256=None):
            return original([x for x in args if x!='--posted-prefetch-head-offer'],expected_profile_sha256)
        with mock.patch.object(exporter,'main',side_effect=omit_head),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):performance.main(['--output',str(self.output),'--emit'])
        self.assertFalse(self.output.exists())
    def test_full_geometry_drift_rejected(self):
        baseline=json.loads((ROOT/'fpga/next/baseline.json').read_text())
        for field in ('issue_width','cache_read_mshrs','cache_writeback_entries','cache_ways'):
            changed=copy.deepcopy(baseline);changed['profile'][field]+=1
            with self.subTest(field=field),mock.patch.object(exporter.json,'loads',return_value=changed),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):performance.main(['--output',str(self.output)])
                self.assertFalse(self.output.exists())
    def test_generic_defaults_stay_off(self):
        result=self.preflight(entry=exporter.main)
        for flag in ('posted_store_merge','posted_prefetch_coexistence','posted_prefetch_head_offer'):self.assertFalse(result[flag])
        self.assertEqual(result['configuration']['lsu_entries'],2)
        self.assertEqual(result['configuration']['data_translation_entries'],8)
        self.assertEqual(result['command'][5:],['--selected','--data-translation-entries=8'])
    def test_preset_and_full_profile_are_bound_into_source_receipt(self):
        for path in ('fpga/next/performance.py','fpga/next/performance-profile.json'):self.assertIn(path,exporter.sources())
if __name__=='__main__':unittest.main()
