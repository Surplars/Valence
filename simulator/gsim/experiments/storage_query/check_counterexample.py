#!/usr/bin/env python3
"""Strict single-frame Yosys witness decoder for the recovery-query <= mutant.

This checks a concrete negative witness, not universal equivalence. Normal proofs
are checked by the SAT runner; an optional normal witness mode checks one sample.
No legal-state restriction is imposed on count/keep encodings.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re


def decode(document):
    values, widths = {}, {}
    for signal in document['signal']:
        name, wave = signal['name'], signal['wave']
        if name in values:
            raise ValueError('duplicate signal: ' + name)
        if wave in ('04', '14'):
            bits = wave[0]
            if signal.get('data'):
                raise ValueError('unexpected scalar data: ' + name)
        elif wave == '=4':
            data = signal['data']
            if len(data) != 2 or data[1] != '':
                raise ValueError('not a single-frame witness: ' + name)
            bits = data[0]
        else:
            raise ValueError('unknown or unsupported waveform: ' + name)
        if not isinstance(bits, str) or not re.fullmatch('[01]+', bits):
            raise ValueError('unknown/nonbinary value: ' + name)
        values[name], widths[name] = int(bits, 2), len(bits)
    return values, widths


def check(document, mode='negative'):
    v, widths = decode(document)
    rows = len([name for name in v if re.fullmatch(r'io_tags_\d+', name)])
    if rows not in (16, 32):
        raise ValueError('expected 16 or 32 rows')
    rb = (rows - 1).bit_length()

    def get(name, width):
        if widths.get(name) != width:
            raise ValueError('missing/wrong width: ' + name)
        return v[name]

    def equals(name, width, expected):
        if get(name, width) != int(expected):
            raise ValueError('recomputed mismatch: ' + name)

    head, count = get('io_head', rb), get('io_count', rb + 1)
    keep, recovering = get('io_keepCount', rb + 1), get('io_recovering', 1)
    tags = [get('io_tags_' + str(i), 64) for i in range(rows)]
    req = {}
    for role in ('external', 'local'):
        prefix = 'io_' + role
        index = get(prefix + '_bits_token_index', rb)
        tag = get(prefix + '_bits_token_tag', 64)
        inclusive = get(prefix + '_bits_inclusive', 1)
        valid = get(prefix + '_valid', 1)
        age = (index - head) % rows
        boundary = age + 1 - inclusive
        admitted = bool(valid and age < count and tags[index] == tag and
                        (not recovering or boundary < keep))
        req[role] = dict(index=index, age=age, tag=tag, valid=valid,
                         inclusive=inclusive, keep=boundary, admitted=admitted)
        equals(prefix + 'Keep', rb + 1, boundary)
    e, local = req['external'], req['local']
    winner = bool(e['admitted'] and (not local['valid'] or e['age'] <= local['age']))
    accepted = winner or local['admitted']
    boundary = (e if winner else local)['keep']
    equals('io_externalWins', 1, winner)
    equals('io_accepted', 1, accepted)
    equals('io_activeKeep', rb + 1, boundary if accepted else keep)
    old, new, lanes = 0, 0, []
    for lane in range(2):
        index = get('io_queryIndex_' + str(lane), rb)
        age = (index - head) % rows
        equals('io_queryAge_' + str(lane), rb, age)
        reference = age < boundary if accepted else (not recovering or age < keep)
        candidate = (age <= boundary if accepted else (not recovering or age < keep)) if mode == 'negative' else reference
        old |= int(reference) << lane
        new |= int(candidate) << lane
        lanes.append(dict(index=index, age=age, reference=bool(reference), candidate=bool(candidate)))
    equals('io_oldQuery', 2, old)
    equals('io_newQuery', 2, new)
    equals('io_ordinaryEqual', 1, 1)
    equals('io_queriesEqual', 1, old == new)
    equals('io_equal', 1, old == new)
    if mode == 'negative':
        if not accepted or old == new or not any(x['age'] == boundary for x in lanes):
            raise ValueError('not the precise accepted-boundary negative control')
        if any(x['reference'] != x['candidate'] and
               (x['age'] != boundary or x['reference'] or not x['candidate']) for x in lanes):
            raise ValueError('unrelated query discrepancy')
    elif mode != 'normal':
        raise ValueError('unknown mode')
    return dict(status='PASS_PRECISE_BOUNDARY_COUNTEREXAMPLE' if mode == 'negative' else 'PASS_NORMAL_SAMPLE',
                rows=rows, head=head, count=count, recovering=recovering, keepCount=keep,
                requests=req, accepted=bool(accepted), externalWins=winner, boundary=boundary,
                lanes=lanes, ordinaryEqual=True, oldQuery=old, newQuery=new,
                scope='concrete two-state witness only; not a universal or sequential proof')


def self_test():
    # Independent synthetic legal witness: head wrap, matching full tags, external tie wins.
    def signal(name, width, value):
        return dict(name=name, wave='=4', data=[format(value, '0' + str(width) + 'b'), ''])
    signals = [signal('io_tags_' + str(i), 64, 0) for i in range(16)]
    fields = {'io_head': (4, 15), 'io_count': (5, 14), 'io_keepCount': (5, 3),
              'io_recovering': (1, 1), 'io_externalWins': (1, 1), 'io_accepted': (1, 1),
              'io_activeKeep': (5, 2), 'io_ordinaryEqual': (1, 1), 'io_queriesEqual': (1, 0),
              'io_equal': (1, 0), 'io_oldQuery': (2, 2), 'io_newQuery': (2, 3)}
    for role in ('external', 'local'):
        for suffix, pair in {'_valid': (1, 1), '_bits_token_index': (4, 0),
                             '_bits_token_tag': (64, 0), '_bits_inclusive': (1, 0), 'Keep': (5, 2)}.items():
            fields['io_' + role + suffix] = pair
    for lane, index, age in [(0, 1, 2), (1, 0, 1)]:
        fields['io_queryIndex_' + str(lane)] = (4, index)
        fields['io_queryAge_' + str(lane)] = (4, age)
    signals += [signal(name, *pair) for name, pair in fields.items()]
    doc = {'signal': signals}
    check(doc)
    failures = 0
    for name, bits in [('io_ordinaryEqual', '0'), ('io_newQuery', '00'),
                       ('io_queryAge_0', '0011'), ('io_tags_0', '1' * 64),
                       ('io_count', 'xxxxx'), ('io_count', '00000')]:
        bad = copy.deepcopy(doc)
        next(s for s in bad['signal'] if s['name'] == name)['data'][0] = bits
        try:
            check(bad)
        except ValueError:
            failures += 1
        else:
            raise AssertionError('accepted bad witness: ' + name)
    normal = copy.deepcopy(doc)
    for s in normal['signal']:
        if s['name'] == 'io_newQuery':
            s['data'][0] = '10'
        if s['name'] in ('io_equal', 'io_queriesEqual'):
            s['data'][0] = '1'
    check(normal, 'normal')
    print(json.dumps(dict(status='PASS', positive=2, rejected=failures)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counterexample', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--mode', choices=('normal', 'negative'), default='negative')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.counterexample is None or args.out is None:
        parser.error('--counterexample and --out are required')
    raw = args.counterexample.read_bytes()
    result = check(json.loads(raw), args.mode)
    result['counterexample_sha256'] = hashlib.sha256(raw).hexdigest()
    args.out.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
