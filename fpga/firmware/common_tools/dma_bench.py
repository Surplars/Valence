#!/usr/bin/python3
"""Explicit bounded DMA memcpy test on driver-owned allocations. No automatic retry."""
import argparse
import ctypes
import errno
import json
import os
import re
from pathlib import Path
import sys


def parse_status(text):
    data = {}
    for word in text.split():
        key, value = word.split('=', 1)
        if key in data:
            raise ValueError('duplicate DMA field')
        data[key] = value
    numeric = ('bytes', 'iterations', 'elapsed_ns', 'payload_bytes_per_sec',
               'logical_rw_bytes_per_sec', 'verified', 'faulted', 'run_sequence', 'last_iteration')
    for key in numeric:
        value = data[key]
        if not value.isdecimal() or not 0 <= int(value) < 1 << 64:
            raise ValueError('invalid DMA numeric field: ' + key)
        data[key] = int(value)
    for key in ('last_errno', 'last_cookie', 'last_result'):
        value = data[key]
        if not re.fullmatch(r'-?[0-9]+', value) or not -(1 << 31) <= int(value) < 1 << 31:
            raise ValueError('invalid DMA signed diagnostic: ' + key)
        data[key] = int(value)
    if data['last_iteration'] > 0xffffffff:
        raise ValueError('invalid DMA iteration diagnostic')
    if data['faulted'] not in (0, 1) or data['verified'] not in (0, 1):
        raise ValueError('invalid DMA boolean')
    if data.get('timing') != 'dmaengine_submit_to_callback':
        raise ValueError('unknown timing semantics')
    if data['logical_rw_bytes_per_sec'] != 2 * data['payload_bytes_per_sec']:
        raise ValueError('DMA rate field mismatch')
    return data


def discover():
    entries = [p for p in Path('/sys/bus/platform/drivers/valence-dma-bench').glob('*/benchmark') if p.is_file()]
    if len(entries) != 1:
        raise RuntimeError('One bound DMA benchmark device is required; inspect DT, module status and dmesg')
    return entries[0]


def validate_request(size, iterations):
    if not 8 <= size <= 8 * 1024 * 1024 or size % 8 or not 1 <= iterations <= 64:
        raise ValueError('bytes8..8388608 aligned8; iterations1..64 required')


def write_once(path, payload):
    # ctypes write deliberately avoids Python's automatic EINTR syscall retry.
    # Any error or short write is uncertain: report it, never issue another request.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.write.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)
    libc.write.restype = ctypes.c_ssize_t
    fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    try:
        buf = ctypes.create_string_buffer(payload)
        written = libc.write(fd, buf, len(payload))
        if written < 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        if written != len(payload):
            raise OSError(errno.EIO, 'Short sysfs write; request outcome uncertain, do not retry')
    finally:
        os.close(fd)


def evaluate(before, after, size, iterations):
    if after['run_sequence'] != before['run_sequence'] + 1:
        raise RuntimeError('Run generation mismatch or concurrent request; no attributed benchmark result')
    if (after['bytes'] != size or after['iterations'] != iterations or not after['elapsed_ns'] or
            after['verified'] != 1 or after['faulted'] != 0 or
            after.get('last_reason') != 'pass' or after.get('last_stage') != 'complete' or
            after['last_errno'] != 0 or after['last_result'] != 0 or
            after['last_iteration'] != iterations or after['last_cookie'] <= 0):
        raise RuntimeError('DMA run did not finish verified; inspect the recorded result and dmesg, do not retry blindly')
    expected_rate = size * iterations * 1000000000 // after['elapsed_ns']
    if after['payload_bytes_per_sec'] != expected_rate:
        raise RuntimeError('DMA payload rate disagrees with measured bytes and interval')
    return after


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'run'))
    parser.add_argument('--bytes', type=int, default=4096)
    parser.add_argument('--iterations', type=int, default=1)
    args = parser.parse_args(argv)
    validate_request(args.bytes, args.iterations)
    path = discover()
    before = parse_status(path.read_text())
    if args.action == 'status':
        print(json.dumps({'kind': 'last_result_only_no_test_started', 'result': before}, sort_keys=True))
        return
    if os.geteuid() != 0:
        raise RuntimeError('Explicit DMA run requires root')
    if before['faulted']:
        raise RuntimeError('DMA fault latched; no write performed. Preserve logs and reset before a new test.')
    print('Explicit DMA run: private coherent buffers; one submission, no retry; up to10s per iteration.', flush=True)
    try:
        write_once(path, f'{args.bytes} {args.iterations}\n'.encode('ascii'))
    except OSError:
        try:
            print(json.dumps({'write_failed_or_uncertain': True, 'current_status': parse_status(path.read_text())}), file=sys.stderr)
        finally:
            raise
    after = evaluate(before, parse_status(path.read_text()), args.bytes, args.iterations)
    print(json.dumps({'kind': 'completed_verified_dma_run', 'result': after,
                      'payload_mib_s': after['payload_bytes_per_sec'] / 1048576,
                      'logical_rw_mib_s': after['logical_rw_bytes_per_sec'] / 1048576,
                      'semantics': 'submit-to-callback elapsed; CPU fill/verification excluded; not DDR/MIG peak'}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f'DMA_BENCH_FAILED: {error}; no automatic retry', file=sys.stderr)
        raise SystemExit(1)
