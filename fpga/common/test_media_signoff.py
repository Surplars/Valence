"""Synthetic three-rate final-gate negatives, not timing evidence."""
import copy
import shutil
import unittest
from unittest.mock import patch
import manifest as gate
import producer
import test_manifest as fixtures


class MediaGate(unittest.TestCase):
    def setUp(self):
        self.c=fixtures.ContractTests(); self.c.setUp(); self.addCleanup(self.c.doCleanups)
        c=self.c; c.m['producer']={}; c.m['signoff']['bus_skew_checks']='mapped-scope'
        c.m['stages']['implementation']['outputs'].append('bus-skew-scope.json')
        c.refresh(); c.frozen_run()
        scopes=[dict(budget_ns=3.333, **{'from':[f'a{i}/C'],'to':[f'b{i}/D']}) for i in range(2)]
        p=c.write_json('local-run/implementation/bus-skew-scope.json',dict(profile_sha256=c.profile,phase='implementation',scopes=scopes))
        r=gate.read(c.root/'local-run/implementation/stage-receipt.json')
        r['outputs_sha256']['bus-skew-scope.json']=gate.sha(p)
        c.write_json('local-run/implementation/stage-receipt.json',r)
        io_text = '\n'.join('checking ' + key + ' (0)' for key in gate.IO_COVERAGE)
        for name in gate.BOARD_REPORTS:
            c.write('local-run/signoff/' + name, 'SYNTHETIC AUDIT ONLY\n')
        c.write('local-run/signoff/io-coverage.rpt', io_text)
        with (c.reports/'coverage.rpt').open('a') as f: f.write('\n'+io_text+'\n')
        for rate in (10,100,1000):
            directory=c.reports/f'media-{rate}';directory.mkdir()
            for name in ('timing.rpt','coverage.rpt','route.rpt','bus_skew.rpt','drc.rpt'):
                shutil.copy2(c.reports/name,directory/name)
            c.write_json(f'local-run/signoff/media-{rate}/scenario.json',dict(rate_mbps=rate,profile_sha256=c.profile,
                dcp_sha256=c.dcp_hash,critical_drc=0,periods_ns=dict.fromkeys(('phy_rx','phy_rx_launch','phy_tx_capture'),{1000: 8.0, 100: 40.0, 10: 400.0}[rate]),
                rx_min_ns=-1.050,rx_max_ns=1.050,tx_min_ns=-1.250,tx_max_ns=1.250))

    def signoff(self):
        # Producer inputs are independently tested; retain every report/stage/hash gate.
        with patch.object(producer,'validate',return_value={}): return self.c.signoff()

    def test_all_three_rates_required(self):
        self.assertIn('media-10/timing.rpt',self.signoff()['reports_sha256'])
        (self.c.reports/'media-10/scenario.json').unlink()
        with self.assertRaises(ValueError): self.signoff()

    def test_rx_hold_zero_budget_and_stale_dcp_rejected(self):
        c=self.c;path=c.reports/'media-100/scenario.json';original=gate.read(path)
        for key,value in [('dcp_sha256','f'*64),('rx_min_ns',0.0),('critical_drc',1),('periods_ns',dict.fromkeys(('phy_rx','phy_rx_launch','phy_tx_capture'),80.0))]:
            bad=copy.deepcopy(original);bad[key]=value
            c.write_json('local-run/signoff/media-100/scenario.json',bad)
            with self.assertRaises(ValueError): self.signoff()
        c.write_json('local-run/signoff/media-100/scenario.json',original)
        (c.reports/'media-10/timing.rpt').write_text('All user specified timing constraints are met.\n0.001 0.000 0 100 -0.138 -0.138 1 100 0.003 0.000 0 100\n')
        with self.assertRaisesRegex(ValueError,'setup/hold/pulse'): self.signoff()

if __name__=='__main__': unittest.main()
