#!/usr/bin/env python3
"""Read-only paired Image/DTB TFTP with explicit, negotiated window limits.

Defaults preserve the V3 window1 command. Select a reviewed pair manifest for
V4 or another explicit release. Multi-window U-Boot remains board-unqualified.
This tool never changes network/firewall settings or resets the board.
"""
import argparse
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import socket
import struct
import time
import netboot_host as tftp

ENGINE_SHA256 = '1ff8a4779cf35c6f98d1405518e7a85b08c6bc8e4e2e6a591c32158cc4fcbbc1'
EXPECTED = {
    'Image': (72754512, '69a1f9991bd1385a2d3f8465e2388292020caa6c4b7e83068592ef9d08074f81'),
    'valence-vl100.dtb': (3387, 'bdd076a3fbfe13e73b13817efbe52389a2272b61d85a94b5080ff77de73f71a2'),
}
NAMES = frozenset(EXPECTED)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate manifest key: ' + repr(key))
        result[key] = value
    return result


def load_pair(manifest=None):
    """A manifest changes only the two explicit hashes, never served names/paths."""
    if manifest is None:
        return 'Valence Linux UART V3 20261009 (built-in)', EXPECTED.copy()
    path = Path(manifest)
    with path.open('rb') as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError('pair manifest exceeds 16 KiB')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != {'schema', 'label', 'files'}:
        raise ValueError('manifest requires exactly schema, label and files')
    if type(data['schema']) is not int or data['schema'] != 1:
        raise ValueError('unsupported pair manifest schema')
    label = data['label']
    if not isinstance(label, str) or not 1 <= len(label) <= 128 or not label.isprintable():
        raise ValueError('manifest label must be 1..128 printable characters')
    entries = data['files']
    if not isinstance(entries, dict) or set(entries) != NAMES:
        raise ValueError('manifest must pair exactly Image and valence-vl100.dtb')
    expected = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {'size', 'sha256'}:
            raise ValueError(name + ': manifest requires exactly size and sha256')
        size, digest = entry['size'], entry['sha256']
        if type(size) is not int or not 0 < size <= 0x7fffffff:
            raise ValueError(name + ': invalid manifest size')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError(name + ': SHA256 must be 64 lowercase hex characters')
        expected[name] = size, digest
    return label, expected


def prepare(image, dtb, manifest=None):
    label, expected_files = load_pair(manifest)
    files = {'Image': Path(image).resolve(), 'valence-vl100.dtb': Path(dtb).resolve()}
    for name, path in files.items():
        size, expected = expected_files[name]
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError(name + ': wrong paired file size (' + label + ')')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(name + ': wrong paired SHA256; use the paired unmodified file')
    event('PAIR_VERIFIED', label=label, manifest=str(manifest) if manifest else 'built-in V3',
          files={name: {'size': size, 'sha256': digest} for name, (size, digest) in expected_files.items()})
    return files


def verify_engine():
    path = Path(tftp.__file__).resolve()
    adjacent = Path(__file__).resolve().with_name('netboot_host.py')
    if path != adjacent or hashlib.sha256(path.read_bytes()).hexdigest() != ENGINE_SHA256:
        raise ValueError('use the paired adjacent netboot_host.py; engine SHA256 mismatch or non-adjacent import')
    return path


def event(kind, **fields):
    # repr escapes control characters in untrusted peer/request/error text.
    fields['perf_counter_s'] = f'{tftp.high_resolution_time():.9f}'
    print('STAGE2 ' + kind + ' ' + ' '.join(f'{key}={value!r}' for key, value in fields.items()), flush=True)


def request_details(packet):
    """Display bounded raw fields; never decide whether the RRQ is accepted."""
    fields = packet[2:514].split(b'\0')
    text = lambda value: value[:128].decode('ascii', errors='backslashreplace')
    return {
        'opcode': int.from_bytes(packet[:2], 'big') if len(packet) >= 2 else None,
        'bytes': len(packet),
        'name': text(fields[0]) if fields else '',
        'mode': text(fields[1]) if len(fields) > 1 else '',
        'options': [(text(fields[i]), text(fields[i + 1])) for i in range(2, len(fields) - 1, 2)],
    }


def rejection_reason(packet):
    """Explain parse_request rejection; the unchanged engine remains authoritative."""
    if len(packet) > 512:
        return 'RRQ exceeds 512-byte request bound'
    if not packet.startswith(b'\0\1'):
        return 'not a read request (opcode must be RRQ=1)'
    fields = packet[2:].split(b'\0')
    if len(fields) < 3 or len(fields) % 2 != 1 or fields[-1]:
        return 'malformed RRQ fields, missing NUL, or unpaired option'
    if fields[1].lower() != b'octet':
        return 'mode must be octet'
    try:
        name = fields[0].decode('ascii')
    except UnicodeDecodeError:
        return 'filename is not ASCII'
    allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'
    if not name or len(name) > 127 or any(c not in allowed for c in name):
        return 'filename is empty, too long, or contains disallowed/path characters'
    seen = set()
    for index in range(2, len(fields) - 1, 2):
        key, value = fields[index].lower(), fields[index + 1]
        if not key or not value:
            return 'empty option name or value'
        if key in seen:
            return 'duplicate option: ' + repr(key)
        if any(c < 33 or c > 126 for c in key + value):
            return 'non-printable option name or value'
        seen.add(key)
        if key in (b'blksize', b'windowsize'):
            if len(value) > 5 or not value.isdigit():
                return 'invalid numeric option: ' + repr(key)
            value = int(value)
            if key == b'blksize' and not 512 <= value <= 65464:
                return 'blksize outside supported request range 512..65464'
            if key == b'windowsize' and not 1 <= value <= 65535:
                return 'windowsize outside range 1..65535'
    return 'request rejected by the paired engine parser'


class ObservedSocket:
    """Transparent socket proxy: every packet, timeout and exception is unchanged."""
    def __init__(self, sock, peer):
        self.sock, self.peer = sock, peer
        self.oacks = self.ack0s = self.timeouts = self.foreign = self.malformed = 0
        self.first_data = self.first_ack = None
        self.first_data_sends = self.peer_errors = 0

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def sendto(self, packet, peer):
        result = self.sock.sendto(packet, peer)
        opcode = packet[:2]
        if opcode == b'\0\6':
            self.oacks += 1
            fields = packet[2:].rstrip(b'\0').split(b'\0')
            options = [(fields[i].decode('ascii', errors='backslashreplace'),
                        fields[i + 1].decode('ascii', errors='backslashreplace'))
                       for i in range(0, len(fields) - 1, 2)]
            event('OACK_SENT', peer=peer, send=self.oacks, options=options)
        elif opcode == b'\0\3' and len(packet) >= 4:
            block = struct.unpack('!H', packet[2:4])[0]
            if self.first_data is None:
                self.first_data = block
                event('FIRST_DATA_SENT', peer=peer, block=block, payload_bytes=len(packet) - 4)
            if block == self.first_data and self.first_ack is None:
                self.first_data_sends += 1
                if self.first_data_sends == 2:
                    event('FIRST_DATA_RETRANSMITTED', peer=peer, block=block)
        return result

    def recvfrom(self, size):
        try:
            packet, peer = self.sock.recvfrom(size)
        except socket.timeout:
            self.timeouts += 1
            if self.timeouts == 1:
                event('FIRST_SOCKET_TIMEOUT', phase='OACK/ACK0' if self.first_data is None else 'DATA/ACK')
            raise
        if peer != self.peer:
            self.foreign += 1
            if self.foreign == 1:
                event('SESSION_IGNORED', peer=peer, expected=self.peer, reason='foreign transfer ID')
        elif len(packet) == 4 and packet.startswith(b'\0\4'):
            block = struct.unpack('!H', packet[2:])[0]
            if block == 0 and self.first_data is None and self.oacks:
                self.ack0s += 1
                event('ACK0_RECEIVED', peer=peer)
            elif self.first_data is not None and self.first_ack is None:
                self.first_ack = block
                event('FIRST_ACK_AFTER_DATA_OBSERVED', peer=peer, block=block)
        elif len(packet) >= 4 and packet.startswith(b'\0\5'):
            self.peer_errors += 1
            event('PEER_ERROR', peer=peer, code=int.from_bytes(packet[2:4], 'big'), message=packet[4:])
        else:
            self.malformed += 1
            if self.malformed == 1:
                event('SESSION_IGNORED', peer=peer, reason='malformed or non-ACK packet', bytes=len(packet))
        return packet, peer

    def summary(self):
        event('OBSERVED', oack_sends=self.oacks, ack0_received=self.ack0s,
              first_data_block=self.first_data, first_data_sends=self.first_data_sends,
              first_ack_block=self.first_ack, socket_timeouts=self.timeouts,
              foreign_packets=self.foreign, malformed_packets=self.malformed, peer_errors=self.peer_errors)


def serve(files, bind, board, port=69, once=False, *, max_blksize=1024,
          max_windowsize=1, packet_delay_us=100):
    verify_engine()
    ipaddress.IPv4Address(bind)
    ipaddress.IPv4Address(board)
    if set(files) != NAMES:
        raise ValueError('serve exactly the two prepared paired filenames')
    if max_blksize not in (512, 1024) or not 1 <= max_windowsize <= tftp.MAX_WINDOWSIZE:
        raise ValueError('invalid TFTP negotiation limits')
    if not math.isfinite(packet_delay_us) or packet_delay_us < 0:
        raise ValueError('packet delay must be finite and nonnegative')
    totals = dict(datagrams_received=0, requests_rejected=0, transfers_started=0,
                  transfers_succeeded=0, transfers_failed=0, transfers_interrupted=0,
                  bytes_acked=0)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            listener.bind((bind, port))
            print(f'STAGE2 TFTP {bind}:{listener.getsockname()[1]} peer={board}; read-only Image + valence-vl100.dtb; diagnostics enabled', flush=True)
            event('ENGINE', release='stage2-pacing-v2-20261009', sha256=ENGINE_SHA256,
                  retry_policy='unchanged: 1 second, 10 sends', files=list(files))
            event('LIMITS', max_blksize=max_blksize, max_windowsize=max_windowsize,
                  packet_delay_us=packet_delay_us, no_window_option_fallback=1,
                  pacing='disabled' if packet_delay_us == 0 else 'within-window sleep only',
                  timing_clock='perf_counter_ns', timing_resolution_s=time.get_clock_info('perf_counter').resolution,
                  multi_window_board_status='unqualified; default remains window1')
            while True:
                packet, peer = listener.recvfrom(2048)
                totals['datagrams_received'] += 1
                event('REQUEST_RECEIVED', peer=peer, **request_details(packet))
                if peer[0] != board:
                    totals['requests_rejected'] += 1
                    event('REQUEST_REJECTED', peer=peer, reason='peer IP does not match --board', expected=board, response='none, same as released server')
                    continue
                request = tftp.parse_request(packet, max_blksize=max_blksize, max_windowsize=max_windowsize)
                if request is None or request.name not in files:
                    totals['requests_rejected'] += 1
                    reason = rejection_reason(packet) if request is None else 'filename is not one of the two permitted paired files'
                    event('REQUEST_REJECTED', peer=peer, reason=reason, response='ERROR 1 file unavailable, same as released server')
                    listener.sendto(b'\x00\x05\x00\x01file unavailable\x00', peer)
                    continue
                path = files[request.name]
                totals['transfers_started'] += 1
                event('REQUEST_ACCEPTED', peer=peer, name=request.name, blksize=request.blksize,
                      windowsize=request.windowsize, negotiated_options=request.options)
                stats = tftp.TransferStats()
                stats.blksize, stats.windowsize = request.blksize, request.windowsize
                display = None
                observed = None
                try:
                    display = tftp.TransferProgress(path.stat().st_size)
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as session, path.open('rb') as source:
                        session.bind((bind, 0))
                        event('SESSION_BOUND', local=session.getsockname(), peer=peer, name=request.name)
                        observed = ObservedSocket(session, peer)
                        sent = tftp.transfer(observed, peer, source, progress=display.update,
                                             stats=stats, blksize=request.blksize,
                                             windowsize=request.windowsize, oack=request.oack,
                                             inter_packet_seconds=packet_delay_us / 1_000_000)
                    totals['transfers_succeeded'] += 1
                    print(f'STAGE2 SENT {request.name} bytes={sent}; verify U-Boot CRC before booti', flush=True)
                    if once:
                        return
                except (OSError, RuntimeError, TimeoutError) as error:
                    totals['transfers_failed'] += 1
                    event('FAILED', name=request.name, error_type=type(error).__name__, error=str(error), next='waiting for a new RRQ')
                except KeyboardInterrupt:
                    totals['transfers_interrupted'] += 1
                    event('INTERRUPTED', name=request.name, reason='Ctrl-C; printing partial transfer stats')
                    raise
                finally:
                    if display is not None:
                        display.close()
                    if observed is not None:
                        observed.summary()
                    totals['bytes_acked'] += stats.bytes_acked
                    print(stats.summary(), flush=True)
    finally:
        event('SERVER_TOTALS', **totals)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True, type=Path)
    p.add_argument('--dtb', required=True, type=Path)
    p.add_argument('--bind', default='192.168.137.1')
    p.add_argument('--board', default='192.168.137.30')
    p.add_argument('--port', default=69, type=int)
    p.add_argument('--once', action='store_true')
    p.add_argument('--manifest', type=Path, help='explicit paired Image/DTB manifest; default is the original V3 pair')
    p.add_argument('--max-blksize', type=int, choices=(512, 1024), default=1024)
    p.add_argument('--max-windowsize', type=int, choices=range(1, tftp.MAX_WINDOWSIZE + 1), default=1,
                   help='maximum negotiated window, default 1; a missing client option always stays 1')
    p.add_argument('--packet-delay-us', type=float, default=100,
                   help='within-window DATA spacing, default 100 microseconds; 0 disables pacing')
    a = p.parse_args()
    try:
        verify_engine()
        serve(prepare(a.image, a.dtb, a.manifest), a.bind, a.board, a.port, a.once,
              max_blksize=a.max_blksize, max_windowsize=a.max_windowsize,
              packet_delay_us=a.packet_delay_us)
    except KeyboardInterrupt:
        event('STOPPED', reason='Ctrl-C; current/previous transfer stats and server totals are above')
        raise SystemExit(130)
    except (OSError, ValueError) as error:
        event('STARTUP_FAILED', error_type=type(error).__name__, error=str(error))
        raise SystemExit(1)
