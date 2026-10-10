"""Host-only oracle/mutation tests. These never establish actual RTL behavior."""
from copy import deepcopy
import unittest
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from ports import INPUTS, OUTPUTS
from pf_oracle import PrefetchLedger, check_policy
from cache_base import Contract, Context, Owner, Reservation, Intent, Token, verify_trace, write_final_images


class OracleTests(unittest.TestCase):
    def test_policy_truth_table_including_ineligible_and_exhausted_offers(self):
        for policy in (False, True):
            for busy in (False, True):
                for episode in (False, True):
                    for proof in (False, True):
                        for hit in (False, True):
                            allowed = not busy and (policy or not episode) and (not proof or (policy and hit))
                            fields = dict(busy=busy, episode=episode, proof_offer=proof, eligible_hit=hit)
                            for event in ('candidate', 'allocated'):
                                with self.subTest(policy=policy, **fields, event=event):
                                    pulses = {'candidate': False, 'allocated': False, event: True}
                                    if allowed:
                                        check_policy(policy, **fields, **pulses)
                                    else:
                                        with self.assertRaises(AssertionError):
                                            check_policy(policy, **fields, **pulses)
                            check_policy(policy, **fields, candidate=False, allocated=False)

    def row(self, ledger):
        a, s = dict.fromkeys(OUTPUTS, 0), dict.fromkeys(INPUTS, 0)
        a['prefetchBusy'] = int(not ledger.empty())
        a['mshrMask'] = a['pfObservation.mshrLiveMask'] = sum(1 << k for k in ledger.misses)
        a['pfObservation.mshrPrefetchMask'] = a['mshrMask']
        a['pfObservation.wbLiveMask'] = a['pfObservation.wbPrefetchMask'] = sum(1 << k for k in ledger.releases)
        a['prefetch.missOwners'], a['prefetch.releaseOwners'] = len(ledger.misses), len(ledger.releases)
        return a, s, {'request': None, 'exhausted': False}

    def sample(self, ledger, a, s, before):
        ledger.sample(a, s, before, sum(ledger.count.values()) + 1)

    def candidate(self, ledger):
        a, s, before = self.row(ledger)
        a['prefetch.candidate'] = a['pfObservation.candidate'] = 1
        a['upstream.request.ready'] = s['upstream.request.valid'] = s['upstream.request.bits.prefetchNextAllowed'] = 1
        before['request'] = {'address': 4224, 'write': False, 'ordinary': True, 'eligible': False, 'resident': True}
        self.sample(ledger, a, s, before)

    def allocate(self, ledger):
        a, s, before = self.row(ledger)
        a['prefetch.allocated'] = a['pfObservation.allocated'] = 1
        a['pfObservation.allocatedSlot'], a['pfObservation.allocatedAddress'] = 1, 4288
        self.sample(ledger, a, s, before)

    def acquire(self, ledger):
        a, s, before = self.row(ledger)
        a['tl.a.valid'] = s['tl.a.ready'] = 1
        a['tl.a.bits.source'], a['tl.a.bits.address'] = 1, 4288
        self.sample(ledger, a, s, before)

    def grants_and_e(self, ledger, error=False):
        for beat in range(8):
            a, s, before = self.row(ledger)
            s['tl.d.valid'] = a['tl.d.ready'] = 1
            s.update({'tl.d.bits.opcode': 5, 'tl.d.bits.source': 1, 'tl.d.bits.sink': 1,
                      'tl.d.bits.data': (1 << 63) + beat, 'tl.d.bits.denied': int(error and beat == 7)})
            self.sample(ledger, a, s, before)
        a, s, before = self.row(ledger)
        a['tl.e.valid'] = s['tl.e.ready'] = a['tl.e.bits.sink'] = 1
        self.sample(ledger, a, s, before)

    def refill(self, ledger, error=False, mutate_word=False):
        a, s, before = self.row(ledger)
        a.update({'pfObservation.refill': 1, 'pfObservation.refillPrefetch': 1,
                  'pfObservation.refillSlot': 1, 'pfObservation.refillAddress': 4288,
                  'pfObservation.refillError': int(error), 'prefetch.error': int(error),
                  'lineWrite': int(not error), 'lineWriteAddress': 4288})
        for beat in range(8):
            a['installWord' + str(beat)] = (1 << 63) + beat
        if mutate_word:
            a['installWord3'] ^= 1 << 63
        self.sample(ledger, a, s, before)

    def test_full_uint64_grant_bytes_and_exact_error_lifetime(self):
        for error in (False, True):
            ledger = PrefetchLedger(True)
            self.candidate(ledger)
            self.allocate(ledger)
            self.acquire(ledger)
            self.grants_and_e(ledger, error)
            self.refill(ledger, error)
            self.assertTrue(ledger.empty())
            self.assertEqual(ledger.count['error'], int(error))
            self.sample(ledger, *self.row(ledger))

    def test_mutated_grant_data_is_rejected(self):
        ledger = PrefetchLedger(True)
        self.candidate(ledger)
        self.allocate(ledger)
        self.acquire(ledger)
        self.grants_and_e(ledger)
        with self.assertRaisesRegex(AssertionError, 'SRAM bytes'):
            self.refill(ledger, mutate_word=True)

    def test_release_obligation_outlives_prefetch_mshr(self):
        ledger = PrefetchLedger(True)
        self.candidate(ledger)
        self.allocate(ledger)
        a, s, before = self.row(ledger)
        a.update({'pfObservation.wbCapture': 1, 'pfObservation.wbCapturePrefetch': 1,
                  'pfObservation.wbCaptureSlot': 0, 'pfObservation.wbCaptureMshr': 1,
                  'pfObservation.wbCaptureAddress': 4800, 'pfObservation.wbCaptureDirty': 1,
                  'pfObservation.wbCaptureFromMiss': 1})
        self.sample(ledger, a, s, before)
        for beat in range(8):
            a, s, before = self.row(ledger)
            a.update({'tl.c.valid': 1, 'tl.c.bits.opcode': 7, 'tl.c.bits.source': 2, 'tl.c.bits.address': 4800})
            s['tl.c.ready'] = 1
            self.sample(ledger, a, s, before)
        self.acquire(ledger)
        self.grants_and_e(ledger)
        self.refill(ledger)
        self.assertFalse(ledger.misses)
        self.assertTrue(ledger.releases)
        a, s, before = self.row(ledger)
        a['accepted.valid'] = 1
        with self.assertRaisesRegex(AssertionError, 'pre-edge PF'):
            self.sample(deepcopy(ledger), a, s, before)
        a, s, before = self.row(ledger)
        a['prefetchBusy'] = 0
        with self.assertRaisesRegex(AssertionError, 'busy lost'):
            self.sample(deepcopy(ledger), a, s, before)
        a, s, before = self.row(ledger)
        s.update({'tl.d.valid': 1, 'tl.d.bits.opcode': 6, 'tl.d.bits.source': 2})
        a['tl.d.ready'] = 1
        self.sample(ledger, a, s, before)
        self.assertTrue(ledger.empty())

    def test_held_proof_cancels_without_ready_authority(self):
        ledger = PrefetchLedger(True)
        self.candidate(ledger)
        a, s, before = self.row(ledger)
        s['upstream.request.valid'] = s['posted.requestProof.valid'] = 1
        before['request'] = {'address': 4224, 'write': True, 'ordinary': True, 'eligible': False, 'resident': True}
        self.sample(ledger, a, s, before)
        self.assertEqual(ledger.count['candidate_cancelled'], 1)
        self.assertTrue(ledger.empty())

    def test_phantom_allocation_and_detached_public_events_rejected(self):
        ledger = PrefetchLedger(True)
        a, s, before = self.row(ledger)
        a['prefetch.allocated'] = a['pfObservation.allocated'] = 1
        with self.assertRaisesRegex(AssertionError, 'without.*prior candidate'):
            self.sample(ledger, a, s, before)
        a['pfObservation.allocated'] = 0
        with self.assertRaisesRegex(AssertionError, 'public PF events'):
            self.sample(ledger, a, s, before)

    def test_final_byte_evidence_rejects_mutation_and_preserves_both_images(self):
        expected = {a: (a * 29 + 11) & 255 for a in range(4096, 8192)}
        backing = dict(expected)
        backing[6179] ^= 0x80
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(AssertionError, 'authored final bytes'):
                write_final_images(Path(temp), 'bad', expected, backing)
            self.assertEqual(list(Path(temp).iterdir()), [])
            backing[6179] ^= 0x80
            result = write_final_images(Path(temp), 'good', expected, backing)
            for item in result.values():
                data = (Path(temp) / item['file']).read_bytes()
                self.assertEqual(len(data), 4096)
                self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
                self.assertEqual(data[6179 - 4096], expected[6179])

    def test_gzip_trace_is_lossless_and_rejects_missing_rows(self):
        raw = b''.join((json.dumps({'input': {'token': (1 << 64) - 1}, 'actual': {'cycle': n}}) + '\n').encode()
                       for n in range(1, 4))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace.jsonl.gz'
            with gzip.open(path, 'wb') as stream:
                stream.write(raw)
            result = verify_trace(path, 3)
            self.assertEqual(result['rows'], 3)
            self.assertEqual(result['uncompressed_sha256'], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(AssertionError, 'dropped or duplicated'):
                verify_trace(path, 4)

    def test_posted_contract_preserves_full_token_and_generation(self):
        memory = {a: a & 255 for a in range(4096, 8192)}
        model = Contract(memory)
        intent = Intent(Token((1 << 63) + 17, 1), 4160, 0xAABBCCDD, 2)
        owner = Owner(0, 0)
        context = Context(owner, owner, 0, 4160)
        reservation = Reservation(0, 1)
        model.accept(intent, context, reservation, 0, True)
        model.response_complete(0, intent.token)
        with self.assertRaisesRegex(AssertionError, 'ACK'):
            model.ack(Token(17, 1), 0)
        with self.assertRaisesRegex(AssertionError, 'unknown or released full owner'):
            model.event(Context(Owner(0, 1 << 32), owner, 0, 4160), reservation)
        model.ack(intent.token, 0)
        self.assertIn(intent.token, model.acknowledged)


if __name__ == '__main__':
    unittest.main(verbosity=2)
