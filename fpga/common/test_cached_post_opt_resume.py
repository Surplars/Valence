import hashlib
from pathlib import Path
import tempfile
import unittest
import resume_diagnostic as resume

class CachedPostOptResumeTests(unittest.TestCase):
    def test_explicit_checkpoint_digest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=root/'diagnostic-run/implementation/optimized-unqualified.dcp'
            p.parent.mkdir(parents=True);p.write_bytes(b'checkpoint')
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(resume.verify_checkpoint(root,digest),p)
            for wrong in ('', '0'*64, digest.upper()):
                with self.assertRaises(ValueError):resume.verify_checkpoint(root,wrong)
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):resume.verify_checkpoint(root,digest)
    def test_all_cache_tools_bound_and_no_mutation(self):
        for name in ('exact_object_cache.tcl','cached_post_opt.tcl','test_exact_object_cache.tcl'):
            self.assertIn(name,resume.CACHE_TOOLS)
        source=Path(__file__).with_name('resume_diagnostic.tcl').read_text()
        for command in ('synth_design','opt_design','place_design','route_design','launch_runs'):
            self.assertNotIn('common_design_step '+command,source)
            self.assertNotIn('\n        '+command+' ',source)
        self.assertLess(source.index('resume_diagnostic.py'),source.index('open_checkpoint'))
        self.assertLess(source.index('open_checkpoint'),source.index('source [file join $recovery_tools cached_post_opt.tcl]'))

    def test_default_entry_paths_enable_cache(self):
        root=Path(__file__).parent
        self.assertIn('common_exact_cache::enable',(root/'synthesize.tcl').read_text())
        for name in ('implement.tcl','diagnostic.tcl'):
            text=(root/name).read_text()
            self.assertIn('cached_post_opt.tcl',text)
            self.assertNotIn('source $valence(post_opt_constraints)',text)
        for name in ('post_synth.tcl','post_opt.tcl','common_cdc.tcl','board_audit.tcl'):
            self.assertIn(name,resume.CACHE_TOOLS)
