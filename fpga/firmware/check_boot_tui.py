#!/usr/bin/env python3
"""Independent 80x24 ANSI terminal model for the actual compiled menu renderer.

Does not import the C layout/parser or use any board/RTL emulator. Unsupported
control codes and any write outside the viewport fail instead of being ignored.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


class Terminal:
    def __init__(self):
        self.cells = [[' '] * 80 for _ in range(24)]
        self.reverse = [[False] * 80 for _ in range(24)]
        self.row = self.col = 0
        self.highlight = self.hidden = False
        self.max_col = self.max_row = 0

    def feed(self, raw):
        data = raw.decode('ascii')
        i = 0
        while i < len(data):
            c = data[i]
            if c == '\x1b':
                found = re.match(r'\x1b\[([0-9;?]*)([A-Za-z])', data[i:])
                assert found, f'unknown escape at {i}'
                args, final = found.groups()
                if final == 'H':
                    rc = [int(n) if n else 1 for n in args.split(';')]
                    self.row, self.col = (rc + [1])[:2]
                    self.row -= 1
                    self.col -= 1
                elif final == 'J':
                    assert args == '2'
                    self.cells = [[' '] * 80 for _ in range(24)]
                    self.reverse = [[False] * 80 for _ in range(24)]
                elif final == 'm':
                    self.highlight = args in ('7', '44;37;1')
                    assert args in ('0', '7', '44;37;1', '36;1')
                elif final in ('h', 'l'):
                    assert args == '?25'
                    self.hidden = final == 'l'
                elif final == 'r':
                    assert args == ''
                else:
                    raise AssertionError(f'unimplemented CSI {final}')
                i += len(found[0])
                continue
            if c == '\r':
                self.col = 0
            elif c == '\n':
                self.row += 1
                if self.row >= 24:
                    self.cells.pop(0)
                    self.cells.append([' '] * 80)
                    self.reverse.pop(0)
                    self.reverse.append([False] * 80)
                    self.row = 23
            else:
                assert 32 <= ord(c) <= 126
                assert 0 <= self.row < 24 and 0 <= self.col < 80, (self.row, self.col)
                self.cells[self.row][self.col] = c
                self.reverse[self.row][self.col] = self.highlight
                self.max_col = max(self.max_col, self.col)
                self.max_row = max(self.max_row, self.row)
                self.col += 1
            i += 1

    def snapshot(self):
        return '\n'.join(''.join(row).rstrip() for row in self.cells) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--jtag', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    raw = subprocess.check_output([str(args.binary.resolve()), '--snapshot'], env={**os.environ, 'ASAN_OPTIONS':'detect_leaks=0'})
    term = Terminal()
    term.feed(raw)
    snapshot = term.snapshot()
    rows = snapshot.splitlines()
    assert len(rows) == 24 and all(len(row) == 78 for row in rows)
    for row in (0, 3, 14, 17, 23):
        assert rows[row] == '+' + '-' * 76 + '+'
    assert 'Network download + boot' in rows[4]
    assert 'UART download + boot' in rows[5]
    assert 'Verify RAM image (read-only)' in rows[7 if args.jtag else 6]
    if args.jtag:
        assert 'JTAG download + boot (host COMMIT)' in rows[6]
    assert 'Run verified RAM image' not in snapshot
    assert 'auto' in rows[19] and 'Last result' in rows[18]
    assert term.hidden and all(term.reverse[4][:78])
    assert not any(term.reverse[5])
    assert term.max_col == 77 and term.max_row == 23
    (args.out / 'menu.ansi').write_bytes(raw)
    (args.out / 'menu.txt').write_text(snapshot)
    # Optional visual preview of the independently decoded terminal cells.
    try:
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 16)
        image = Image.new('RGB', (1000, 540), '#111827')
        draw = ImageDraw.Draw(image)
        for row in range(24):
            for col in range(80):
                x, y = 20 + col * 12, 18 + row * 21
                if term.reverse[row][col]:
                    draw.rectangle((x, y, x+11, y+20), fill='#1e40af')
                draw.text((x, y), term.cells[row][col], font=font, fill='#e5e7eb')
        image.save(args.out / 'menu.png')
    except ImportError:
        pass
    receipt = dict(status='passed', columns=80, rows=24, occupied_columns=78,
                   offscreen_writes=0, ansi_bytes=len(raw), source='actual host-compiled renderer',
                   board_verified=False, model='independent Python terminal interpreter')
    (args.out / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('BOOT_TUI_TERMINAL_PASS rows=24 columns=80 border=ascii offscreen_writes=0')


if __name__ == '__main__':
    main()
