#!/usr/bin/env python3
"""Bounded selected-LSU transport tests. Source preparation is not run approval.

Cancellation is authored component control, not real backend head recovery.
No FP, decoder, ROB head-minting, translation, cache/Home or performance claim.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import selectors
import subprocess
import sys
sys.dont_write_bytecode = True
from ports import INPUT_WIDTHS, OUTPUT_WIDTHS
from oracle import Ledger, Op, RAM, Violation, check, schema

HERE = Path(__file__).resolve().parent
TRACE_CAP = 1024 * 1024


def operation(n, **changes):
    size = changes.get('size', 3)
    lane = {0: 3, 1: 2, 2: 4, 3: 0}[size]
    base = Op(name='op-' + str(n), index=n % 16, tag=0x8000000100000000 + n,
        address=RAM + n * 32 + lane, pc=RAM + 0x1000 + 4 * n,
        data=0x87654321FEDCBA98 ^ (n * 257),
        beat=0x80FEDCBA98765480 ^ (0x0101010101010101 * n),
        destination=1 + (n * 7) % 47)
    return replace(base, **changes)


class Bench:
    """Stimulus/transport only; the independent Ledger owns expected lifetimes."""
    def __init__(self, driver, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.tracePath = self.directory / 'trace.jsonl'
        self.trace = self.tracePath.open('x')
        self.stderr = (self.directory / 'driver.stderr').open('x')
        self.child = subprocess.Popen([str(Path(driver).resolve())], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.child.stdout, selectors.EVENT_READ)
        self.model = Ledger()
        self.memoryReady = True
        self.completeReady = True
        self.cancel = set()
        self.reply = None
        self.last = None
        self.ticks = 0
        self.events = []

    def raw(self, inputs, offer=None, checked=True):
        schema(inputs, INPUT_WIDTHS)
        self.ticks += 1
        check(self.ticks <= 256, 'CYCLE_BUDGET: bounded LSU case exceeded')
        wire = ' '.join(name + '=' + str(inputs[name]) for name in INPUT_WIDTHS) + '\n'
        self.child.stdin.write(wire); self.child.stdin.flush()
        check(bool(self.selector.select(timeout=5)), 'DRIVER_OUTPUT_TIMEOUT')
        line = self.child.stdout.readline()
        check(bool(line), 'DRIVER_EOF: see retained driver.stderr')
        actual = json.loads(line)
        schema(actual, OUTPUT_WIDTHS, ('cycle',))
        self.trace.write(json.dumps({'input': inputs, 'actual': actual,
            'offer': asdict(offer) if offer else None, 'checked': checked,
            'wire_input': wire.rstrip(), 'wire_output': line.rstrip()}, separators=(',', ':')) + '\n')
        self.trace.flush()
        check(self.tracePath.stat().st_size <= TRACE_CAP, 'TRACE_BUDGET: preserve outputs and stop')
        if checked:
            take = self.model.observe(inputs, actual, offer)
        else:
            take = False
        self.last = actual
        if self.reply and actual['memory.response.ready'] and inputs['memory.response.valid']:
            self.reply = None
        return take

    def tick(self, offer=None):
        inputs = offer.drive() if offer else dict.fromkeys(INPUT_WIDTHS, 0)
        inputs.update({'memory.request.ready': int(self.memoryReady),
                       'complete.ready': int(self.completeReady)})
        inputs.update({'cancel.' + str(n): int(n in self.cancel) for n in range(4)})
        if self.reply:
            inputs['memory.response.valid'] = 1
            inputs.update({'memory.response.bits.' + k: v for k, v in self.reply.items()})
        return self.raw(inputs, offer)

    def setup(self):
        for reset in (1, 1, 0):
            inputs = dict.fromkeys(INPUT_WIDTHS, 0)
            inputs['reset'] = reset
            self.raw(inputs, checked=False)
        for _ in range(3):
            self.tick()
        self.model.drained()

    def until(self, predicate, why, offer=None, limit=24):
        for _ in range(limit):
            if predicate():
                return
            self.tick(offer)
        check(predicate(), why)

    def accept(self, op):
        self.until(lambda: op.token in self.model.owners, 'START_TIMEOUT: ' + op.name, op)
        return self.model.find(op.token)

    def issue(self, owner):
        self.until(lambda: owner.issued, 'REQUEST_TIMEOUT: ' + owner.op.name)

    def response(self, owner):
        check(owner.issued and not owner.responded and self.reply is None, 'SERVICE_STIMULUS_OWNER')
        self.reply = owner.op.reply(owner.slot)
        self.until(lambda: owner.responded, 'RESPONSE_TIMEOUT: ' + owner.op.name)

    def drain(self):
        check(not self.cancel, 'DRAIN_CONTROL: cancel must be explicitly withdrawn')
        self.memoryReady = self.completeReady = True
        for _ in range(32):
            if not self.reply:
                outstanding = next((o for o in self.model.owners.values() if o.issued and not o.responded), None)
                if outstanding:
                    self.reply = outstanding.op.reply(outstanding.slot)
            self.tick()
            if all(o.drained for o in self.model.owners.values()):
                break
        self.model.drained()
        for _ in range(2):
            self.tick()
        self.model.drained()

    def note(self, name):
        self.events.append({'name': name, 'cycle': self.last['cycle']})
        print('COLLECTION_LSU_CASE', name, 'cycle=' + str(self.last['cycle']), flush=True)

    def anchor(self, name):
        print('TAGGED_LOAD_PUBLISH_ANCHOR', name, 'cycle=' + str(self.last['cycle']), flush=True)

    def stop(self):
        if self.child.poll() is None:
            try:
                self.child.stdin.write('quit\n'); self.child.stdin.flush()
                self.child.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.child.kill(); self.child.wait(timeout=5)
        self.selector.close()
        self.trace.close(); self.stderr.close()


def positive(b):
    b.setup()
    b.memoryReady = b.completeReady = False
    a = b.accept(operation(1, name='A-qualified-held-cancel', collectionRead=True, size=1))
    originalRequest = a.op.request(a.slot)
    other = b.accept(operation(2, name='B-unqualified-other-slot', size=2))
    check(a.slot != other.slot and a.phase == other.phase == 1,
          'HELD_OTHER_SLOT: accepted B must independently own another request slot')
    for _ in range(2):
        b.tick()
    check(not a.issued and not other.issued and b.model.counts['request_hold_other_start'] == 1,
          'HELD_OTHER_SLOT: A did not survive B becoming ready')
    b.cancel = {a.slot}; b.tick(); b.cancel = set(); b.tick()
    check(a.cancelled and not a.drained and not a.issued and a.op.request(a.slot) == originalRequest,
          'CANCEL_HELD: cancellation must retain original offered responsibility')
    b.memoryReady = True
    b.issue(a); b.issue(other)
    b.response(a)
    check(a.responded and not a.drained and a.publications == 0,
          'CANCEL_RESPONSE: response acceptance is distinct from later done drain')
    b.tick()
    check(a.drained and not a.completed and b.model.counts['discards'] == 1,
          'CANCEL_DISCARD: exactly one nonarchitectural drain required')
    b.response(other)
    for _ in range(2):
        b.tick()
    check(not other.completed and other.publications == 1, 'HELD_RETURN: B must retain architectural completion')
    b.drain(); b.note('qualified_hold_other_ready_slot_and_authored_cancel_drain')

    # The exact physical slot and ROB index recur only after A really drained;
    # changing the full tag prevents accidentally treating this as the old owner.
    cOp = operation(3, name='C-reused-index-unqualified', index=a.op.index,
        tag=a.op.tag ^ (1 << 63), collectionRead=False, size=0)
    b.completeReady = False
    c = b.accept(cOp); b.issue(c)
    check(c.slot == a.slot and c.op.index == a.op.index and c.op.tag != a.op.tag,
          'FULL_TOKEN_REUSE: exact slot/index requires distinct full generation')
    b.response(c)
    for _ in range(2):
        b.tick()
    dOp = operation(4, name='D-same-edge-qualified-replacement', index=c.op.index,
                    tag=c.op.tag ^ (1 << 62), collectionRead=True)
    b.completeReady = True; b.memoryReady = False
    check(b.tick(dOp), 'same-edge completed-slot replacement rejected')
    d = b.model.find(dOp.token)
    check(c.completed and d.slot == c.slot and d.op.token != c.op.token and not d.issued,
          'same-index high-generation slot reuse absent')
    for _ in range(2):
        b.tick()
    b.memoryReady = True; b.issue(d); b.response(d); b.drain()
    b.note('full_token_reuse_false_bit_and_same_edge_true_bit_replacement')

    b.memoryReady = b.completeReady = False
    store = b.accept(operation(5, name='E-ordinary-store-false-bit', store=True,
        parallel=False, collectionRead=False, destinationValid=False, size=2))
    for _ in range(2):
        b.tick()
    check(not store.issued and not store.cancelled, 'STORE_OBLIGATION: store is non-cancellable')
    b.memoryReady = True; b.issue(store); b.response(store)
    for _ in range(2):
        b.tick()
    check(not store.completed and store.publications == 0, 'STORE_RETURN: exact completion retained')
    b.drain(); b.note('ordinary_serial_store_false_bit_non_cancellable_drain')
    counts = b.model.counts
    check(all(counts[k] == v for k, v in dict(starts=5, issues=5, responses=5,
          completions=4, discards=1, publications=3, replacements=1).items()),
          'FINAL_CARDINALITIES: five exact owners required')
    check(counts['qualified_holds'] >= 6 and counts['request_hold_other_start'] == 1 and
          counts['completion_stalls'] >= 6, 'NONVACUOUS_TRANSPORT_WITNESSES')


NEGATIVES = ['invalid-handle', 'wrong-domain', 'unsolicited', 'duplicate',
    'held-response-payload', 'oracle-token', 'oracle-data', 'oracle-publish-valid',
    'oracle-publish-destination', 'oracle-publish-duplicate']


def negative(b, mode):
    b.setup()
    if mode in ('invalid-handle', 'wrong-domain', 'unsolicited'):
        handle, anchor = {'invalid-handle': (7, 'invalid_handle_7'),
            'wrong-domain': (4, 'store_domain_handle_4'),
            'unsolicited': (0, 'unsolicited_integer_handle_0')}[mode]
        b.anchor(anchor)
        b.reply = dict(returnHandle=handle, data=0xABCDEF0123456789, error=0, pageFault=0)
        b.tick()
    elif mode == 'held-response-payload':
        op = operation(1)
        b.completeReady = False
        b.reply = op.reply(0)
        check(b.tick(op), 'held-control setup lacks actual hold')
        owner = b.model.find(op.token)
        check(owner.issued and not owner.responded and b.reply is not None,
              'held-control setup lacks actual hold')
        b.anchor('held_response_payload'); b.reply['data'] ^= 1; b.tick()
    else:
        owner = b.accept(operation(1)); b.issue(owner)
        b.completeReady = False
        if mode in ('oracle-publish-valid', 'oracle-publish-destination'):
            b.model.mutation = mode
            b.response(owner)
        else:
            b.response(owner)
            if mode == 'duplicate':
                b.drain(); b.anchor('duplicate_drained_handle')
                b.reply = owner.op.reply(owner.slot); b.tick()
            else:
                check(mode in ('oracle-token', 'oracle-data', 'oracle-publish-duplicate'), 'unknown negative control')
                b.model.mutation = mode; b.tick()
    raise Violation('NEGATIVE_CONTROL_ESCAPED: designated assertion/oracle did not reject')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--negative', choices=NEGATIVES)
    args = parser.parse_args()
    # Runtime authority and global disk watchdog belong to the parent's bound
    # controller. This program is never invoked as part of source/API checking.
    b = Bench(args.driver, args.output)
    status, error = 'FAIL', None
    try:
        negative(b, args.negative) if args.negative else positive(b)
        status = 'PASS'
    except Exception as exc:
        error = str(exc)
        for anchor in b.model.anchors:
            b.anchor(anchor)
        print('TAGGED_LOAD_PUBLISH_REJECT', error, file=sys.stderr, flush=True)
    finally:
        b.stop()
        receipt = {'status': status, 'error': error, 'negative': args.negative,
            'scope': 'selected direct integer LSU transport; authored head bit/cancel; no FP/backend head authority',
            'cycles': b.ticks, 'counts': b.model.counts, 'events': b.events,
            'anchors': b.model.anchors, 'driver_returncode': b.child.returncode,
            'owners': [asdict(o) for o in b.model.owners.values()],
            'source_bindings': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(HERE.glob('*.py'))],
            'driver_sha256': hashlib.sha256(args.driver.read_bytes()).hexdigest(),
            'trace_sha256': hashlib.sha256(b.tracePath.read_bytes()).hexdigest()}
        (args.output / 'RESULT.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
