#!/usr/bin/env python3
"""Cross-language TFTP check using the real host sender and portable C receiver.

Only in-memory queues carry packets. Real socket creation is forbidden. The
independent adapter constructs ARP/IPv4/UDP frames, checks ordered RAM stores,
and verifies the final payload with Python zlib. No board or hardware tools.
"""
import argparse
import ctypes as C
import io
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch
import zlib

import netboot_host as host

U8, U32, U64 = C.c_uint8, C.c_uint32, C.c_uint64
Now = C.CFUNCTYPE(U64)
Send = C.CFUNCTYPE(C.c_int, C.POINTER(U8), C.c_uint)
Recv = C.CFUNCTYPE(C.c_int, C.POINTER(U8), U64)
Store = C.CFUNCTYPE(C.c_int, U32, C.POINTER(U8), C.c_uint)
Verify = C.CFUNCTYPE(C.c_int, U32, U32)


class Bridge(C.Structure):
    _fields_ = [("now", Now), ("send", Send), ("recv", Recv), ("store", Store),
                ("verify", Verify), ("tx", U8 * 512), ("rx", U8 * 2048)]


BRIDGE_SOURCE = r'''#include "netboot.h"
struct bridge {
    uint64_t (*now)(void);
    int (*send)(const uint8_t *,unsigned);
    int (*recv)(uint8_t *,uint64_t);
    int (*store)(uint32_t,const uint8_t *,unsigned);
    int (*verify)(uint32_t,uint32_t);
    uint8_t tx[512],rx[2048];
};
static uint64_t now(void *p) { return ((struct bridge *)p)->now(); }
static int send(void *p,unsigned n) { struct bridge *b=p; return b->send(b->tx,n); }
static int recv(void *p,uint64_t n) { struct bridge *b=p; return b->recv(b->rx,n); }
static int store(void *p,uint32_t off,const uint8_t *data,unsigned n) { return ((struct bridge *)p)->store(off,data,n); }
static int verify(void *p,uint32_t n,uint32_t crc) { return ((struct bridge *)p)->verify(n,crc); }
int bridge_run(struct bridge *b,uint32_t *entry,uint32_t *length) {
    struct nb_ops o={.context=b,.tx=b->tx,.rx=b->rx,.mac={2,0x56,0x41,0x4c,0,1},
      .ip=0xc0a8891e,.server_ip=0xc0a88901,.base=0x80200000,.limit=0x10000000,.hz=1000,
      .now=now,.send=send,.recv=recv,.store=store,.verify=verify,.request_blksize=1024,.request_windowsize=4};
    return nb_tftp(&o,"valence.vld",entry,length);
}
'''

MAC = bytes.fromhex("0256414c0001")
SERVER_MAC = bytes.fromhex("02aabbccdd01")
IP = bytes([192, 168, 137, 30])
SERVER_IP = bytes([192, 168, 137, 1])
PEER = ("192.168.137.30", 49152)


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    value = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while value >> 16:
        value = (value & 65535) + (value >> 16)
    return (~value) & 65535


def udp(data):
    packet = struct.pack("!4H", 43000, 49152, len(data) + 8, 0) + data
    pseudo = SERVER_IP + IP + struct.pack("!BBH", 0, 17, len(packet))
    check = checksum(pseudo + packet) or 65535
    packet = packet[:6] + struct.pack("!H", check) + packet[8:]
    header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, len(packet) + 20, 0,
                         0x4000, 64, 17, 0, SERVER_IP, IP)
    header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
    return MAC + SERVER_MAC + b"\x08\x00" + header + packet


def run(lib, fault):
    incoming, outgoing = queue.Queue(), queue.Queue()
    threads, result = [], []
    stored = bytearray()
    dropped, held, verified = False, None, 0
    payload = bytes(index % 251 for index in range(4060 if fault == "zero_eof" else 10001))
    packed = host.header(len(payload), zlib.crc32(payload)) + payload
    last_block = len(packed) // 1024 + 1

    class SocketAdapter:
        def settimeout(self, timeout):
            self.timeout = timeout

        def recvfrom(self, size):
            try:
                return outgoing.get(timeout=self.timeout)
            except queue.Empty:
                raise socket.timeout() from None

        def sendto(self, data, destination):
            nonlocal dropped, held
            assert destination == PEER
            opcode, block = struct.unpack("!HH", data[:4])
            if not dropped and ((fault == "oack" and opcode == 6) or
                                (fault == "data" and opcode == 3 and block == 2)):
                dropped = True
                return
            if fault == "reorder" and opcode == 3 and block == 2 and not dropped:
                held = data
                return
            incoming.put(udp(data))
            if held is not None and opcode == 3 and block == 3:
                dropped = True
                incoming.put(udp(held))
                held = None

    def sender(rrq):
        try:
            request = host.parse_request(rrq)
            assert request.name == "valence.vld"
            assert (request.blksize, request.windowsize) == (1024, 4)
            result.append(host.transfer(SocketAdapter(), PEER, io.BytesIO(packed),
                                        retry_seconds=0.25, retries=10, blksize=request.blksize,
                                        windowsize=request.windowsize, oack=request.oack))
        except Exception as error:
            result.append(error)

    @Now
    def now():
        return int(time.monotonic() * 1000)

    @Send
    def send(pointer, size):
        nonlocal dropped
        packet = C.string_at(pointer, size)
        if packet[12:14] == b"\x08\x06":
            incoming.put(MAC + SERVER_MAC + b"\x08\x06" +
                         struct.pack("!HHBBH", 1, 0x800, 6, 4, 2) +
                         SERVER_MAC + SERVER_IP + MAC + IP)
            return 0
        total = struct.unpack("!H", packet[16:18])[0]
        if checksum(packet[14:34]):
            return -1
        pseudo = packet[26:34] + struct.pack("!BBH", 0, 17, total - 20)
        if checksum(pseudo + packet[34:14 + total]):
            return -1
        data = packet[42:14 + total]
        opcode = struct.unpack("!H", data[:2])[0]
        if opcode == 1:
            if not threads:
                thread = threading.Thread(target=sender, args=(data,), daemon=True)
                threads.append(thread)
                thread.start()
        elif opcode == 4:
            block = struct.unpack("!H", data[2:4])[0]
            if not dropped and ((fault == "ack0" and block == 0) or
                                (fault == "ack4" and block == 4) or
                                (fault in ("eof", "zero_eof") and block == last_block)):
                dropped = True
                return 0
            outgoing.put((data, PEER))
        elif opcode == 5:
            outgoing.put((data, PEER))
        else:
            return -1
        return 0

    @Recv
    def recv(pointer, budget):
        try:
            packet = incoming.get(timeout=budget / 1000)
        except queue.Empty:
            return 0
        if len(packet) > 2048:
            return -1
        C.memmove(pointer, packet, len(packet))
        return len(packet)

    @Store
    def store(offset, pointer, size):
        if offset != len(stored) or offset + size > len(payload):
            return -1
        stored.extend(C.string_at(pointer, size))
        return 0

    @Verify
    def verify(size, wanted):
        nonlocal verified
        verified += 1
        return 0 if size == len(stored) and zlib.crc32(stored) == wanted else -1

    bridge = Bridge(now, send, recv, store, verify)
    entry, length = U32(), U32()
    good = lib.bridge_run(C.byref(bridge), C.byref(entry), C.byref(length))
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads), (fault, "host did not finish")
    assert good and stored == payload and result == [len(packed)], (fault, good, len(stored), result)
    assert entry.value == 0x80200000 and length.value == len(payload) and verified == 1
    assert fault == "clean" or dropped, (fault, "fault was not injected")
    print("TFTP_C_PY_INTEROP_PASS", fault, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="C compiler for the portable engine")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="netboot-interop-") as directory:
        bridge, library = Path(directory) / "bridge.c", Path(directory) / "bridge.so"
        bridge.write_text(BRIDGE_SOURCE)
        subprocess.run([args.cc, "-std=c11", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        "-I", str(source), str(bridge), str(source / "netboot.c"), str(source / "crc32.c"),
                        "-o", str(library)], check=True)
        lib = C.CDLL(str(library))
        lib.bridge_run.argtypes = [C.POINTER(Bridge), C.POINTER(U32), C.POINTER(U32)]
        # The adapter uses socket.timeout only. Any real socket is a test failure.
        with patch("socket.socket", side_effect=AssertionError("real sockets forbidden in interop test")):
            for fault in ("clean", "data", "reorder", "oack", "ack0", "ack4", "eof", "zero_eof"):
                run(lib, fault)
    print("BOOTROM_TFTP_INTEROP_PASS cases=8 real_sockets=0 python_sender=1 c_receiver=1", flush=True)


if __name__ == "__main__":
    main()
