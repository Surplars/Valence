"""Clock metadata/negative configuration checks, no Linux build or simulation."""
import argparse
import subprocess
import sys
import unittest
from pathlib import Path
from clock_config import add_clock_arguments, resolve_clocks
from build_linux import board_dts

HERE = Path(__file__).resolve().parent


def clocks(*args):
    parser = argparse.ArgumentParser()
    add_clock_arguments(parser, 40000000)
    return resolve_clocks(parser.parse_args(args))


class FirmwareClocksTests(unittest.TestCase):
    def test_shared_rom_flags_have_no_cpu_profile_dependency(self):
        profiles = [clocks('--common-platform', '--cpu-hz', str(hz)) for hz in (100000000, 300000000)]
        self.assertEqual(profiles[0].flags(), profiles[1].flags())
        self.assertEqual(profiles[0].metadata(), profiles[1].metadata())
        self.assertIsNone(profiles[0].metadata()['cpu_hz'])
        self.assertEqual(profiles[0].timebase_hz, 250000000)
        self.assertIn('-DBOARD_CPU_CLOCK_HZ=0ULL', profiles[0].flags())

    def test_legacy_and_explicit_domains(self):
        self.assertEqual(clocks().timebase_hz, 40000000)
        cfg = clocks('--cpu-hz', '300000000', '--timebase-hz', '250000000', '--fabric-hz', '250000000')
        self.assertEqual((cfg.cpu_hz, cfg.timebase_hz, cfg.ddr_ui_hz), (300000000, 250000000, 250000000))
        self.assertIn('-DBOARD_CPU_CLOCK_HZ=300000000ULL', cfg.flags())

    def test_common_dynamic_boot_preserves_cmu_and_fixed_time(self):
        cfg = clocks('--common-platform', '--common-clock-profile', 'boot50-dynamic', '--cpu-hz', '50000000')
        self.assertEqual((cfg.timebase_hz, cfg.fabric_hz, cfg.ddr_ui_hz), (250000000, 50000000, 250000000))
        self.assertEqual(cfg.flags(), ['-DBOARD_CPU_CLOCK_HZ=0ULL', '-DTIMEBASE_HZ=250000000ULL',
            '-DFABRIC_CLOCK_HZ=50000000ULL', '-DDDR_UI_CLOCK_HZ=250000000ULL', '-DBOARD_CMU_CLOCKS=1'])
        self.assertEqual(cfg.metadata()['cpu_clock_source'], 'CMU resource 1 nominalHz')
        self.assertIsNone(cfg.metadata()['cpu_hz'])
        self.assertFalse(cfg.metadata()['clock_frequencies_measured'])
        for args in (('--cpu-hz', '50000000'), ('--common-platform', '--cpu-hz', '100000000'),
                     ('--common-platform', '--cpu-hz', '50000000', '--fabric-hz', '250000000'),
                     ('--common-platform', '--cpu-hz', '50000000', '--timebase-hz', '50000000')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                clocks('--common-clock-profile', 'boot50-dynamic', *args)

    def test_bad_domains(self):
        for args in (('--cpu-hz', '0'), ('--cpu-hz', '500000001'), ('--timebase-hz', '-1'),
                     ('--fabric-hz', '1'), ('--ddr-ui-hz', '0'),
                     ('--common-platform', '--timebase-hz', '100000000'),
                     ('--common-platform', '--fabric-hz', '300000000'),
                     ('--common-platform', '--ddr-ui-hz', '100000000')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                clocks(*args)

    def test_linux_cpu_and_sbi_timebase_are_independent(self):
        for kind, cpu, compatible in (('i1', 300000000, 'openion,valence-i1'),
                                      ('a1', 100000000, 'openion,orbital-a1')):
            text = board_dts('rv64gc', cpu, 460800, 0x80000000,
                             timebase_hz=250000000, fabric_hz=250000000, cpu_kind=kind)
            self.assertIn('timebase-frequency = <250000000>;', text)
            self.assertIn(f'clock-frequency = <{cpu}>;', text)
            self.assertIn(f'compatible = "{compatible}", "riscv";', text)
            self.assertIn('clock-frequency = <7372800>;', text)
            self.assertIn('diagnostics@fff78000', text)
            self.assertIn('monitor@ffff8000', text)
            self.assertIn('riscv,isa = "rv64imafdc_zicsr_zifencei";', text)
        # UART reference is not derived from CPU rate.
        self.assertIn('current-speed = <460800>', board_dts('rv64imac', 6000000, 460800,
                       timebase_hz=250000000, fabric_hz=250000000, cpu_kind='i1'))
        with self.assertRaises(RuntimeError):
            board_dts('rv64gc', 300000000, 460800, timebase_hz=0)
        with self.assertRaises(RuntimeError):
            board_dts('rv64gc', 300000000, 460800, cpu_kind='unknown')

    def test_invalid_cli_fails_before_build(self):
        for script, args, expected in (
                ('build.py', ['--common-platform', '--timebase-hz', '100000000'], 'requires timebase'),
                ('build_coremark.py', ['--clock-hz', '500000001'], '6..500 MHz'),
                ('build_linux.py', ['--common-platform', '--cpu-kind', 'i1', '--cpu-hz', '100000000'], 'I1 CPU=300MHz'),
                ('build_linux.py', ['--timebase-hz', '0'], '6..500 MHz')):
            result = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(expected, result.stderr)


if __name__ == '__main__':
    unittest.main()
