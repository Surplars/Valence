"""Independent ABI ordering model, NOT kernel-module or RTL execution.

The oracle follows the documented level/MSI latch contract. It does not read
driver source or import its register constants. Simultaneous completions can
coalesce into one interrupt; packet ownership, not IRQ count, is the invariant.
"""
import unittest

class Fabric:
    def __init__(self):
        self.running = True
        self.device_enabled = True
        self.source_enabled = True
        self.identity_enabled = True
        self.delivery = True
        self.line = False
        self.source_pending = False
        self.identity_pending = False
        self.tx_done = self.rx_done = False
        self.napi = False
        self.tx_consumed = self.rx_consumed = 0

    def update(self):
        line = self.device_enabled and (self.tx_done or self.rx_done)
        if line and not self.line:
            self.source_pending = True
        if not line:
            self.source_pending = False
        self.line = line
        if self.source_pending and self.source_enabled:
            self.identity_pending = True
            self.source_pending = False

    def complete_packet(self, direction):
        assert not getattr(self, direction + '_done')
        setattr(self, direction + '_done', True)
        self.update()

    def irq(self):
        if not (self.delivery and self.identity_enabled and self.identity_pending):
            return False
        self.identity_pending = False  # STOPEI CSRRW claim
        self.source_enabled = self.identity_enabled = False
        self.source_pending = False  # child mask/ack
        self.device_enabled = False  # hard handler masks DMA before scheduling
        self.update()
        if self.running:
            self.napi = True
        self.source_enabled = self.identity_enabled = True
        if self.line:  # level replay quirk at chip unmask
            self.source_pending = True
        self.update()
        return True

    def consume(self, budget):
        work = 0
        if not self.running:
            return work
        if self.tx_done:
            self.tx_done = False
            self.tx_consumed += 1
        if budget and self.rx_done:
            self.rx_done = False
            self.rx_consumed += 1
            work += 1
        self.update()
        return work

    def finish(self, work, budget):
        if not budget or work == budget:
            return
        self.napi = False
        if self.running:
            self.device_enabled = True
        self.update()

class OrderingTests(unittest.TestCase):
    def test_inactive_source_discards_target_writes(self):
        # Independent register-state oracle from the pinned hardware ABI.
        # At mode=0, each cycle clears target, pending and source-enable.
        def programmed_target(operations):
            mode = target = 0
            for register, value in operations:
                if register == 'mode':
                    mode = value
                else:
                    target = value
                if mode == 0:
                    target = 0
            return target
        self.assertEqual(programmed_target([('mode', 0), ('target', 31), ('mode', 4)]), 0)
        self.assertEqual(programmed_target([('mode', 0), ('mode', 4), ('target', 31)]), 31)

    def test_no_empty_periodic_wakeup(self):
        f = Fabric()
        for _ in range(10000):
            f.update()
            self.assertFalse(f.irq())

    def test_rx_and_tx_coalesce_without_packet_loss(self):
        f = Fabric()
        f.complete_packet('tx'); f.complete_packet('rx')
        self.assertTrue(f.irq())
        work = f.consume(8); f.finish(work, 8)
        self.assertEqual((f.tx_consumed, f.rx_consumed), (1, 1))
        self.assertFalse(f.irq())

    def test_arrival_during_masked_poll_is_latched(self):
        f = Fabric()
        f.complete_packet('rx'); f.irq()
        work = f.consume(8)
        f.complete_packet('rx')
        self.assertFalse(f.irq())
        f.finish(work, 8)
        self.assertTrue(f.irq())
        work = f.consume(8); f.finish(work, 8)
        self.assertEqual(f.rx_consumed, 2)

    def test_arrival_after_napi_completion_before_unmask(self):
        f = Fabric()
        f.complete_packet('tx'); f.irq(); f.consume(8)
        f.napi = False
        f.complete_packet('rx')
        f.finish(0, 8)
        self.assertTrue(f.irq())

    def test_zero_budget_does_not_consume_rx_or_unmask(self):
        f = Fabric()
        f.complete_packet('tx'); f.complete_packet('rx'); f.irq()
        work = f.consume(0); f.finish(work, 0)
        self.assertEqual(f.tx_consumed, 1)
        self.assertEqual(f.rx_consumed, 0)
        self.assertTrue(f.napi)
        self.assertFalse(f.device_enabled)

    def test_exact_budget_keeps_napi_scheduled(self):
        f = Fabric()
        f.complete_packet('rx'); f.irq()
        work = f.consume(1); f.finish(work, 1)
        self.assertTrue(f.napi)
        self.assertFalse(f.device_enabled)
        f.finish(f.consume(1), 1)
        self.assertFalse(f.napi)

    def test_ifdown_between_complete_and_unmask(self):
        f = Fabric()
        f.complete_packet('rx'); f.irq()
        work = f.consume(8)
        f.running = False
        f.finish(work, 8)
        self.assertFalse(f.device_enabled)
        self.assertFalse(f.napi)

    def test_held_level_requires_explicit_aplic_retrigger(self):
        f = Fabric()
        f.complete_packet('rx')
        f.identity_pending = False  # claim without dropping device level
        f.source_enabled = False
        f.source_enabled = True
        f.update()
        self.assertFalse(f.identity_pending)  # no automatic resend
        f.source_pending = f.line  # software SETIPNUM after unmask
        f.update()
        self.assertTrue(f.identity_pending)

if __name__ == '__main__':
    unittest.main()
