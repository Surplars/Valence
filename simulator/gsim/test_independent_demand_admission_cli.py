import tempfile
import unittest
import test_ddr_write_collection_cli as common


class IndependentDemandAdmissionCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_explicit_forwarding_and_frozen_recommended_default(self):
        with tempfile.TemporaryDirectory(prefix='demand-admission-cli-') as tmp:
            options = ['--virtual-ram-load-precheck', '--canonical-virtual-store-overlap',
                       '--independent-demand-admission']
            native = self.call('fpga/next/export.py', ['--output', tmp+'/absent', *options])
            board = self.call('simulator/gsim/fpga_next_board.py',
                              ['--tag', 'demand-cli', '--preflight-only', '--variant', 'selected', *options])
            self.assertEqual(native['command'][5:], board['plan']['parameters'])
            self.assertIs(native['configuration']['independent_demand_admission'], True)
            default = self.call('fpga/next/performance.py', ['--output', tmp+'/absent'])
            self.assertNotIn('independent_demand_admission', default['configuration'])

    def test_missing_authority_duplicate_and_assignment_rejected_before_output(self):
        with tempfile.TemporaryDirectory(prefix='demand-admission-bad-') as tmp:
            for bad in (['--independent-demand-admission'],
                        ['--virtual-ram-load-precheck', '--independent-demand-admission'],
                        ['--independent-demand-admission', '--independent-demand-admission'],
                        ['--independent-demand-admission=false']):
                self.call('fpga/next/export.py', ['--output', tmp+'/absent', *bad], False)
                self.call('simulator/gsim/fpga_next_board.py',
                          ['--tag', 'demand-bad', '--preflight-only', *bad], False)


if __name__ == '__main__':
    unittest.main()
