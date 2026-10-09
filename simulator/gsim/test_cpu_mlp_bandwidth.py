"""Host-only plan guards; hardware execution is the separately receipted runner."""
import unittest
import cpu_mlp_bandwidth_board as mlp
import cpu_bandwidth_flow_board as flow


class CapacityPlanTests(unittest.TestCase):
    def test_only_capacity_flag_differs(self):
        common = dict(dma_line_transfers=True, dma_line_entries=4)
        two = mlp.expected_model_plan(1, lsu_entries=2, **common)
        four = mlp.expected_model_plan(1, lsu_entries=4, **common)
        self.assertEqual(two, flow.expected_model_plan(1, **common))
        self.assertEqual(four['parameters'], ['--selected', '--dma-line-transfers',
            '--dma-line-entries=4', '--lsu-entries=4', '--physical-load-ingress-flow'])
        adjusted = dict(four, parameters=[p for p in four['parameters'] if p != '--lsu-entries=4'])
        self.assertEqual(two, adjusted)

    def test_reject_invalid_capacity(self):
        for count in (0, 1, 3, 8):
            with self.subTest(count=count), self.assertRaises(RuntimeError):
                mlp.expected_model_plan(1, lsu_entries=count)

    def test_fixed_current_dma_profile(self):
        args = mlp.arguments(['--tag', 'host-test'])
        self.assertEqual((args.dma_line_transfers, args.dma_line_entries, args.dma_line_yield_cycles),
                         (True, 4, 0))
        for option, value in (('--dma-line-entries', '2'), ('--dma-line-yield-cycles', '4')):
            with self.subTest(option=option), self.assertRaises(SystemExit):
                mlp.arguments(['--tag', 'host-test', option, value])


if __name__ == '__main__':
    unittest.main()
