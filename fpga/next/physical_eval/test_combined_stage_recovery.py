"""Mock-only durable stage and recovery gates; no FPGA tool execution."""
from pathlib import Path
import tempfile
import unittest
from combined_contract import read, write, info, sha
from combined_stage_receipt import check_synthesis, recover_synthesis, seal, transient_artifact


class StageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root/'synthesis'; self.stage.mkdir()
        self.identity = {'mock': True}
        for name in ('post_synth_unconstrained.dcp', 'stage-result.txt', 'utilization.rpt',
                     'ip_status.rpt', 'rom-init.tsv', 'project-inputs.verified.json'):
            (self.stage/name).write_text('MOCK '+name)
        self.scratch = self.stage/'.Xil/Vivado-123-MOCK/realtime/ddr4_0_stub.v'
        self.scratch.parent.mkdir(parents=True); self.scratch.write_text('MOCK scratch')
        self.runtime = self.stage/'dfx_runtime.txt'; self.runtime.write_text('before exit')
        self.receipt = self.stage/'combined-stage-receipt.json'
        self.sidecar = self.root/'recovery.json'

    def legacy(self):
        artifacts = {p.relative_to(self.stage).as_posix(): info(p) for p in self.stage.rglob('*') if p.is_file()}
        write(self.receipt, dict(schema='combined-bandwidth-stage-v1', stage='synthesis',
              status='SYNTHESIZED_NOT_PHYSICALLY_QUALIFIED', identity=self.identity,
              checkpoint=info(self.stage/'post_synth_unconstrained.dcp'), artifacts=artifacts))
        self.original_hash = sha(self.receipt)
        self.checkpoint_hash = sha(self.stage/'post_synth_unconstrained.dcp')
        self.scratch.unlink(); self.runtime.write_text('after exit')

    def recover(self):
        recover_synthesis(self.root, self.identity, self.sidecar, self.original_hash,
                          self.checkpoint_hash, {'mockValidator': True})

    def test_fresh_seal_only_durable_outputs(self):
        seal(self.root, 'synthesis', self.identity)
        self.scratch.unlink(); self.runtime.write_text('after exit')
        check_synthesis(self.root, self.identity)
        self.assertIn('utilization.rpt', read(self.receipt)['artifacts'])
        self.assertNotIn('dfx_runtime.txt', read(self.receipt)['artifacts'])

    def test_recovery_preserves_original_and_all_stable_hashes(self):
        self.legacy()
        with self.assertRaises(ValueError): check_synthesis(self.root, self.identity)
        self.recover(); check_synthesis(self.root, self.identity, self.sidecar)
        self.assertEqual(sha(self.receipt), self.original_hash)
        self.assertEqual(len(read(self.sidecar)['artifacts']), 6)
        with self.assertRaises(FileExistsError): self.recover()

    def test_changed_stable_report_fails(self):
        self.legacy(); (self.stage/'utilization.rpt').write_text('changed')
        with self.assertRaises(ValueError): self.recover()

    def test_swapped_checkpoint_fails(self):
        self.legacy(); self.recover()
        (self.stage/'post_synth_unconstrained.dcp').write_text('old historical DCP')
        with self.assertRaises(ValueError): check_synthesis(self.root, self.identity, self.sidecar)

    def test_omitted_stable_report_fails(self):
        self.legacy(); self.recover()
        record = read(self.sidecar); del record['artifacts']['utilization.rpt']
        self.sidecar.unlink(); write(self.sidecar, record)
        with self.assertRaisesRegex(ValueError, 'omission'): check_synthesis(self.root, self.identity, self.sidecar)

    def test_unknown_scratch_and_report_names_are_not_exempt(self):
        for name in ('.Xil/Vivado-123-MOCK/important.dcp', '.Xil/report.rpt', 'sub/dfx_runtime.txt',
                     '../dfx_runtime.txt', 'utilization.rpt', 'netlist.v'):
            self.assertFalse(transient_artifact(name), name)

    def test_failure_and_stale_original_receipt_fail(self):
        self.legacy(); self.recover()
        (self.stage/'failure.txt').write_text('failure')
        with self.assertRaises(ValueError): check_synthesis(self.root, self.identity, self.sidecar)
        (self.stage/'failure.txt').unlink()
        self.receipt.write_text(self.receipt.read_text()+'\n')
        with self.assertRaisesRegex(ValueError, 'original receipt'): check_synthesis(self.root, self.identity, self.sidecar)

if __name__ == '__main__': unittest.main()
