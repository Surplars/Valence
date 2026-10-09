#!/usr/bin/env python3
"""Production Python uploader ↔ actual host-compiled BootROM through pipes.

These are local process pipes, not serial hardware, sockets, a CPU or a board.
"""
import argparse
import io
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time

import uart_load as host


class PipeSerial:
    def __init__(self, process):
        self.process = process
        self.written = bytearray()
        self.discarded = bytearray()

    def write(self, data):
        self.written.extend(data)
        return os.write(self.process.stdin.fileno(), data)

    def flush(self):
        self.process.stdin.flush()

    def read(self, size):
        if select.select([self.process.stdout], [], [], 0.05)[0]:
            return os.read(self.process.stdout.fileno(), size)
        return b''

    def reset_input_buffer(self):
        while select.select([self.process.stdout], [], [], 0)[0]:
            data = os.read(self.process.stdout.fileno(), 4096)
            if not data:
                break
            self.discarded.extend(data)


def run(binary, selected):
    process = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0,
                               env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
    port = PipeSerial(process)
    try:
        if selected:
            # Wait for the full menu before selecting UART using CRLF Enter.
            banner = bytearray()
            deadline = time.monotonic() + 3
            while b'No separate Run Image action.' not in banner and time.monotonic() < deadline:
                banner += port.read(4096)
            assert b'No separate Run Image action.' in banner
            port.write(b'\x1b[B\r\n')
            # Leave the original VLOAD unread so upload() must discard it.
            time.sleep(0.05)
        image = bytes((i*37+11) & 255 for i in range(769))
        host.upload(port, image, verify_timeout=5)
        transcript = io.BytesIO()
        assert host.finish_download(port, run=True, timeout=5, output=transcript) == 'autoboot'
        suffix = bytearray()
        deadline = time.monotonic() + 3
        while b'GUEST ENTRY SENTINEL\r\n' not in suffix and time.monotonic() < deadline:
            suffix += port.read(4096)
        assert b'GUEST ENTRY SENTINEL\r\n' in suffix, suffix
        assert process.wait(timeout=3) == 0, process.stderr.read()
        expected = (b'\x1b[B\r\n' if selected else b'') + b'd' + host.image_header(image, host.RAM_BASE)
        for sequence, offset in enumerate(range(0, len(image), host.CHUNK_SIZE)):
            expected += host.chunk_frame(sequence, image[offset:offset+host.CHUNK_SIZE])
        assert port.written == expected, 'unexpected post-download g or other host bytes'
        if selected:
            assert b'VLOAD1\r\n' in port.discarded, port.discarded
        assert b'RAM IMAGE VERIFIED\r\nAUTOBOOT\r\n' in transcript.getvalue()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cc')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as temporary:
        binary = str(Path(temporary) / 'bootrom-pipe')
        subprocess.run([args.cc, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        str(source/'test_bootrom_uart_pipe.c'), str(source/'crc32.c'),
                        '-o', binary], check=True)
        for selected in (False, True):
            run(binary, selected)
    print('UART_TUI_INTEROP_PASS cases=2 production_uploader=1 real_bootrom_c=1 pipes_only=1 no_trailing_g=1')


if __name__ == '__main__':
    main()
