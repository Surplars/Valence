"""Synthetic negative controls; not FPGA/functional qualification."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import diagnostic as d
import manifest as gate

class DiagnosticTests(unittest.TestCase):
    def fixture(self,root):
        for name in gate.ROOTS:(root/name).mkdir(parents=True,exist_ok=True)
        source='src/main/scala/test.scala';(root/source).write_text('frozen baseline')
        for name in d.HELPERS:(root/'fpga/common'/name).write_text('helper')
        (root/'fpga/common/diagnostic-baseline.json').write_text(json.dumps(dict(commit=d.BASELINE,inputs={source:gate.sha(root/source)})))
        (root/'dci-result.json').write_text(json.dumps(dict(source_commit=d.BASELINE,dci_positive='PASS',positive_forbidden_messages_found=False)))
        (root/'fw.json').write_text('{}')
        files=[p for p in root.rglob('*') if p.is_file()]
        m=dict(schema=d.SCHEMA,status=d.STATUS,diagnosticOnly=True,missing_functional_receipt=True,source_commit=d.BASELINE,threads=8,
               configuration=dict(cpu='i1',clock_profile='performance300-static',top='soc_top_common_ddr',part='xczu15eg-ffvb1156-2-i',abi=1,interrupt_abi='aia',rom_base=0x80000000,rom_bytes=131072,clocks_hz=gate.reviewed_board_clocks('i1','performance300-static'),features=dict(mac=True,network_dma=True)),
               roles=dict(firmware_contract='fw.json'),native_evidence=['dci-result.json'],inputs={p.relative_to(root).as_posix():gate.sha(p) for p in files})
        path=root/'diagnostic.json';path.write_text(json.dumps(m));return path,m
    def test_formal_gate_rejects_diagnostic_schema(self):
        with tempfile.TemporaryDirectory() as t:
            p,m=self.fixture(Path(t))
            with self.assertRaisesRegex(ValueError,'schema'):gate.preflight(p)
    def test_frozen_sources_and_frequency_are_not_optional(self):
        with tempfile.TemporaryDirectory() as t, patch.object(d.producer,'validate'),patch.object(gate,'firmware_contract'):
            p,m=self.fixture(Path(t));d.check(p)
            m['configuration']['clocks_hz']['cpu']=50000000;p.write_text(json.dumps(m))
            with self.assertRaises(ValueError):d.check(p)
            m['configuration']['clocks_hz']['cpu']=300000000
            source=Path(t)/'src/main/scala/test.scala';source.write_text('dirty core')
            m['inputs']['src/main/scala/test.scala']=gate.sha(source);p.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'baseline'):d.check(p)
    def test_no_formal_receipt_or_bit_interface(self):
        here=Path(__file__).parent
        script=(here/'diagnostic.tcl').read_text();runner=(here/'run-diagnostic.ps1').read_text()
        self.assertIn('write_bitstream write_device_image',script)
        self.assertNotIn('signoff.tcl',script)
        self.assertNotIn('GenerateBit',runner)
        self.assertIn('DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM',runner)
        with tempfile.TemporaryDirectory() as t,patch.object(d,'check') as check:
            root=Path(t);out=root/'diagnostic-run/synthesis';out.mkdir(parents=True)
            (out/'stage-receipt.json').write_text('{}');check.return_value=(root,{},'profile')
            with self.assertRaisesRegex(ValueError,'formal receipt'):d.record(root/'diagnostic.json','synthesis')
    def test_baseline_is_the_published_snapshot_not_worktree(self):
        baseline=json.loads((Path(__file__).parent/'diagnostic-baseline.json').read_text())
        self.assertEqual(baseline['commit'],d.BASELINE)
        self.assertIn('src/main/scala/core/inorder/FiveStageCore.scala',baseline['inputs'])
        self.assertIn('src/main/scala/platform/CommonI1CpuTile.scala',baseline['inputs'])

if __name__=='__main__':unittest.main()
