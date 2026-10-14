#!/usr/bin/env python3
"""Actual SRAM CPU/C byte checks, reusing the independently authored manager.

No expected byte comes from candidate/referee outputs. Observed install records
are only accepted by the imported contract after comparison with authored intent;
all scenarios additionally demand CPU readback and dirty physical C readback.
"""
import argparse
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[2]
# Use the frozen shared host code, not a mutated production copy.
sys.path.insert(0, str(BASE / 'simulator/gsim/posted_cache_rebuild'))
from fixture import Cache, DriverFailure, observed_context, victim, credit_late_hit, merge_reuse
from contract_oracle import Intent, require, Violation

MASK64 = (1 << 64) - 1
PHYSICAL_FAILURES = (
    'actual CPU byte/error response differs from authored intent',
    'actual SRAM C bytes differ from authored coherent image',
)


@dataclass(frozen=True)
class MaskedIntent(Intent):
    byte_mask: int = 255

    def bytes(self):
        require(self.address % 8 == 0 and 0 <= self.byte_mask <= 255, 'masked scalar request')
        return {self.address + i: (self.value >> (8 * i)) & 255
                for i in range(8) if self.byte_mask & (1 << i)}


class WriteDataCache(Cache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tag = (1 << 63) + 0x123400000000  # Real high-bit full-width CPU tokens.
        self.model.context_epoch = 0xFEDCBA98  # Exact production 32-bit epoch width.
        self.mask_coverage = set()
        self.read_banks = set()
        self.source_case = None
        self.two_owner_updates = []
        self.enqueue_refill_witnesses = []

    def begin_masked(self, address, value, mask):
        token = self.begin(address, write=True, value=value)
        old = self.request['intent']
        self.request['intent'] = MaskedIntent(old.token, old.address, old.value, old.size,
                                               old.epoch, byte_mask=mask)
        self.request['bits']['mask'] = mask
        self.request['bits']['data'] = value & MASK64
        self.mask_coverage.add(((address >> 3) & 7, mask))
        return token

    def tick(self, **updates):
        current = self.request
        a = super().tick(**updates)
        if current and a['upstream.request.ready'] and not current['bits']['write']:
            self.read_banks.add((current['bits']['address'] >> 3) & 7)
        if a['tl.c.valid'] and self.state['tl.c.ready']:
            if a['tl.c.bits.opcode'] == 5:
                self.count['physical_probe_data_beats'] += 1
            if a['tl.c.bits.opcode'] == 7:
                self.count['physical_release_data_beats'] += 1
        if a['upstream.response.valid'] and self.state['upstream.response.ready']:
            self.count['physical_cpu_responses'] += 1
        owners = []
        for event, valid, prefix in [
            ('accepted', a['accepted.valid'], 'accepted.bits.member.context'),
            ('acknowledged', a['acknowledged.valid'], 'acknowledged.bits.context'),
            ('refill', a['refillValid'], 'refillEvent.context'),
            ('installed', a['installedValid'], 'installedEvent.context'),
            ('drained', a['drained.valid'], 'drained.bits.context'),
            ('released', a['released.valid'], 'released.bits.context')]:
            if valid:
                owners.append((event, observed_context(a, prefix).owner))
        if len({owner for _, owner in owners}) >= 2:
            self.count['simultaneous_two_owner_update'] += 1
            self.two_owner_updates.append({'cycle': self.cycle,
                'events': [{'event': event, 'slot': owner.slot, 'generation': owner.generation}
                           for event, owner in owners]})
        if a['accepted.valid'] and a['refillValid']:
            enq = observed_context(a, 'accepted.bits.member.context')
            refill = observed_context(a, 'refillEvent.context')
            if enq.owner != refill.owner:
                self.count['enqueue_refill_distinct_owner_payload_updates'] += 1
                self.enqueue_refill_witnesses.append({'cycle': self.cycle,
                    'accepted_owner': {'slot': enq.owner.slot, 'generation': enq.owner.generation},
                    'accepted_line': enq.line, 'accepted_token': a['accepted.bits.member.token.tag'],
                    'refill_owner': {'slot': refill.owner.slot, 'generation': refill.owner.generation},
                    'refill_line': refill.line})
        return a

    def idle(self):
        # Let delayed retained prefetch candidates become real A transactions;
        # then drain them. This is stricter than the legacy fixture's empty-edge test.
        super().idle()
        for _ in range(20):
            self.tick()
        super().idle()

    def close(self, success=True):
        result = super().close(success)
        result.update(mask_bank_pairs=len(self.mask_coverage), read_banks=sorted(self.read_banks),
                      two_owner_updates=self.two_owner_updates,
                      enqueue_refill_witnesses=self.enqueue_refill_witnesses,
                      owner_generation_bits=64, high_cpu_token_bits_exercised=True)
        return result


def miss_merge(t):
    # Each target starts absent. All other fill banks must remain manager bytes.
    # Poison only invalid live CPU DATA after request acceptance; a miss must use
    # saved fillRequest.data, never the current unrelated CPU input.
    for bank in range(8):
        line = 4160 + bank * 128
        t.flush(); t.idle()
        mask = (0x96 ^ (1 << bank)) & 255
        value = (0xA5B6C7D8E9FA0123 ^ (0x102030405060708 * bank)) & MASK64
        t.begin_masked(line + bank * 8, value, mask)
        t.until(lambda: t.request is None, 'masked miss acceptance')
        t.state['upstream.request.bits.data'] = value ^ MASK64
        t.state['upstream.request.bits.mask'] = mask ^ 255
        t.idle()
        t.read_line(line)
        t.start_probe(line); t.finish_probe(); t.idle()
        require(t.probe['dirty'], 'miss-merge line must return dirty physical SRAM bytes')
    require(t.read_banks == set(range(8)) and t.count['physical_probe_data_beats'] >= 64,
            'all-bank miss/refill/dirty ProbeAckData coverage absent')
    t.flush()


def all_hit_masks(t):
    line = 4160
    t.read_line(line)
    for bank in range(8):
        for mask in range(256):
            value = ((0xF1E2D3C4B5A69788 + mask * 0x01030507090B0D0F) ^
                     (bank * 0x102040810204081)) & MASK64
            t.begin_masked(line + bank * 8, value, mask)
            t.until(lambda: t.request is None, 'masked hit acceptance')
            t.until(lambda: not t.responses, 'masked hit write response')
            t.send(line + bank * 8)
            t.until(lambda: not t.responses, 'physical masked hit readback')
    require(len(t.mask_coverage) == 8 * 256, '8-bank/256-mask physical write coverage absent')
    t.read_line(line)
    t.start_probe(line); t.finish_probe(); t.idle()
    require(t.probe['dirty'] and t.count['physical_probe_data_beats'] >= 8,
            'all-mask line did not pass physical dirty probe oracle')
    t.flush()


def posted_banks(t):
    # Eight partial stores fit one real 16-member owner; untouched bytes must
    # come from the independently authored refill, across all eight SRAM banks.
    t.hold_a = True
    for bank in range(8):
        size = bank % 3
        offset = (bank % (8 >> size)) << size
        t.send(4160 + bank * 8 + offset, write=True,
               value=(0x80F1A263B445C627 ^ (bank * 0x1517191B1D1F2123)) & MASK64,
               size=size, proof=True)
        t.until(lambda: not t.responses, 'posted partial-store early ACK')
    require(t.count['posted_new'] == 1 and t.count['posted_join'] == 7,
            'all-bank partial stores did not share one real posted owner')
    t.hold_a = False
    t.hold_e = True
    t.until(lambda: bool(t.last['tl.e.valid']), 'whole-Grant E backpressure')
    for _ in range(5): t.tick()
    t.hold_e = False
    t.idle(); t.read_line(4160)
    t.hold_c = True
    t.start_probe(4160)
    t.until(lambda: bool(t.last['tl.c.valid']), 'posted dirty probe C backpressure')
    for _ in range(5): t.tick()
    t.hold_c = False
    t.finish_probe(); t.idle()
    require(t.probe['dirty'] and t.count['held_a'] and t.count['held_c'] and t.count['held_e'],
            'posted SRAM/held A,C,E coverage absent')
    t.flush()


def two_owner_update(t):
    t.hold_cpu = True
    t.delay_by_line = {4160: 120, 4288: 12}
    t.send(4160 + 3, write=True, value=0xC7, size=0, proof=True)
    t.send(4288 + 50, write=True, value=0xABCD, size=1, proof=True)
    t.until(lambda: t.count['e'] == 1, 'younger owner E before oldest CPU ACK')
    # The first post-E engine-result cycle refills owner 1 while response.fire
    # acknowledges owner 0. Count actual reported owners, never assumed timing.
    t.hold_cpu = False
    t.idle()
    require(t.count['simultaneous_two_owner_update'] > 0,
            'same-edge two-distinct-owner update not reached')
    require(t.count['posted_new'] == 2 and t.count['posted_ack'] == 2 and t.count['held_cpu'] > 0,
            'two-owner ACK/backpressure coverage absent')
    t.read_line(4160); t.read_line(4288)
    for line in (4160, 4288):
        t.start_probe(line); t.finish_probe(); t.idle()
        require(t.probe['dirty'], 'two-owner data was not checked through physical dirty C')
    t.flush()


def enqueue_refill_two_owner(t):
    t.send(4160 + 5, write=True, value=0xA9, size=0, proof=True)
    t.until(lambda: t.count['e'] == 1, 'first owner E before next owner enqueue')
    # E transitions the acquire engine to complete. Its following response is
    # the first owner's refill while the fresh second owner accepts byte intent.
    # The assertion counts only actual enq+refill on distinct full owners.
    t.begin(4288 + 54, write=True, value=0x8BC7, size=1, proof=True)
    t.tick()
    require(t.count['enqueue_refill_distinct_owner_payload_updates'] > 0,
            'distinct-owner accepted/enqueue + refill payload writes not reached')
    t.idle()
    t.read_line(4160); t.read_line(4288)
    for line in (4160, 4288):
        t.start_probe(line); t.finish_probe(); t.idle()
        require(t.probe['dirty'], 'enqueue/refill owner bytes missed physical dirty probe')
    t.flush()


def dirty_eviction(t):
    victim(t, True)
    require(t.count['physical_release_data_beats'] >= 8,
            'real dirty eviction did not reach independent C byte oracle')


CASES = {'miss-merge': miss_merge, 'all-hit-masks': all_hit_masks,
         'posted-banks': posted_banks, 'two-owner-update': two_owner_update,
         'enqueue-refill-two-owner': enqueue_refill_two_owner,
         'dirty-eviction': dirty_eviction, 'credit-held-to-hit': credit_late_hit}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--executable', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--enabled', type=int, choices=(0, 1), required=True)
    p.add_argument('--case', choices=CASES)
    p.add_argument('--expect-physical-byte-failure', action='store_true')
    a = p.parse_args()
    require(not a.expect_physical_byte_failure or a.case is not None,
            'source negative must name its specific physical readback case')
    a.output.mkdir(parents=True, exist_ok=False)
    selected = [a.case] if a.case else (['miss-merge', 'all-hit-masks'] +
        (['posted-banks', 'enqueue-refill-two-owner', 'two-owner-update', 'dirty-eviction', 'credit-held-to-hit'] if a.enabled else []))
    results = []
    for name in selected:
        require(a.enabled or name in ('miss-merge', 'all-hit-masks'), 'posted scenario requires posted owner')
        t = WriteDataCache(a.executable, a.output, name, bool(a.enabled), 64, 2)
        try:
            CASES[name](t)
            result = t.close()
        except Violation as error:
            t.close(False)
            if not a.expect_physical_byte_failure or str(error) not in PHYSICAL_FAILURES:
                raise
            result = {'name': name, 'status': 'EXPECTED_PHYSICAL_BYTE_ORACLE_FAILURE',
                      'diagnostic': str(error), 'cycle': t.cycle, 'actual_model_exit': t.child.returncode}
        except BaseException:
            t.close(False)
            raise
        else:
            require(not a.expect_physical_byte_failure, 'source mutation survived physical byte oracle')
        results.append(result)
        (a.output / 'progress.json').write_text(json.dumps(results, indent=2) + '\n')
    report = {'status': 'EXPECTED_PHYSICAL_BYTE_ORACLE_FAILURE' if a.expect_physical_byte_failure else 'PASS',
        'scope': 'real cache/SRAM/acquire engine; frozen cycle pair plus independent external CPU/C bytes; synthetic manager',
        'not_claimed': ['executing CPU authorization', 'real Home reachability', 'upper generation bits reached in short run', 'board/PPA'],
        'enabled': bool(a.enabled), 'generation_bits': 64, 'cases': results}
    (a.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('CACHE_WRITE_DATA_' + report['status'], 'enabled=' + str(a.enabled), 'cases=' + str(len(results)))


if __name__ == '__main__':
    main()
