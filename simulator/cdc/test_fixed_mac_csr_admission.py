#!/usr/bin/env python3
"""Bounded control-law proof, not emitted RTL or physical timing qualification.

The documented FixedMacBoundary input contract closes upstream CSR producers
before any PARK offer. A PARK offer therefore has no simultaneous CSR valid.
Keep this assumption explicit: generic Decoupled traffic does not imply it.
"""
import itertools
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'src/main/scala/ip/ethernet/FixedSourceManagedGmac.scala'


def csr(current_park, command_valid, command_park, request_valid, mailbox_ready, old):
    closed = current_park or (old and command_valid and command_park)
    ready = mailbox_ready and not closed
    return ready, request_valid and ready


class FixedMacCsrAdmissionTest(unittest.TestCase):
    def test_legal_request_handshake_equivalence(self):
        checked = 0
        for state in itertools.product((False, True), repeat=6):
            current, valid, park, request, ready, upstream_closed = state
            # Existing documented PARK-offer contract, not a new permission to
            # register or weaken a live drain witness.
            if valid and park and (request or not upstream_closed):
                continue
            before = csr(current, valid, park, request, ready, True)
            after = csr(current, valid, park, request, ready, False)
            self.assertEqual(before[1], after[1])
            if request:
                self.assertEqual(before[0], after[0])
            checked += 1
        self.assertEqual(checked, 52)

    def test_ready_independent_of_unaccepted_management_offer(self):
        for current, ready in itertools.product((False, True), repeat=2):
            values = {csr(current, valid, park, False, ready, False)[0]
                      for valid, park in itertools.product((False, True), repeat=2)}
            self.assertEqual(values, {ready and not current})

    def test_park_acceptance_edge_and_release(self):
        current = False
        # An accepted PARK cannot coincide with a CSR offer. Its new state
        # blocks a later CSR offer, even while the command receipt is pending.
        self.assertFalse(csr(current, True, True, False, True, False)[1])
        current = True  # command.fire updates current on this edge
        self.assertFalse(csr(current, False, False, True, True, False)[1])
        # Release is not allowed to bypass the previously accepted PARK on its
        # accepting edge. Admission reopens only after current changes.
        self.assertFalse(csr(current, True, False, True, True, False)[1])
        current = False
        self.assertTrue(csr(current, False, False, True, True, False)[1])

    def test_unsent_park_cancellation_preserves_reply_owner(self):
        # An existing reply means the CSR mailbox is not ready/idle. Desired
        # PARK is not an accepted command and must not create a parked owner.
        current = False
        mailbox_ready = False
        self.assertFalse(csr(current, False, True, False, mailbox_ready, False)[1])
        # Cancel the unsent desired PARK; its old CSR reply remains outstanding.
        self.assertFalse(csr(current, True, False, True, mailbox_ready, False)[1])
        mailbox_ready = True  # only actual old reply consumption returns credit
        self.assertTrue(csr(current, False, False, True, mailbox_ready, False)[1])

    def test_source_keeps_live_fences_and_registered_admission(self):
        source = SOURCE.read_text()
        self.assertIn('val closingCsr = current.park\n', source)
        self.assertIn('registers.request.ready := csr.source.request.ready && !closingCsr', source)
        self.assertIn('csr.source.request.valid := registers.request.valid && !closingCsr', source)
        self.assertIn('!registers.request.valid && csr.sourceIdle', source)
        self.assertIn('commands.source.ready && !pendingReceipt && legal && txFence && csrFence', source)
        self.assertIn('when(command.fire) { current := command.bits; pendingReceipt := true.B }', source)
        self.assertIn('assert(controlProducersClosed && !registers.request.valid', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
