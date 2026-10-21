import hashlib
from pathlib import Path
import tempfile
import unittest
import resume_cached_post_opt as resume

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
            self.assertIn(name,resume.TOOLS)
        source=Path(__file__).with_name('resume_cached_post_opt.tcl').read_text()
        for command in ('synth_design','opt_design','place_design','route_design','launch_runs'):
            self.assertNotIn(command,source)
        self.assertLess(source.index('resume_cached_post_opt.py'),source.index('open_checkpoint'))
        self.assertLess(source.index('open_checkpoint'),source.index('source [file join $cached_resume_tools cached_post_opt.tcl]'))
