import unittest
import cpu_retire_prefix_board as prefix
import cpu_bandwidth_flow_board as flow

class PrefixPlanTests(unittest.TestCase):
    def test_only_retirement_option_differs(self):
        common=dict(dma_line_transfers=True,dma_line_entries=4,lsu_entries=4)
        off=prefix.expected_model_plan(1,**common)
        on=prefix.expected_model_plan(1,load_order_older_retire=True,**common)
        self.assertIs(off['fetch_previous_packet'],False)
        self.assertIs(on['fetch_previous_packet'],False)
        self.assertEqual({k:v for k,v in off.items() if k!='fetch_previous_packet'},
                         flow.expected_model_plan(1,**common))
        self.assertEqual({k:v for k,v in on.items() if k!='fetch_previous_packet'},
                         flow.expected_model_plan(1,load_order_older_retire=True,**common))
        self.assertEqual(on['parameters'][:-1],off['parameters'])
        self.assertEqual(on['parameters'][-1],'--load-order-older-retire')
    def test_reject_uncontrolled_baselines(self):
        for change in ({'flag':0},{'lsu_entries':2},{'load_order_older_retire':1}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                options=dict(flag=1,lsu_entries=4,load_order_older_retire=False)
                options.update(change)
                prefix.expected_model_plan(**options)
    def test_dma_fixed(self):
        args=prefix.arguments(['--tag','host-check'])
        self.assertEqual((args.dma_line_transfers,args.dma_line_entries,args.dma_line_yield_cycles),(True,4,0))

if __name__=='__main__':unittest.main()
