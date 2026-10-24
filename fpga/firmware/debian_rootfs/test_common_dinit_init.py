"""Execute production platform shell against isolated DT/sysfs + modprobe mocks."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parent

class CommonInitTests(unittest.TestCase):
    def run_case(self, enabled=True, irq=True, fail='', control=None, fabric=None, a1_runtime=False, capability=True):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);bin=root/'bin';bin.mkdir();ledger=root/'ledger'
            mock=bin/'modprobe'
            mock.write_text('#!/bin/sh\necho "$1" >> "$LEDGER"\n[ "$1" != "$FAIL_MODULE" ]\n');mock.chmod(0o755)
            node=root/'dt/soc/clock-monitor';node.mkdir(parents=True)
            (node/'compatible').write_bytes(b'openion,valence-a1-runtime-clock-monitor-v2\0' if a1_runtime else b'openion,valence-clock-monitor-v1\0')
            (root/'dt/compatible').write_bytes(b'openion,valence-a1-runtime-v2\0' if capability else b'openion,valence-vl100\0')
            (node/'status').write_bytes(b'okay\0' if enabled else b'disabled\0')
            if control is not None:
                (node/'openion,cpu-rate-control').touch()
                rate=root/'devices/clockmon';rate.mkdir(parents=True)
                if control != 'missing':(rate/'cpu_control').write_text(control)
            if fabric is not None:
                (node/'openion,i1-boot-pair-125').touch()
                rate=root/'devices/clockmon';rate.mkdir(parents=True,exist_ok=True)
                if fabric != 'missing':(rate/'fabric_boot_control').write_text(fabric)
            status=root/'devices/aia';status.mkdir(parents=True)
            (status/'irqchip_status').write_text('ready=1 faulted=0' if irq else 'ready=0 faulted=1')
            source=(HERE/'dinit/common-platform-init').read_text()
            source=source.replace('export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',f'export PATH={bin}:/usr/bin:/bin')
            source=source.replace('/sys/firmware/devicetree/base',str(root/'dt')).replace('/sys/bus/platform/devices',str(root/'devices')).replace('/etc/valence/build-time',str(root/'absent-build-time'))
            script=root/'platform.sh';script.write_text(source)
            result=subprocess.run(['/bin/sh',script],env=dict(os.environ,LEDGER=str(ledger),FAIL_MODULE=fail),capture_output=True,text=True)
            return result,ledger.read_text().splitlines()
    def test_a1_runtime_readonly(self):
        result,loads=self.run_case(a1_runtime=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('valence_clockmon',loads)
        for options in ({'capability':False},{'control':'missing'},{'fabric':'missing'}):
            result,loads=self.run_case(a1_runtime=True,**options)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('valence_clockmon',loads)
    def test_i1_order(self):
        result,loads=self.run_case();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(loads,['valence_soc','valence_clockmon','valence_cmu','valence_aia','valence_dma','valence_gmac'])
    def test_a1_no_unknown_mmio(self):
        result,loads=self.run_case(enabled=False);self.assertEqual(result.returncode,0)
        self.assertNotIn('valence_clockmon',loads);self.assertIn('SKIP_UNSUPPORTED',result.stdout)
    def test_irq_fail_stops_consumers(self):
        result,loads=self.run_case(irq=False);self.assertNotEqual(result.returncode,0)
        self.assertNotIn('valence_dma',loads);self.assertNotIn('valence_gmac',loads)
    def test_confirmed_target(self):
        result,loads=self.run_case(control='last_result=0 last_confirmed_hz=125000000 boot_target_hz=125000000')
        self.assertEqual(result.returncode,0);self.assertIn('valence_gmac',loads)
    def test_confirmed_fallback(self):
        result,loads=self.run_case(control='last_result=-110 last_confirmed_hz=50000000 boot_target_hz=125000000')
        self.assertEqual(result.returncode,0);self.assertIn('without retry',result.stdout)
    def test_unknown_and_mismatch_stop(self):
        for control in ('missing','last_result=-110 last_confirmed_hz=0 boot_target_hz=125000000',
                        'last_result=0 last_confirmed_hz=50000000 boot_target_hz=125000000',
                        'last_result=0 last_confirmed_hz=50000000 boot_target_hz=50000000'):
            with self.subTest(control=control):
                result,loads=self.run_case(control=control)
                self.assertNotEqual(result.returncode,0);self.assertNotIn('valence_cmu',loads)
    def test_pair_success_and_confirmed_fallback(self):
        cpu='last_result=0 last_confirmed_hz=125000000 boot_target_hz=125000000'
        for fab in ('last_result=0 last_confirmed_hz=125000000 boot_target_hz=125000000 attempted=1',
                    'last_result=-110 last_confirmed_hz=50000000 boot_target_hz=125000000 attempted=1'):
            result,loads=self.run_case(control=cpu,fabric=fab)
            self.assertEqual(result.returncode,0,result.stdout);self.assertIn('valence_gmac',loads)
    def test_cpu_fallback_skips_fabric(self):
        cpu='last_result=-110 last_confirmed_hz=50000000 boot_target_hz=125000000'
        fab='last_result=0 last_confirmed_hz=50000000 boot_target_hz=125000000 attempted=0'
        result,loads=self.run_case(control=cpu,fabric=fab)
        self.assertEqual(result.returncode,0,result.stdout);self.assertIn('valence_gmac',loads)
    def test_cpu50_fabric125_contradiction_stops(self):
        cpu='last_result=-110 last_confirmed_hz=50000000 boot_target_hz=125000000'
        fab='last_result=0 last_confirmed_hz=125000000 boot_target_hz=125000000 attempted=1'
        result,loads=self.run_case(control=cpu,fabric=fab)
        self.assertNotEqual(result.returncode,0);self.assertNotIn('valence_cmu',loads)
        self.assertIn('Contradictory',result.stdout)
    def test_pair_unknown_missing_or_unexpected_skip_stops(self):
        cpu='last_result=0 last_confirmed_hz=125000000 boot_target_hz=125000000'
        for fab in ('missing','last_result=-110 last_confirmed_hz=0 boot_target_hz=125000000 attempted=1',
                    'last_result=0 last_confirmed_hz=50000000 boot_target_hz=125000000 attempted=0'):
            result,loads=self.run_case(control=cpu,fabric=fab)
            self.assertNotEqual(result.returncode,0,result.stdout);self.assertNotIn('valence_cmu',loads)
        result,loads=self.run_case(fabric='missing')
        self.assertNotEqual(result.returncode,0);self.assertNotIn('valence_cmu',loads)
    def test_monitor_failure_stops_dependents(self):
        result,loads=self.run_case(fail='valence_clockmon');self.assertNotEqual(result.returncode,0)
        self.assertEqual(loads,['valence_soc','valence_clockmon'])
if __name__=='__main__':unittest.main()
