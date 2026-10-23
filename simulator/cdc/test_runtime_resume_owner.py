#!/usr/bin/env python3
"""Independent temporal properties for the one-token resume admission law.

This is a bounded control model plus production-source guard, not RTL simulation.
The real three-clock runtime regression remains the hardware acceptance gate.
"""
import itertools
from pathlib import Path
import unittest


class Endpoint:
    def __init__(self):
        self.active = True
        self.ack = True
        self.epoch = 23
        self.pending = False
        self.release_pending = False
        self.edges = 0
        self.released = False

    def tick(self, valid=False, epoch=23, drained=False, external_stop=False,
             response_ready=False, reset=False):
        ready = self.active and self.ack and not self.pending and epoch == self.epoch
        accepted = valid and ready
        applied = self.pending and self.active and self.ack and drained
        response = self.release_pending and self.released
        prior_stop = self.active or external_stop
        if reset:
            self.active = self.ack = self.pending = self.release_pending = self.released = False
            self.edges = 0
            return False, False, False
        if self.release_pending and not self.released:
            if prior_stop:
                self.edges = 0
            elif self.edges == 1:
                self.released = True
            else:
                self.edges += 1
        if accepted:
            self.pending = True
        if applied:
            self.pending = self.active = self.ack = False
            self.release_pending = True
            self.edges = 0
            self.released = False
        if response and response_ready:
            self.release_pending = self.released = False
            self.edges = 0
        return accepted, applied, response


class ResumeOwnerTest(unittest.TestCase):
    def test_all_short_stall_sequences(self):
        for drains in itertools.product((False, True), repeat=6):
            d = Endpoint()
            accepted_at = applied_at = None
            for cycle, drained in enumerate(drains):
                accepted, applied, response = d.tick(valid=True, drained=drained)
                if accepted:
                    self.assertIsNone(accepted_at)
                    accepted_at = cycle
                if applied:
                    self.assertIsNone(applied_at)
                    self.assertLess(accepted_at, cycle)
                    self.assertTrue(drained)
                    applied_at = cycle
                if response:
                    self.assertIsNotNone(applied_at)
                    self.assertGreaterEqual(cycle, applied_at + 3)
                if applied_at is None:
                    self.assertTrue(d.active)
            self.assertEqual(accepted_at, 0)

    def test_stale_duplicate_and_unacknowledged(self):
        d = Endpoint()
        for epoch in (0, 22, 24, 255):
            self.assertEqual(d.tick(valid=True, epoch=epoch, drained=True), (False, False, False))
        d.ack = False
        self.assertFalse(d.tick(valid=True, drained=True)[0])
        d.ack = True
        self.assertTrue(d.tick(valid=True)[0])
        for _ in range(9):
            self.assertEqual(d.tick(valid=True), (False, False, False))
        self.assertEqual(d.tick(valid=True, drained=True), (False, True, False))
        self.assertFalse(d.tick(valid=True, drained=True)[0])

    def test_real_release_edges_and_response_backpressure(self):
        d = Endpoint()
        d.tick(valid=True)
        # A cancel already serialized by fabric cannot revoke this token.
        for _ in range(5):
            self.assertFalse(d.tick()[1])
            self.assertTrue(d.active)
        self.assertTrue(d.tick(drained=True)[1])
        for _ in range(5):
            self.assertFalse(d.tick(external_stop=True)[2])
        self.assertFalse(d.tick()[2])
        self.assertFalse(d.tick()[2])
        for _ in range(12):
            self.assertTrue(d.tick()[2])
            self.assertEqual(d.epoch, 23)
        self.assertTrue(d.tick(response_ready=True)[2])
        self.assertFalse(d.tick()[2])

    def test_cold_reset_drops_pending_or_response(self):
        for release in (False, True):
            d = Endpoint()
            d.tick(valid=True)
            if release:
                d.tick(drained=True)
                d.tick(); d.tick()
            d.tick(reset=True)
            for _ in range(10):
                self.assertEqual(d.tick(valid=True, drained=True), (False, False, False))

    def test_production_guard(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / 'src/main/scala/platform/CommonI1CpuTile.scala').read_text()
        self.assertIn('resume.ready := runtimeActive && runtimeAcknowledged && !resumePending &&', source)
        self.assertIn('val apply = resumePending && privateDrained && runtimeAcknowledged', source)
        self.assertIn('when(applyResume) {\n                releasePending.get := true.B', source)
        self.assertIn('when(releaseEdges === 1.U) { released := true.B }', source)
        self.assertIn('response.valid := releasePending.get && released', source)
        self.assertIn('resume.ready := privateDrained && runtimeAcknowledged && resume.bits === runtimeEpoch', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
