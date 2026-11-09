#!/usr/bin/env python3
"""First real decoded-backend ownership case. Native execution is separately gated."""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import sys
sys.dont_write_bytecode = True
from decoded import program, RAM
from ports import INPUT_WIDTHS, OUTPUT_WIDTHS
from oracle import Ledger, check, schema

HERE = Path(__file__).resolve().parent
TRACE_CAP = 12 * 1024 * 1024


class Bench:
    def __init__(self, driver, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.trace_path = self.directory / 'trace.jsonl.gz'
        self.trace = gzip.open(self.trace_path, 'xt', encoding='utf-8', compresslevel=6)
        self.stderr = (self.directory / 'driver.stderr').open('x')
        self.child = subprocess.Popen([str(Path(driver).resolve())], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.child.stdout, selectors.EVENT_READ)
        self.model = Ledger()
        self.ready = True
        self.reply = None
        self.last = None
        self.ticks = 0

    def raw(self, inp, offers=(None, None), checked=True):
        schema(inp, INPUT_WIDTHS)
        self.ticks += 1
        check(self.ticks <= 1024, 'BACKEND_CYCLE_BUDGET')
        wire = ' '.join(n + '=' + str(inp[n]) for n in INPUT_WIDTHS) + '\n'
        self.child.stdin.write(wire); self.child.stdin.flush()
        check(bool(self.selector.select(timeout=5)), 'DRIVER_OUTPUT_TIMEOUT')
        line = self.child.stdout.readline()
        check(bool(line), 'DRIVER_EOF: see retained driver.stderr')
        f = json.loads(line)
        schema(f, OUTPUT_WIDTHS, ('cycle',))
        check(f['cycle'] == self.ticks, 'DRIVER_FRAME_SEQUENCE')
        self.trace.write(json.dumps(dict(input=inp, actual=f,
            offers=[asdict(o) if o else None for o in offers], checked=checked), separators=(',', ':')) + '\n')
        self.trace.flush()
        check(self.trace_path.stat().st_size <= TRACE_CAP, 'TRACE_BUDGET_PRESERVE_AND_STOP')
        accepted = self.model.observe(inp, f, offers) if checked else []
        self.last = f
        if self.reply and inp['io.memory.response.valid'] and f['io.memory.response.ready']:
            self.reply = None
        return accepted

    def tick(self, offers=(None, None)):
        inp = dict.fromkeys(INPUT_WIDTHS, 0)
        inp.update({'io.commitEnable': 1, 'io.fetchQuiescent': 1, 'io.vmFlushReady': 1,
                    'io.fenceIFlushReady': 1, 'io.imsic.request.ready': 1,
                    'io.emptyPc': RAM + 0x2000, 'io.timeValue': self.ticks,
                    'io.inspectRegister': self.ticks % 32,
                    'io.memory.request.ready': int(self.ready),
                    'io.posted.externalBusy': int(bool(self.model.external)),
                    'io.posted.contextEpoch': int(self.model.published),
                    'io.loadPrecheck.epoch': int(self.model.published),
                    'io.loadPrecheck.stable': int(self.model.published),
                    'io.posted.blockNew': int(not self.model.published)})
        for lane, op in enumerate(offers):
            if op is None:
                continue
            inp['io.allocate.' + str(lane) + '.valid'] = 1
            d = op.decoded()
            inp.update({'io.allocate.' + str(lane) + '.bits.' + k: v for k, v in d.items()})
            inp.update({'io.rawRequests.' + str(lane) + '.' + k[7:]: v for k, v in d.items() if k.startswith('rename.')})
            inp['io.rawDestinations.' + str(lane)] = d['rename.rd']
        if self.reply:
            inp['io.memory.response.valid'] = 1
            inp.update({'io.memory.response.bits.' + k: v for k, v in self.reply.items()})
        return self.raw(inp, offers)

    def setup(self):
        for reset in (1, 1, 0):
            inp = dict.fromkeys(INPUT_WIDTHS, 0)
            inp['reset'] = reset
            self.raw(inp, checked=False)
        for _ in range(3):
            self.tick()
        check(not self.model.order and not self.last['io.occupancy'] and not self.last['io.memoryBusy'], 'RESET_DRAIN')

    def until(self, predicate, why, offers=(None, None), limit=128):
        for _ in range(limit):
            if predicate():
                return
            self.tick(offers)
        check(predicate(), why)

    def accept(self, op):
        self.until(lambda: op.role in self.model.roles, 'DECODED_ACCEPT_TIMEOUT: ' + op.role, (op, None), limit=32)
        return self.model.roles[op.role]

    def service(self, owner):
        check(owner.requested and not owner.responded and self.reply is None, 'AUTHORED_SERVICE_PREMISE')
        self.reply = owner.reply()
        self.until(lambda: owner.responded, 'SERVICE_RESPONSE_TIMEOUT: ' + owner.instruction.role, limit=32)

    def quiet(self):
        return not self.model.order and not self.last['io.occupancy'] and not self.last['io.recovering'] and \
            not self.last['io.pauseFetch'] and not self.last['io.memoryBusy'] and not self.last['io.pmpRawChanged']

    def stop(self):
        if self.child.poll() is None:
            try:
                self.child.stdin.write('quit\n'); self.child.stdin.flush()
                self.child.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.child.kill(); self.child.wait(timeout=5)
        self.selector.close(); self.trace.close(); self.stderr.close()


def positive(b):
    b.setup()
    instructions = program()
    # All setup instructions are serialized through accepted full tokens and
    # actual retirement, including real CSR-driven fetch recovery.
    for op in instructions[:18]:
        owner = b.accept(op)
        b.until(lambda: owner.retired and b.quiet(), 'SETUP_RETIRE_DRAIN_TIMEOUT: ' + op.role, limit=64)
        b.tick()
    b.until(b.quiet, 'INITIAL_CONTEXT_DRAIN')
    for _ in range(2):
        b.tick(); b.model.context_ready(b.last)
    b.model.publish(b.last)
    b.tick()

    store = b.accept(instructions[18])
    b.until(lambda: store.requested and store.retired, 'POSTED_LOCAL_RETIRE_AND_EXTERNAL_ACCEPT', limit=64)
    check(store.lsu_accepted and not store.responded and store.token in b.model.external,
          'REAL_POSTED_LOCAL_RETIRE_RETAINS_EXTERNAL_RESPONSIBILITY')
    b.model.note('posted_local_retirement_before_service_response', token=list(store.token))
    b.service(store)
    for _ in range(2):
        b.tick()
    check(not b.last['io.posted.busy'] and b.last['observation.postedBusy'] and b.last['io.memoryBusy'] and
          b.model.external == {store.token} and not b.model.pending,
          'SERVICE_DRAIN_MUST_NOT_CLEAR_EXTERNAL_POSTED_OWNER')

    b.ready = False
    divide = b.accept(instructions[19])
    read = b.accept(instructions[20])
    check(divide.accepted < read.accepted and not divide.retired, 'REAL_OLDER_DIV_WINDOW')
    b.until(lambda: read.started and b.last['io.memory.request.valid'], 'REAL_QUALIFIED_HEAD_REQUEST_TIMEOUT')
    check(b.model.counts['prehead_suppressed_cycles'] >= 2 and
          b.model.counts['prehead_candidate_payload_cycles'] >= 1 and not read.requested,
          'OBSERVED_PREHEAD_SUPPRESSION_AND_HELD_HEAD_OFFER')
    b.model.note('accepted_younger_read_suppressed_under_actual_div_head',
                 token=list(read.token), candidate_payload_is_not_valid_selection=True)
    for _ in range(4):
        b.tick()
        check(not read.requested and b.last['io.memory.request.valid'] and b.last['io.collectionHeadRead'] and
              b.model.external == {store.token}, 'QUALIFIED_HELD_REQUEST_WITH_OLDER_EXTERNAL_OWNER')
    b.ready = True
    b.until(lambda: read.requested, 'QUALIFIED_READ_ACCEPT_TIMEOUT', limit=16)
    b.service(read)
    b.until(lambda: read.retired, 'READ_ARCHITECTURAL_RETIRE_TIMEOUT', limit=32)
    check(b.model.external == {store.token} and not b.model.pending and b.last['io.memoryBusy'],
          'READ_RETIREMENT_RETAINS_OLDER_EXTERNAL_RESPONSIBILITY')
    for _ in range(2):
        b.tick()
    b.model.external_complete(store)
    # A full architectural register scan follows actual completion and final
    # external discharge; inspected state must match independently retired data.
    for _ in range(32):
        b.tick()
    expected = b.model.final(b.last)
    b.model.note('final_real_backend_and_external_owner_drain')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    b = Bench(args.driver, args.output)
    status, error, expected = 'FAIL', None, None
    try:
        expected = positive(b)
        status = 'PASS'
    except Exception as exc:
        error = str(exc)
        print('COLLECTION_BACKEND_REJECT', error, file=sys.stderr, flush=True)
    finally:
        b.stop()
        if status == 'PASS' and b.child.returncode != 0:
            status, error = 'FAIL', 'NONZERO_NATIVE_DRIVER_EXIT'
        result = dict(status=status, error=error, cycles=b.ticks, driver_returncode=b.child.returncode,
            counts=dict(b.model.counts), expected_exact_counts=expected, events=b.model.events,
            owners=[asdict(o) for o in b.model.owners.values()],
            external_remaining=[list(t) for t in sorted(b.model.external)],
            architectural_registers=b.model.registers,
            scope='real decoded IntegerBackend head eligibility and exact ownership transport; explicit external posted environment',
            limitations=['No decoder instantiated: independently authored legal decoded inputs.',
                'Pre-head candidate payload is diagnostic only; no valid scheduler-selection witness.',
                'Bare translationEpoch is inactive opaque start-captured transport; active fields are independently predicted.',
                'No adapter, cache/Home, FP dynamic, whole-CPU or performance claim.'],
            source_bindings=[dict(path=str(p.resolve()), bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(HERE.iterdir()) if p.is_file()],
            driver_sha256=hashlib.sha256(args.driver.read_bytes()).hexdigest(),
            trace_sha256=hashlib.sha256(b.trace_path.read_bytes()).hexdigest(), trace_format='gzip JSONL complete scalar input/output frames')
        (args.output / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print('COLLECTION_BACKEND_RESULT', status, 'cycles=' + str(b.ticks), flush=True)
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
