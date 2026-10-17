#!/usr/bin/env python3
"""Directed compact-member lifetime supplement; existing 32-case suite unchanged.

The scalar ABI and independent Scenario/Contract are reused verbatim. These
checks concern public owner/member identities and legal handshake lifetimes.
They do not inspect compact-bank state or claim CPU/Home integration. Assertion
negatives corrupt explicit environment inputs; the offline sensitivity check
corrupts a reconstructed public drain observation, not an internal RTL register.

This source runs only an explicitly supplied, already-built generation64 model.
Source preparation itself needs no build or DUT execution.
"""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import full_line_cases as base
from full_line_cases import (Scenario, DriverFailure, Violation, check, event_fields,
                             member_fields, observe, sd_members)

HERE = Path(__file__).resolve().parent
SCOPE = ('standalone compact-member public lifetime supplement; synthetic posted authorization, '
         'response completion and coherence completion premises; no CPU/cache/Home qualification')


def binding():
    paths = [Path(__file__).resolve(), HERE/'full_line_cases.py', HERE/'ports.py',
             HERE/'PostedStoreMerge.scala', HERE/'PostedStoreMergeGsim.scala']
    paths += [base.BASE/name for name in ['fixture.py', 'contract_oracle.py', 'ports.py']]
    return [{'path': str(p.relative_to(base.ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
             'bytes': p.stat().st_size} for p in paths]


def ack_fields(item):
    intent, context, _, ticket = item
    return {'acknowledged.valid': 1, **member_fields('acknowledged.bits', intent, context, ticket)}


def prepare_partial(s, item, *, already_acked=False):
    s.accept(item)
    if already_acked:
        s.ack(item)
    s.decide(item, False, seal=True)
    s.acquire(item)
    s.fill(item)
    s.consume('installValid', 'installReady')


def delayed_ack_and_victim(executable, out):
    s = Scenario(executable, out, 'compact-delayed-ack-and-victim-release')
    first = s.authored(1, address=4160, size=1, value=0xA172, ticket=0, victim=(4672, True))
    second = s.authored(2, address=4164, size=2, value=0xEAC48123, ticket=1, victim=(4672, True))
    s.accept(first); s.accept(second, new=False)
    s.decide(first, False, seal=True)
    s.wb(first, 'writebackAttach', 1); s.wb(first, 'writebackSent', 1)
    s.acquire(first); s.fill(first); s.consume('installValid', 'installReady')
    for _ in range(5):
        actual = s.clock(drainReady=1, releaseReady=1, seal=1)
        check(actual['stores'] == 2 and actual['lines'] == 1 and actual['busy'] and
              not actual['drained.valid'] and not actual['released.valid'],
              'DELAYED_REAL_ACK_RETAINS_MEMBER', 'installation or recovery seal freed an unacknowledged token')
    s.ack(first)
    held = s.clock()
    check(held['drained.valid'], 'DELAYED_ACK_DRAIN_START', 'first real ACK did not make its installed member drainable')
    # ACK is a one-shot event, not a backpressured output. The second ACK may
    # complete while the older already-ACKed drain remains irrevocably held.
    actual = s.clock(**ack_fields(second))
    observe(actual, member_fields('drained.bits', first[0], first[1], first[3]))
    for _ in range(3): s.clock(seal=1)
    s.consume('drained.valid', 'drainReady')
    s.consume('drained.valid', 'drainReady')
    for _ in range(3):
        actual = s.clock(releaseReady=1)
        check(actual['stores'] == 0 and actual['lines'] == 1 and actual['busy'] and not actual['released.valid'],
              'VICTIM_ACK_RETAINS_PARENT', 'empty member bank released parent before captured ReleaseAck')
    s.wb(first, 'writebackComplete', 1)
    s.consume('released.valid', 'releaseReady', hold=2)
    result = s.close()
    result['coverage'] = 'two delayed ordered ACKs; younger ACK during older held drain; seal and exact victim ReleaseAck lifetime'
    return result


def held_drain_other_slot_reuse(executable, out):
    s = Scenario(executable, out, 'compact-held-drain-other-slot-reuse')
    first = s.authored(1, size=0, value=0x61)
    second = s.authored(2, address=4224, size=1, value=0x72A3, slot=1, generation=1,
                        ticket=1, root=first[1].owner)
    s.accept(first); s.ack(first); s.accept(second); s.ack(second)
    s.decide(first, False); s.decide(second, False, seal=True)
    s.acquire(first); s.acquire(second); s.fill(first); s.fill(second)
    s.consume('installValid', 'installReady')
    s.consume('installValid', 'installReady')
    s.consume('drained.valid', 'drainReady')  # Only owner0's member drains.
    actual = s.clock()
    check(actual['released.valid'] and actual['drained.valid'], 'LEGAL_RELEASE_HELD_DRAIN_OVERLAP',
          'older empty release and younger installed drain were not both eligible')
    observe(actual, member_fields('drained.bits', second[0], second[1], second[3]))
    # The original oldest-owner rule permits releasing empty owner0 while
    # younger owner1's drain is held; it forbids releasing owner1 here.
    actual = s.clock(releaseReady=1)
    observe(actual, event_fields('released.bits', first[1], first[2]))
    observe(actual, member_fields('drained.bits', second[0], second[1], second[3]))
    third = s.authored(3, address=4288, size=2, value=0x84A6C8EA, slot=0, generation=2,
                       ticket=0, root=first[1].owner)
    # Reuse is on the later edge after release, never release+reuse together.
    actual = s.clock(**s.payload(third))
    check(actual['accepted.valid'] and actual['drained.valid'], 'LEGAL_REUSE_HELD_DRAIN_OVERLAP',
          'free other slot could not allocate while younger drain remained held')
    observe(actual, member_fields('drained.bits', second[0], second[1], second[3]))
    s.ack(third)
    for _ in range(3):
        actual = s.clock(seal=1)
        observe(actual, member_fields('drained.bits', second[0], second[1], second[3]))
    s.consume('drained.valid', 'drainReady')
    s.consume('released.valid', 'releaseReady')
    s.finish_members([third], False, hold=2)
    result = s.close()
    result['coverage'] = 'owner1/gen1 held drain survives owner0/gen0 release and later slot0/gen2 allocation'
    result['forbidden_overlap_not_used'] = 'no same-edge release+reuse, and no younger token drained before the older token'
    return result


def ring_wrap_simultaneous(executable, out):
    s = Scenario(executable, out, 'compact-ring-wrap-triple-handshakes')
    current = sd_members(s, first_tag=1)
    s.decide(current[0], True); s.acquire(current[0]); s.fill(current[0])
    s.consume('installValid', 'installReady')
    triples = []
    for generation, slot, line, first_tag in [(1, 1, 4224, 17), (2, 0, 4288, 33)]:
        following = []
        for n in range(8):
            item = s.authored(first_tag+n, address=line+n*8, value=0x1029384756ABCDEF ^ (generation << 48) ^ n,
                              slot=slot, generation=generation, ticket=n % 2,
                              root=current[0][1].root)
            inputs = s.payload(item, new=(n == 0))
            if n:
                inputs.update(ack_fields(following[-1]))
                inputs['drainReady'] = 1
            actual = s.clock(**inputs)
            check(actual['accepted.valid'], 'RING_WRAP_ACCEPTANCE', 'authored legal incoming member stalled')
            if n:
                older = current[n-1]
                check(actual['drained.valid'], 'TRIPLE_HANDSHAKE_DRAIN', 'installed older member failed to drain')
                observe(actual, member_fields('drained.bits', older[0], older[1], older[3]))
                check(len({item[0].token, following[-1][0].token, older[0].token}) == 3,
                      'TRIPLE_HANDSHAKE_DISTINCT_ENTRIES', 'ingress/ACK/drain were not three distinct full tokens')
                triples.append({'cycle': actual['cycle'], 'accepted_tag': item[0].token.tag,
                                'acknowledged_tag': following[-1][0].token.tag, 'drained_tag': older[0].token.tag})
            following.append(item)
        actual = s.clock(**{**ack_fields(following[-1]), 'drainReady': 1})
        observe(actual, member_fields('drained.bits', current[-1][0], current[-1][1], current[-1][3]))
        check(actual['drained.valid'], 'RING_WRAP_LAST_OLDER_DRAIN', 'last older member did not drain')
        s.consume('released.valid', 'releaseReady')
        s.decide(following[0], True); s.acquire(following[0]); s.fill(following[0])
        s.consume('installValid', 'installReady')
        current = following
    for _ in current: s.consume('drained.valid', 'drainReady')
    s.consume('released.valid', 'releaseReady')
    result = s.close()
    check(result['events']['accepted'] == 24 and result['events']['drain'] == 24 and
          result['events']['ack'] == 24 and len(triples) == 14,
          'RING_WRAP_EXTERNAL_LEDGER', 'did not cover all24 members and14 distinct triple-handshake cycles')
    result.update(member_ring_entries=16, accepted_and_drained=24, triple_handshakes=triples,
                  coverage='tail and head each pass the 16-entry ring boundary; no live entry or unACKed ticket reused')
    return result


def error_after_held_drain(executable, out):
    s = Scenario(executable, out, 'compact-error-after-held-drain')
    first = s.authored(1, size=1, value=0x71A2)
    second = s.authored(2, address=4224, size=2, value=0x83B5D7F9, slot=1, generation=1,
                        ticket=1, root=first[1].owner)
    s.accept(first); s.ack(first); s.accept(second); s.ack(second)
    s.decide(first, False); s.decide(second, False, seal=True)
    s.acquire(first); s.acquire(second); s.fill(first)
    s.consume('installValid', 'installReady')
    check(s.clock()['drained.valid'], 'HELD_DRAIN_ERROR_PREMISE', 'older successful drain was not offered')
    bad = s.fill_payload(second, error=True)
    check(not s.clock(**bad)['refillReady'], 'HELD_DRAIN_ERROR_ORDER', 'fatal result withdrew held successful drain')
    actual = s.clock(**{**bad, 'drainReady': 1})
    check(actual['drained.valid'] and not actual['refillReady'], 'HELD_DRAIN_ERROR_ORDER',
          'fatal result overlapped prior irrevocable drain completion')
    check(s.clock(**bad)['refillReady'], 'HELD_DRAIN_ERROR_ORDER', 'fatal result was not captured after held drain')
    for _ in range(4):
        actual = s.clock(installReady=1, drainReady=1, releaseReady=1, seal=1)
        check(actual['failed'] and actual['busy'] and actual['stores'] == 1 and actual['lines'] == 2 and
              not any(actual[k] for k in ['installValid', 'drained.valid', 'released.valid']),
              'ERROR_RETAINS_PARENT_AND_MEMBER', 'error dropped surviving member or either original parent owner')
    result = s.close(require_empty=False)
    result['coverage'] = 'pre-existing successful drain completes once, then fatal error preserves both owners and remaining token'
    return result


NEGATIVES = {
    'compact-ticket-reuse-before-ack': 'new posted store reused a response ticket before its real ACK',
    'compact-stale-generation-ack-after-reuse': 'posted ACK must be the one real ordered',
    'compact-wrong-parent-line-ack': 'posted ACK must be the one real ordered',
}


def negative(executable, out, name):
    s = Scenario(executable, out, name)
    first = s.authored(1, size=1, value=0x5381, ticket=0)
    if name == 'compact-ticket-reuse-before-ack':
        s.accept(first)
        second = s.authored(2, address=4164, size=2, value=0x91234567, ticket=0)
        bad = s.payload(second, new=False)
    elif name == 'compact-stale-generation-ack-after-reuse':
        s.accept(first); s.ack(first); s.finish_members([first], False, seal=True)
        second = s.authored(2, address=4224, generation=1, size=1, value=0xA6C7, ticket=0,
                            root=first[1].owner)
        s.accept(second)
        bad = ack_fields(second)
        # Keep current token, response ticket, line, epoch and cohort root;
        # only the saved parent generation is stale. A token-only check fails.
        bad['acknowledged.bits.context.owner.generation'] = first[1].owner.generation
    else:
        s.accept(first)
        bad = ack_fields(first)
        bad['acknowledged.bits.context.lineAddress'] = 4224
    caught = None
    try:
        s.raw_clock(**bad); s.raw_clock()
    except DriverFailure as error:
        caught = str(error)
    if s.child.poll() is None:
        try: s.child.stdin.write('quit\n'); s.child.stdin.flush()
        except BrokenPipeError: pass
        s.child.wait(timeout=5)
    s.stderr.close(); s.trace.close()
    log = (caught or '') + s.stderr_path.read_text()
    check(caught is not None and NEGATIVES[name] in log and s.child.returncode != 0,
          'PRECISE_RTL_NEGATIVE', name+'\n'+log)
    check('AddressSanitizer' not in log and 'runtime error:' not in log,
          'SANITIZER_NOT_EXPECTED_NEGATIVE', name)
    return {'name': name, 'status': 'EXPECTED_RTL_ASSERTION', 'anchor': NEGATIVES[name]}


def generation_observation_mutation(out):
    source = Path(out)/'compact-held-drain-other-slot-reuse.jsonl.gz'
    with gzip.open(source, 'rt', encoding='utf-8') as trace:
        records = [json.loads(line) for line in trace]
    base.replay(copy.deepcopy(records))
    changed = None
    previously_held = False
    for frame in records:
        if not frame['checked']: continue
        actual, inputs = frame['actual'], frame['input']
        if actual['drained.valid'] and actual['drained.bits.context.owner.generation'] == 1 and not previously_held:
            actual['drained.bits.context.owner.generation'] = 0
            changed = actual['cycle']
            break
        previously_held = bool(actual['drained.valid'] and not inputs['drainReady'])
    check(changed is not None, 'GENERATION_MUTATION_ANCHOR', 'first unheld generation1 drain was absent')
    caught = None
    try: base.replay(records)
    except Violation as error: caught = str(error)
    anchor = 'actual scalar mismatch drained.bits.context.owner.generation'
    check(caught is not None and anchor in caught, 'GENERATION_MUTATION_REJECTION', str(caught))
    return {'name': 'compact-reconstructed-drain-generation-mutation', 'status': 'EXPECTED_HOST_REJECTION',
            'mutated_cycle': changed, 'anchor': anchor, 'diagnostic': caught,
            'scope': 'public reconstructed event mutation only; no compact-bank RTL register fault injection'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-label', default='compact-members-generation64',
                        help='report label only; emitter/model binding must establish the actual configuration')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    reports = [run(args.executable, args.output) for run in
               [delayed_ack_and_victim, held_drain_other_slot_reuse, ring_wrap_simultaneous, error_after_held_drain]]
    reports += [negative(args.executable, args.output, name) for name in NEGATIVES]
    reports.append(generation_observation_mutation(args.output))
    result = {'scope': SCOPE, 'model_label': args.model_label, 'status': 'PASS', 'cases': reports,
              'executable_sha256': hashlib.sha256(args.executable.read_bytes()).hexdigest(),
              'source_bindings': binding(), 'original_suite_modified': False,
              'trace_format': 'lossless gzip JSONL, inherited 2 MiB aggregate trace cap',
              'trace_compressed_bytes': sum(p.stat().st_size for p in args.output.glob('*.jsonl.gz')),
              'not_claimed': ['internal compact-bank fault injection', 'generation-width exhaustion',
                              'illegal same-edge parent release and slot reuse', 'production integration']}
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print('COMPACT_MEMBER_LIFETIME_PASS cases='+str(len(reports)))


if __name__ == '__main__':
    main()
