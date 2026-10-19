"""Explicit clock-domain contract shared by firmware builders (not timing proof)."""
from dataclasses import dataclass

MIN_HZ = 6_000_000
MAX_HZ = 500_000_000
COMMON_HZ = 250_000_000


@dataclass(frozen=True)
class ClockConfig:
    cpu_hz: int
    timebase_hz: int
    fabric_hz: int
    ddr_ui_hz: int
    cmu: bool = False

    def flags(self):
        # A CMU-enabled image has no baked-in CPU rate. Both CPU profiles use
        # these exact bytes, including the separately linked RAM diagnostics.
        return [f'-DBOARD_CPU_CLOCK_HZ={0 if self.cmu else self.cpu_hz}ULL',
                f'-DTIMEBASE_HZ={self.timebase_hz}ULL',
                f'-DFABRIC_CLOCK_HZ={self.fabric_hz}ULL',
                f'-DDDR_UI_CLOCK_HZ={self.ddr_ui_hz}ULL',
                f'-DBOARD_CMU_CLOCKS={int(self.cmu)}']

    def metadata(self):
        return dict(cpu_hz=None if self.cmu else self.cpu_hz,
                    cpu_clock_source='CMU resource 1 nominalHz' if self.cmu else 'build contract',
                    cpu_identity='runtime unspecified; select core in hardware/payload manifest',
                    timebase_hz=self.timebase_hz, fabric_hz=self.fabric_hz,
                    ddr_ui_hz=self.ddr_ui_hz, cmu_clock_metadata=self.cmu,
                    clock_frequencies_measured=False, physical_timing_verified=False)


def add_clock_arguments(parser, default_cpu_hz, cpu_option='--cpu-hz'):
    parser.add_argument(cpu_option, dest='cpu_hz', type=int, default=default_cpu_hz,
                        help='CPU nominal Hz; not rdtime Hz when --timebase-hz is set; ignored in shared CMU image')
    parser.add_argument('--timebase-hz', type=int, help='rdtime/mtime ticks per second (legacy default: CPU Hz)')
    parser.add_argument('--fabric-hz', type=int, help='fabric nominal Hz (default: timebase Hz)')
    parser.add_argument('--ddr-ui-hz', type=int, help='DDR UI nominal Hz (default: fabric Hz)')
    parser.add_argument('--common-platform', action='store_true',
                        help='same I1/A1 ROM: CMU CPU metadata, fabric/timebase/DDR UI fixed at 250 MHz')


def resolve_clocks(args):
    if not MIN_HZ <= args.cpu_hz <= MAX_HZ:
        raise ValueError('CPU clock must be in 6..500 MHz')
    values = [args.timebase_hz, args.fabric_hz, args.ddr_ui_hz]
    if args.common_platform:
        if any(v is not None and v != COMMON_HZ for v in values):
            raise ValueError('common platform requires timebase/fabric/DDR UI = 250000000 Hz')
        values = [COMMON_HZ] * 3
    else:
        values[0] = args.cpu_hz if values[0] is None else values[0]
        values[1] = values[0] if values[1] is None else values[1]
        values[2] = values[1] if values[2] is None else values[2]
    if any(not MIN_HZ <= value <= MAX_HZ for value in values):
        raise ValueError('timebase/fabric/DDR UI clocks must be in 6..500 MHz')
    return ClockConfig(args.cpu_hz, *values, args.common_platform)
