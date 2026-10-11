import tempfile
import unittest
import test_ddr_write_collection_cli as common

class TranslationHitFlowCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_explicit_forwarding_and_default_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='translation-hit-cli-') as tmp:
            options=['--virtual-ram-load-precheck','--translation-hit-flow']
            native=self.call('fpga/next/export.py',['--output',tmp+'/absent',*options])
            board=self.call('simulator/gsim/fpga_next_board.py',[
                '--tag','translation-hit-cli','--preflight-only','--variant','selected',*options])
            self.assertEqual(native['command'][5:],board['plan']['parameters'])
            self.assertIs(native['configuration']['translation_hit_flow'],True)
            self.assertEqual(native['command'].count('--translation-hit-flow'),1)
            default=self.call('fpga/next/performance.py',['--output',tmp+'/absent'])
            self.assertNotIn('translation_hit_flow',default['configuration'])

    def test_duplicate_and_assignment_rejected(self):
        with tempfile.TemporaryDirectory(prefix='translation-hit-bad-') as tmp:
            for bad in (['--translation-hit-flow','--translation-hit-flow'],['--translation-hit-flow=false']):
                self.call('fpga/next/export.py',['--output',tmp+'/absent',*bad],False)
                self.call('simulator/gsim/fpga_next_board.py',['--tag','hit-bad','--preflight-only',*bad],False)

if __name__=='__main__':unittest.main()
