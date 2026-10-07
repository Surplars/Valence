#!/usr/bin/env python3
"""PC-side counterpart for Valence net-bench (not an iperf protocol)."""
import argparse
import socket
import struct
import time

def exact(sock, count):
    result = bytearray()
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            raise RuntimeError('unexpected EOF')
        result.extend(chunk)
    return bytes(result)

def serve(conn):
    conn.settimeout(30)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    magic, mode, reserved, count = struct.unpack('!8sIIQ', exact(conn, 24))
    if magic != b'VNETB001' or mode not in (1, 2) or reserved or not 0 < count <= 256 * 1048576:
        raise RuntimeError('invalid benchmark header')
    pattern = bytes([0xa5]) * 16384
    begin, done = time.monotonic_ns(), 0
    while done < count:
        chunk = min(count - done, len(pattern))
        if mode == 1:
            if exact(conn, chunk) != pattern[:chunk]:
                raise RuntimeError('payload verification failed')
        else:
            conn.sendall(pattern[:chunk])
        done += chunk
    elapsed = time.monotonic_ns() - begin
    if mode == 1:
        conn.sendall(struct.pack('!8sQQ', b'VNETACK1', count, elapsed))
    else:
        magic, confirmed, elapsed = struct.unpack('!8sQQ', exact(conn, 24))
        if magic != b'VNETACK1' or confirmed != count or not elapsed:
            raise RuntimeError('invalid receiver acknowledgement')
    print(f'PC {"RX" if mode == 1 else "TX"} verified={count} bytes '
          f'receiver={elapsed / 1e9:.6f}s {count * 1e9 / elapsed / 1048576:.3f} MiB/s PASS', flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='192.168.137.1')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.bind, args.port))
        server.listen(1)
        print(f'LISTEN {args.bind}:{server.getsockname()[1]} (manual board test only)', flush=True)
        while True:
            conn, peer = server.accept()
            with conn:
                print('PEER ' + str(peer), flush=True)
                serve(conn)
            if args.once:
                break

if __name__ == '__main__':
    main()
