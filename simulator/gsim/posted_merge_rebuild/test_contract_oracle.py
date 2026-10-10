import unittest
from dataclasses import replace

from contract_oracle import (Context, Contract, HeldOffer, Intent, Owner, Reservation,
                             Responsibility, Token, Violation)


def fresh(**kwargs):
    return Contract({a: (a * 29 + 11) & 255 for a in range(2048)}, **kwargs)


def offer(model, tag=1, *, address=64, size=3, value=0x1122334455667788,
          slot=0, generation=0, ticket=0, new=True, root=None, victim=None):
    intent = Intent(Token(tag, tag % 16), address, value, size)
    owner = Owner(slot, generation)
    context = Context(owner, root or owner, 0, address & ~63)
    reservation = Reservation(slot, (address // 64) % model.cache_sets,
                              victim_valid=victim is not None,
                              victim_dirty=bool(victim and victim[1]),
                              victim_address=victim[0] if victim else 0)
    model.accept(intent, context, reservation, ticket, new)
    return intent, context, reservation


def acknowledge(model, intent, ticket=0):
    model.response_complete(ticket, intent.token)
    model.ack(intent.token, ticket)


def fill(model, context, reservation, *, source=None, to_t=True, error=False):
    source = context.owner.slot if source is None else source
    model.acquire(context, reservation, source)
    base = model.line(context.line)
    for beat in range(8):
        model.grant_beat(source, int.from_bytes(base[beat * 8:beat * 8 + 8], 'little'),
                         source, to_t=to_t, error=error)
    model.e(source)
    model.refill(context, reservation, base)


def finish(model, intent, context, reservation, ticket=0):
    acknowledge(model, intent, ticket)
    fill(model, context, reservation)
    model.install(context, reservation, model.expected_install(context.owner))
    model.drain(intent.token, context)
    model.release(context, reservation)


class OracleTests(unittest.TestCase):
    def test_dma_before_actual_a_changes_base(self):
        model = fresh()
        old_base = model.line(64)
        intent, context, reservation = offer(model, size=0, value=0xEA)
        acknowledge(model, intent)
        model.probe(64)
        model.dma_write({74: 0x97, 75: 0x52})
        fill(model, context, reservation)
        expected = model.expected_install(context.owner)
        self.assertEqual(expected[0], 0xEA)
        self.assertEqual(expected[10:12], bytes([0x97, 0x52]))
        stale = bytearray(old_base)
        stale[0] = 0xEA
        with self.assertRaises(Violation):
            model.install(context, reservation, bytes(stale))
        model.install(context, reservation, expected)
        model.drain(intent.token, context)
        model.release(context, reservation)
        model.flush()

    def test_overlapping_authored_scalar_bytes(self):
        model = fresh()
        first, context, reservation = offer(model)
        acknowledge(model, first)
        second = Intent(Token(2, 2), 66, 0xA1B2, 1)
        model.accept(second, context, reservation, 1, False)
        acknowledge(model, second, 1)
        third = Intent(Token(3, 3), 71, 0xC3, 0)
        model.accept(third, context, reservation, 0, False)
        acknowledge(model, third)
        fill(model, context, reservation)
        result = model.expected_install(context.owner)
        self.assertEqual(result[:8], bytes([0x88, 0x77, 0xB2, 0xA1, 0x44, 0x33, 0x22, 0xC3]))
        model.install(context, reservation, result)
        for intent in [first, second, third]:
            model.drain(intent.token, context)
        model.release(context, reservation)
        model.flush()

    def test_late_fill_cannot_write_reused_ticket(self):
        model = fresh()
        first, context, reservation = offer(model)
        acknowledge(model, first)
        second = Intent(Token(2, 2), 72, 8)
        model.accept(second, context, reservation, 0, False)
        with self.assertRaises(Violation):
            model.response_complete(0, first.token)
        acknowledge(model, second)
        with self.assertRaises(Violation):
            model.ack(first.token, 0)
        fill(model, context, reservation)
        with self.assertRaises(Violation):
            model.response_complete(0, first.token)
        model.install(context, reservation, model.expected_install(context.owner))
        model.drain(first.token, context)
        model.drain(second.token, context)
        model.release(context, reservation)

    def test_out_of_order_returns_preserve_install_order(self):
        model = fresh()
        first, older, first_reservation = offer(model)
        second, younger, second_reservation = offer(model, 2, address=128, slot=1, generation=1,
                                                    ticket=1, root=older.owner)
        acknowledge(model, first)
        acknowledge(model, second, 1)
        fill(model, younger, second_reservation)
        with self.assertRaises(Violation):
            model.install(younger, second_reservation, model.expected_install(younger.owner))
        fill(model, older, first_reservation)
        for intent, context, reservation in [(first, older, first_reservation), (second, younger, second_reservation)]:
            model.install(context, reservation, model.expected_install(context.owner))
            model.drain(intent.token, context)
            model.release(context, reservation)
        model.flush()

    def test_probe_after_install_with_held_ack_does_not_resurrect(self):
        model = fresh()
        intent, context, reservation = offer(model)
        fill(model, context, reservation)
        original_install = model.expected_install(context.owner)
        model.install(context, reservation, original_install)
        model.probe(64)
        model.dma_write({64: 0x19, 65: 0x23})
        acknowledge(model, intent)
        model.drain(intent.token, context)
        with self.assertRaises(Violation):
            model.install(context, reservation, original_install)
        model.release(context, reservation)
        model.flush()
        self.assertEqual(model.backing[64], 0x19)
        self.assertEqual(model.backing[65], 0x23)

    def test_probe_after_a_and_after_e_before_install_waits(self):
        model = fresh()
        _, context, reservation = offer(model)
        model.acquire(context, reservation, 0)
        with self.assertRaises(Violation):
            model.probe(64)
        base = model.line(64)
        for n in range(8):
            model.grant_beat(0, int.from_bytes(base[n * 8:n * 8 + 8], 'little'), 0)
        model.e(0)
        with self.assertRaises(Violation):
            model.probe(64)
        model.refill(context, reservation, base)
        with self.assertRaises(Violation):
            model.probe(64)
        with self.assertRaises(Violation):
            model.dma_write({65: 7})

    def test_grant_bytes_must_match_independent_home(self):
        model = fresh()
        _, context, reservation = offer(model)
        model.acquire(context, reservation, 0)
        corrupt = bytes([0xFF] * 64)
        for n in range(8):
            model.grant_beat(0, int.from_bytes(corrupt[n * 8:n * 8 + 8], 'little'), 0)
        model.e(0)
        with self.assertRaises(Violation):
            model.refill(context, reservation, corrupt)

    def test_both_clean_and_dirty_victims_retain_real_wb(self):
        for dirty in [False, True]:
            with self.subTest(dirty=dirty):
                model = fresh()
                intent, context, reservation = offer(model, victim=(576, dirty))
                model.attach_wb(context, reservation, 1)
                with self.assertRaises(Violation):
                    model.acquire(context, reservation, 0)
                with self.assertRaises(Violation):
                    model.complete_wb(context, reservation, (1, context.owner))
                model.sent_wb(context, reservation, (1, context.owner))
                acknowledge(model, intent)
                fill(model, context, reservation)  # C-last -> acquire overlap is allowed before WB ACK.
                model.install(context, reservation, model.expected_install(context.owner))
                model.drain(intent.token, context)
                with self.assertRaises(Violation):
                    model.release(context, reservation)
                with self.assertRaises(Violation):
                    model.complete_wb(context, reservation, (1, Owner(0, 99)))
                model.complete_wb(context, reservation, (1, context.owner))
                model.release(context, reservation)

    def test_victim_cancel_needs_real_prior_probe_and_no_capture(self):
        model = fresh()
        intent, context, reservation = offer(model, victim=(576, True))
        with self.assertRaises(Violation):
            model.cancel_victim(context, reservation)
        model.resident[576] = model.line(576)  # Explicit warmed victim fixture premise.
        model.probe(576)
        model.cancel_victim(context, reservation)
        with self.assertRaises(Violation):
            model.attach_wb(context, reservation, 0)
        finish(model, intent, context, reservation)

    def test_live_slot_generation_and_full_token_reuse_rejected(self):
        for mutation in ['generation', 'slot', 'mshr', 'token']:
            with self.subTest(mutation=mutation):
                model = fresh()
                first, context, reservation = offer(model)
                second = Intent(Token(2, 2), 128, 10)
                later = Context(Owner(1, 1), context.owner, 0, 128)
                other = Reservation(1, 2)
                if mutation == 'generation':
                    later = replace(later, owner=Owner(1, 0))
                elif mutation == 'slot':
                    later = replace(later, owner=Owner(0, 1))
                elif mutation == 'mshr':
                    other = replace(other, mshr=0)
                else:
                    second = replace(second, token=first.token)
                with self.assertRaises(Violation):
                    model.accept(second, later, other, 1, True)

    def test_every_component_authority_premise_required(self):
        for premise in ['head', 'pmp', 'physical', 'integer', 'posted', 'checked']:
            with self.subTest(premise=premise):
                model = fresh()
                intent = replace(Intent(Token(1, 1), 64, 10), **{premise: False})
                context = Context(Owner(0, 0), Owner(0, 0), 0, 64)
                with self.assertRaises(Violation):
                    model.accept(intent, context, Reservation(0, 1), 0, True)

    def test_resident_hit_or_upgrade_is_not_an_absent_line_miss(self):
        model = fresh()
        model.resident[64] = model.line(64)
        with self.assertRaises(Violation):
            offer(model)

    def test_source_count_and_actual_a_not_engine_reservation(self):
        model = fresh()
        _, context, reservation = offer(model)
        with self.assertRaises(Violation):
            model.grant_beat(0, 1, 0)
        with self.assertRaises(Violation):
            model.acquire(context, reservation, 2)
        model.acquire(context, reservation, 0)
        with self.assertRaises(Violation):
            model.e(0)
        with self.assertRaises(Violation):
            model.refill(context, reservation, model.line(64))

    def test_error_and_wrong_permission_never_install_or_release(self):
        for error, to_t in [(True, True), (False, False)]:
            model = fresh()
            intent, context, reservation = offer(model)
            acknowledge(model, intent)
            fill(model, context, reservation, error=error, to_t=to_t)
            self.assertTrue(model.failed and model.busy())
            with self.assertRaises(Violation):
                model.install(context, reservation, bytes(64))
            with self.assertRaises(Violation):
                model.drain(intent.token, context)
            with self.assertRaises(Violation):
                model.release(context, reservation)

    def test_tiny_generation_exhaustion_preserves_fallback_identity(self):
        model = fresh(generation_bits=2)
        for generation in range(4):
            intent, context, reservation = offer(model, tag=generation + 1, generation=generation)
            finish(model, intent, context, reservation)
            model.probe(64)
            model.end_episode()
        self.assertTrue(model.exhausted)
        with self.assertRaises(Violation):
            offer(model, tag=5, generation=0)
        intent = Intent(Token(5, 5), 64, 123)
        model.fallback_accept(intent, 1)
        self.assertTrue(model.busy())
        with self.assertRaises(Violation):
            model.fallback_ack(Token(5, 4), 1)
        model.fallback_ack(intent.token, 1)
        self.assertFalse(model.busy())

    def test_cohort_root_survives_first_owner_release(self):
        model = fresh()
        first, older, first_reservation = offer(model)
        second, younger, second_reservation = offer(model, 2, address=128, slot=1, generation=1,
                                                    ticket=1, root=older.owner)
        finish(model, first, older, first_reservation)
        third, newest, third_reservation = offer(model, 3, address=192, generation=2, root=older.owner)
        self.assertEqual(newest.root, older.owner)
        finish(model, second, younger, second_reservation, 1)
        finish(model, third, newest, third_reservation)
        model.end_episode()
        next_intent = Intent(Token(4, 4), 256, 1)
        wrong = Context(Owner(0, 3), older.owner, 0, 256)
        with self.assertRaises(Violation):
            model.accept(next_intent, wrong, Reservation(0, 4), 0, True)

    def test_empty_local_owner_does_not_end_upstream_episode(self):
        model = fresh()
        intent, context, reservation = offer(model)
        finish(model, intent, context, reservation)
        self.assertFalse(model.busy())
        for keyword in ['accepted_upstream_busy', 'held_ingress', 'coherence_busy']:
            with self.assertRaises(Violation):
                model.end_episode(**{keyword: True})
        second, continuing, second_reservation = offer(model, 2, address=128, generation=1, root=context.owner)
        self.assertEqual(continuing.root, context.owner)
        finish(model, second, continuing, second_reservation)
        model.end_episode()
        third, new_episode, third_reservation = offer(model, 3, address=192, generation=2)
        self.assertNotEqual(new_episode.root, context.owner)
        finish(model, third, new_episode, third_reservation)

    def test_context_and_full_event_field_mutations_rejected(self):
        for mutation in ['epoch', 'root', 'line', 'victim', 'way']:
            model = fresh()
            _, context, reservation = offer(model)
            bad_context, bad_reservation = context, reservation
            if mutation == 'epoch':
                bad_context = replace(context, epoch=1)
            elif mutation == 'root':
                bad_context = replace(context, root=Owner(1, 0))
            elif mutation == 'line':
                bad_context = replace(context, line=128)
            elif mutation == 'victim':
                bad_reservation = replace(reservation, victim_address=512)
            else:
                bad_reservation = replace(reservation, way=1)
            with self.assertRaises(Violation):
                model.acquire(bad_context, bad_reservation, 0)
            with self.assertRaises(Violation):
                model.context_boundary(1)

    def test_empty_episode_closes_with_context_without_stale_root_admission(self):
        model = fresh()
        intent, context, reservation = offer(model)
        finish(model, intent, context, reservation)
        with self.assertRaises(Violation):
            model.end_episode(accepted_same_edge=True)
        with self.assertRaises(Violation):
            model.context_boundary(1)
        model.end_episode(context_epoch=1)
        next_intent = Intent(Token(2, 2), 128, 0x45, epoch=1)
        next_context = Context(Owner(0, 1), Owner(0, 1), 1, 128)
        next_reservation = Reservation(0, 2)
        with self.assertRaises(Violation):
            model.accept(replace(next_intent, epoch=0), replace(next_context, epoch=0), next_reservation, 0, True)
        with self.assertRaises(Violation):
            model.accept(next_intent, replace(next_context, root=context.owner), next_reservation, 0, True)
        model.accept(next_intent, next_context, next_reservation, 0, True)
        finish(model, next_intent, next_context, next_reservation)

    def test_held_payload_epoch_and_valid_are_irrevocable(self):
        payload = Intent(Token(1, 1), 64, 100)
        for changed, epoch in [(replace(payload, value=101), 0), (payload, 1), (None, 0)]:
            held = HeldOffer()
            held.sample(payload, False, 0)
            with self.assertRaises(Violation):
                held.sample(changed, False, epoch)
        held = HeldOffer()
        held.sample(payload, False, 0)
        # Candidate victim/MSHR/ticket changes are intentionally not payload.
        held.sample(payload, False, 0)
        held.sample(payload, True, 0)

    def test_handoff_union_has_no_sb_to_cache_gap(self):
        ledger = Responsibility()
        token, payload = Token(1, 1), (64, 3, 255, 0x1234, 0)
        ledger.accept_posted(token, 5, payload)
        for before, after in [('sb', 'ingress'), ('ingress', 'translated'),
                              ('translated', 'checked'), ('checked', 'cache')]:
            for pre, post in [(False, True), (True, False)]:
                with self.assertRaises(Violation):
                    ledger.move(token, before, after, payload, pre, post)
            with self.assertRaises(Violation):
                ledger.move(token, before, after, payload[:-1] + (1,), True, True)
            ledger.move(token, before, after, payload, True, True)
            self.assertTrue(ledger.older_busy(6))
        ledger.release(token)
        self.assertTrue(ledger.may_launch_independent())

    def test_accepted_load_drains_and_ordered_gate_ignores_younger_store(self):
        ledger = Responsibility()
        load, older, younger = Token(0, 0), Token(1, 1), Token(2, 2)
        ledger.accept_load(load)
        ledger.accept_posted(older, 5, 'original bytes')
        ledger.accept_posted(younger, 9, 'younger bytes')
        ledger.drain_load(load)  # No new busy flag may strand an accepted load.
        self.assertFalse(ledger.older_busy(4))
        self.assertTrue(ledger.older_busy(7))
        with self.assertRaises(Violation):
            ledger.accept_load(Token(3, 3))
        ledger.move(older, 'sb', 'cache', 'original bytes', True, True)
        ledger.release(older)
        self.assertFalse(ledger.older_busy(7))  # Younger store cannot self-deadlock this boundary.
        self.assertTrue(ledger.older_busy(10))


if __name__ == '__main__':
    unittest.main(verbosity=2)
