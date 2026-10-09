#!/usr/bin/env python3
"""Validate the exact upstream source that defines the 8250 proc ABI; read-only."""
import argparse
import hashlib
import json
from pathlib import Path
import re

LINUX_REVISION = '551c722f40809618230001baccf219193e22fc5a'
PROC_PATH = '/proc/tty/driver/serial_8250'
SOURCES = {
    'drivers/tty/serial/8250/8250_core.c': '531d79a03acee7570e4fe67eca79334fbb48badc2d6a5f4740328d2542fef36b',
    'drivers/tty/serial/serial_core.c': '0c7f4222aadb4d006ec64925e7780b31d75c8497183f7adf528b96dd80e5f076',
    'fs/proc/proc_tty.c': '2fc6687c078e34b6ac84759ad733a35bba36ed902edb03cdfa3df5b74b4f5d1f',
}


def validate(source, helper=None):
    texts = {}
    for name, expected in SOURCES.items():
        blob = (source / name).read_bytes()
        if hashlib.sha256(blob).hexdigest() != expected:
            raise RuntimeError('Pinned serial proc implementation changed: ' + name)
        texts[name] = blob.decode()
    core = texts['drivers/tty/serial/8250/8250_core.c']
    registration = re.search(r'struct uart_driver serial8250_reg = \{(.*?)\n\};', core, re.S)
    if not registration:
        raise RuntimeError('8250 registration missing')
    name = re.search(r'\.driver_name\s*=\s*"([a-zA-Z0-9_]+)"', registration[1])[1]
    derived_path = '/proc/tty/driver/' + name
    serial = texts['drivers/tty/serial/serial_core.c']
    proc = texts['fs/proc/proc_tty.c']
    if (derived_path != PROC_PATH or
            not re.search(r'normal->driver_name\s*=\s*drv->driver_name;', serial) or
            'proc_create_single_data(driver->driver_name, 0, proc_tty_driver,' not in proc or
            '" MMIO%s:%pa"' not in serial or '"%u: uart:%s"' not in serial or
            '" irq:%u"' not in serial):
        raise RuntimeError('8250 proc naming or line-format contract changed')
    if helper is not None and ('uart_proc=' + derived_path + '\n') not in helper.read_text():
        raise RuntimeError('Bootstrap proc pathname differs from exact kernel driver')
    return dict(linux_revision=LINUX_REVISION, proc_path=derived_path,
        source_sha256=SOURCES, board_verified=False,
        scope='Exact kernel source naming/format and helper consistency; no IRQ traffic test')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--helper', type=Path, default=Path(__file__).resolve().parents[1] /
                        'debian_rootfs/dinit/uart-irq-init')
    args = parser.parse_args()
    print(json.dumps(validate(args.kernel_source, args.helper), indent=2))
