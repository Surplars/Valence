#!/usr/bin/env python3
"""Actual 512-line SRAM high-set/both-way narrow gate; no new byte oracle.

Only memory geometry and directed traffic change. The existing independently
written Contract, CPU response check, and ProbeAckData/ReleaseData byte check are
imported without changing their functions. No DUT byte supplies expected data.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from cache_write_data_fixture import WriteDataCache, enqueue_refill_two_owner, MASK64
from contract_oracle import Contract, require

SETS = (0, 127, 128, 255)


class Geometry512Cache(WriteDataCache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The base constructor issued reset only. Replace the initial host-owned
        # byte image and geometry before any CPU/TL request is offered.
        require(self.count['cpu_accept'] == 0 and not self.acquires and not self.request,
                'geometry must be configured before authored traffic')
        epoch = self.model.context_epoch
        memory = {a: (a * 29 + 11) & 255 for a in range(4096, 69632)}
        self.model = Contract(memory, generation_bits=64, cache_sets=256, wb_entries=2)
        self.model.context_epoch = epoch
        self.backing = dict(memory)
        self.reservation_witnesses = []
        self.geometry_hit_writes = set()
        self.geometry_checks = []

    def tick(self, **updates):
        current = self.request
        a = super().tick(**updates)
        if a['accepted.valid'] and a['accepted.bits.newLine']:
            witness = {'cycle': self.cycle,
                'line': a['accepted.bits.member.context.lineAddress'],
                'set': a['accepted.bits.reservation.set'],
                'way': a['accepted.bits.reservation.way'],
                'mshr': a['accepted.bits.reservation.mshr'],
                'owner_slot': a['accepted.bits.member.context.owner.slot'],
                'owner_generation': a['accepted.bits.member.context.owner.generation'],
                'cpu_token': a['accepted.bits.member.token.tag']}
            require(witness['set'] == (witness['line'] // 64) % 256,
                    'actual posted reservation lost high set bits')
            require(witness['way'] in (0, 1), 'actual posted reservation has impossible way')
            self.reservation_witnesses.append(witness)
        if current and a['upstream.request.ready'] and current['bits']['write'] and a['hit']:
            address = current['bits']['address']
            self.geometry_hit_writes.add((address & ~63, (address >> 3) & 7))
        return a

    def close(self, success=True):
        result = super().close(success)
        result.update(lines=512, cache_sets=256, cache_ways=2,
            aperture_base=4096, aperture_bytes=65536,
            reservation_witnesses=self.reservation_witnesses,
            geometry_hit_write_line_banks=[list(x) for x in sorted(self.geometry_hit_writes)],
            geometry_checks=self.geometry_checks)
        return result


def geometry_sets_both_ways(t):
    all_line_banks = set()
    for cache_set in SETS:
        # Bit 14 changes the tag, not the 8-bit set. Both tags fit the authored
        # aperture. Set 127/128 straddles the exact high-set-bit boundary.
        lines = ((1 << 14) + cache_set * 64, (2 << 14) + cache_set * 64)
        before = len(t.reservation_witnesses)
        for lane, line in enumerate(lines):
            t.send(line + 7, write=True, value=0xA0 + lane + (cache_set & 15), size=0, proof=True)
            t.idle()
        witnesses = t.reservation_witnesses[before:]
        require(len(witnesses) == 2 and {w['line'] for w in witnesses} == set(lines),
                'both same-set tags require actual new posted acceptance witnesses')
        require({w['set'] for w in witnesses} == {cache_set} and {w['way'] for w in witnesses} == {0, 1},
                'actual reservations did not cover both ways at the requested high set')
        require(all(line in t.model.resident for line in lines),
                'same-set tags were not simultaneously resident before hit writes')
        for lane, line in enumerate(lines):
            for bank in range(8):
                size = bank % 3
                offset = ((bank + lane) % (8 >> size)) << size
                value = (0x91C3E507294B6D8F ^ (cache_set << 16) ^
                         (bank * 0x102030405060708) ^ (lane * 0x8877665544332211)) & MASK64
                t.send(line + bank * 8 + offset, write=True, value=value, size=size)
                t.until(lambda: not t.responses, 'high-set partial hit write response')
                t.send(line + bank * 8)
                t.until(lambda: not t.responses, 'high-set physical SRAM bank readback')
                all_line_banks.add((line, bank))
            t.read_line(line)
        require(all(line in t.model.resident for line in lines),
                'both ways must remain live through all partial-store/readback checks')
        # Re-read both complete lines while both ways are still resident. This
        # catches a way-address alias even if writes individually appeared valid.
        t.read_line(lines[0]); t.read_line(lines[1])
        before_probe = t.count['physical_probe_data_beats']
        for line in lines:
            t.start_probe(line); t.finish_probe(); t.idle()
            require(t.probe['dirty'], 'high-set resident way omitted dirty ProbeAckData')
        require(t.count['physical_probe_data_beats'] - before_probe == 16,
                'both requested ways must each return eight physical SRAM C data beats')
        t.geometry_checks.append({'set': cache_set, 'lines': list(lines),
            'actual_ways': [w['way'] for w in witnesses], 'partial_store_banks_per_way': 8,
            'dirty_probe_data_beats': 16, 'both_resident_before_probe': True})
    require(all_line_banks <= t.geometry_hit_writes and len(all_line_banks) == 4 * 2 * 8,
            'each of four high/low sets and two real ways needs all eight bank hit writes')
    require({(w['set'], w['way']) for w in t.reservation_witnesses} >=
            {(s, way) for s in SETS for way in (0, 1)},
            'high-set/both-way actual reservation coverage absent')
    require(t.count['physical_probe_data_beats'] >= 64,
            'high-set/both-way full physical dirty C oracle coverage absent')
    t.flush()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--executable', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--case', choices=('geometry-sets-both-ways', 'enqueue-refill-two-owner'))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    cases = {'geometry-sets-both-ways': geometry_sets_both_ways,
             'enqueue-refill-two-owner': enqueue_refill_two_owner}
    selected = [a.case] if a.case else list(cases)
    results = []
    for name in selected:
        t = Geometry512Cache(a.executable, a.output, name, True, 64, 2)
        try:
            cases[name](t)
            results.append(t.close())
        except BaseException:
            t.close(False)
            raise
        (a.output / 'progress.json').write_text(json.dumps(results, indent=2) + '\n')
    report = {'status': 'PASS', 'scope': 'actual 512-line/256-set two-way SRAM; frozen cycle pair; independent physical CPU/C byte oracle; synthetic manager',
        'sets': list(SETS), 'ways': [0, 1], 'lines': 512, 'tl_source_bits': 3,
        'not_claimed': ['executing CPU', 'tagged CPU-return sidecar', 'real Home reachability',
                        'all-mask replay at 512 lines', 'upper generation bits reached', 'board/PPA'],
        'cases': results}
    (a.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('CACHE_WRITE_DATA_512_PASS', 'cases=' + str(len(results)))


if __name__ == '__main__':
    main()
