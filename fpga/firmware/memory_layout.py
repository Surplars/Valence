"""Explicit board memory profiles; never infer a larger window from a small image."""
from dataclasses import dataclass

RAM_BASE = 0x80200000
MONITOR_BYTES = 0x4000

@dataclass(frozen=True)
class MemoryLayout:
    ram_bytes: int

    def __post_init__(self):
        if self.ram_bytes not in (0x100000, 0x20000000, 0x40000000, 0x80000000):
            raise ValueError("unsupported board RAM capacity")

    @property
    def end(self):
        return RAM_BASE + self.ram_bytes

    @property
    def monitor(self):
        # BootROM medany globals must remain within signed PC-relative reach.
        return min(self.end - MONITOR_BYTES, 0xffff8000)

    @property
    def image_limit(self):
        return self.monitor - RAM_BASE

PROFILES = {"uram": MemoryLayout(0x100000), "ddr": MemoryLayout(0x20000000),
            "ddr1g": MemoryLayout(0x40000000), "ddr2g": MemoryLayout(0x80000000)}
