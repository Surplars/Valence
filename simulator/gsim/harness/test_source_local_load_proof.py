#!/usr/bin/env python3
"""Pure transition audit; no RTL/model build. Not a hardware acceptance claim.

The oracle invalidates a set of full owner identities after nominal protocol moves.
The candidate propagates source-local cancellation through those same moves. Scheduler
is intentionally common: it is not changed by this refactor. Compare all valid keys,
nominal events, next turn and exclusion mask; test arbitrary unique pre-edge owner
states as well as reachable traces. Permission is an arbitrary external final bit:
no PMP logic is replaced by this audit.
"""
from dataclasses import dataclass, replace
import json
import random

@dataclass(frozen=True)
class Key:
    token: tuple
    va: int
    size: int
    epoch: int

@dataclass(frozen=True)
class Row:
    key: Key
    valid: bool = False
    allowed: bool = True

ZERO = Key((0, 0), 0, 0, 0)

def conflict(a, b):
    return a.token == b.token and (a.va, a.size) != (b.va, b.size)

def step(rows, current, ahead, issued, live, epoch, enabled, response_ok,
         permission, turn=0, victim_turn=0, mutant=None):
    identities = [r.key.token for r in rows if r.valid]
    assert len(identities) == len(set(identities)), 'unique valid old full tokens required'
    sources = [x for x in [current] + ahead if x is not None]
    fresh = [r.valid and live[i] and r.key.epoch == epoch for i, r in enumerate(rows)]
    matches = [current is not None and fresh[i] and r.key == current for i, r in enumerate(rows)]
    bad = {r.key.token for i, r in enumerate(rows) if r.valid and
           (not fresh[i] or any(conflict(s, r.key) for s in sources))}
    expired = {r.key for r in rows[3:] if r.valid and not r.allowed}
    d_empty = next((i for i in [0, 1] if not rows[i].valid), None)
    r_empty = next((i for i in [3, 4] if not rows[i].valid), None)
    advance = enabled and fresh[2] and r_empty is not None
    t_space = not rows[2].valid or advance
    qrow = next((i for i in [0, 1] if matches[i]), None)
    if qrow is None and (current is None or any(matches)):
        qrow = next((i for i in [turn, 1-turn] if fresh[i]), None)
    old_conflict = current is not None and any(r.valid and conflict(current, r.key) for r in rows)
    query = rows[qrow].key if qrow is not None else (
        current if current is not None and not any(matches) and not old_conflict else None)
    accept = enabled and t_space and query is not None and response_ok
    capture = next((s for s in ahead if s is not None and
                    not any(r.valid and r.key.token == s.token for r in rows) and
                    not (accept and s.token == query.token)), None)
    if not enabled or d_empty is None:
        capture = None
    preempt = enabled and current is not None and not any(matches[3:]) and r_empty is None
    victim = rows[3+victim_turn].key.token if preempt else None
    # Semantic oracle: move nominal owners, then remove identities disqualified by
    # any old owner, exact expired key, issued identity, victim or inconsistent input.
    reference = list(rows)
    if advance:
        reference[r_empty] = Row(rows[2].key, True, permission)
        reference[2] = replace(reference[2], valid=False)
    if accept:
        reference[2] = Row(query, True, False)
        if qrow is not None:
            reference[qrow] = replace(reference[qrow], valid=False)
    if capture is not None:
        reference[d_empty] = Row(capture, True)
    for i, r in enumerate(reference):
        remove = (not enabled or r.key.epoch != epoch or r.key.token in bad or
                  r.key in expired or r.key.token == victim or r.key.token == issued or
                  any(conflict(s, r.key) for s in sources))
        reference[i] = replace(r, valid=r.valid and not remove)

    def issue_matches(key):
        if mutant == 'drop_issue':
            return False
        if mutant == 'index_only_issue':
            return issued is not None and key.token[0] == issued[0]
        return key.token == issued

    def incoming_conflict(key):
        return False if mutant == 'drop_incoming_conflict' else any(conflict(s, key) for s in sources)

    # Proposed local implementation. Old valid owners are pairwise full-token unique.
    # Hence cross-old bad/expiry/victim cancellation reduces to each source's own
    # conditions. A fresh CURRENT can still match a dead raw resident, unlike capture.
    old_keep = []
    for i, r in enumerate(rows):
        own_expired = i >= 3 and not r.allowed
        own_victim = preempt and i == 3+victim_turn
        old_keep.append(fresh[i] and enabled and not incoming_conflict(r.key) and
                        not issue_matches(r.key) and not own_expired and not own_victim)
    candidate = [replace(r, valid=old_keep[i]) for i, r in enumerate(rows)]
    if advance:
        candidate[r_empty] = Row(rows[2].key, old_keep[2], permission)
        candidate[2] = replace(candidate[2], valid=False)
    if accept:
        if qrow is not None:
            keep_query = old_keep[qrow]
            candidate[qrow] = replace(candidate[qrow], valid=False)
        else:
            stale_raw_bad = query.token in bad
            if mutant == 'drop_current_bad_raw':
                stale_raw_bad = False
            keep_query = (enabled and query.epoch == epoch and not stale_raw_bad and
                          query not in expired and query.token != victim and
                          not incoming_conflict(query) and not issue_matches(query))
        if mutant == 'cancel_old_destination':
            keep_query = keep_query and not issue_matches(rows[2].key)
        candidate[2] = Row(query, keep_query, False)
    if capture is not None:
        keep_capture = (enabled and capture.epoch == epoch and
                        not incoming_conflict(capture) and not issue_matches(capture))
        candidate[d_empty] = Row(capture, keep_capture)
    def visible(rs):
        return tuple((r.valid, r.key if r.valid else None, r.allowed if r.valid else None) for r in rs)
    mask = 0
    for r in rows:
        if r.valid:
            mask |= 1 << r.key.token[0]
    for s in [query if accept else None, capture]:
        if s is not None:
            mask |= 1 << s.token[0]
    events = (advance, accept, qrow if accept else None, capture, preempt,
              1-qrow if accept and qrow is not None else turn,
              1-victim_turn if preempt else victim_turn, mask)
    return visible(reference), visible(candidate), reference, events


def main():
    rng = random.Random(0xCB614F5)
    mutants = ['drop_issue', 'index_only_issue', 'drop_incoming_conflict',
               'drop_current_bad_raw', 'cancel_old_destination']
    killed = {}
    coverage = dict(advance=0, query=0, capture=0, preempt=0, turnover=0,
                    bad_current=0, conflict=0, high_tag_alias=0)
    # Exhaust all occupancy/liveness masks, query identities, issue identities and
    # epoch relations in a fixed distinct-full-tag/same-index small key domain.
    directed = 0
    basis_directed = [Key((1, (1 << 48)+i), i*8, 3, 0) for i in range(7)]
    def check_directed(rs, cur, ah, issue, ls, ep=0, vt=0):
        nonlocal directed
        rr, cc, _, ev = step(rs, cur, ah, issue, ls, ep, True, True, True, 0, vt)
        assert rr == cc, ('directed mismatch', directed, rr, cc)
        directed += 1
        return ev
    for slot in range(5):
        for stale in [False, True]:
            # Invalid payload garbage deliberately duplicates the valid owner's key.
            rs = [Row(basis_directed[slot]) for _ in range(5)]
            rs[slot] = Row(basis_directed[slot], True, slot != 3)
            ls = [True]*5
            if not stale:
                ls[slot] = False
            ep = int(stale)
            check_directed(rs, replace(basis_directed[slot], epoch=ep), [None,None], None, ls, ep)
    # Full results + stale exact current simultaneously exercise victim cancellation.
    rs = [Row(ZERO), Row(ZERO), Row(ZERO), Row(basis_directed[3],True,False),
          Row(basis_directed[4],True)]
    check_directed(rs, replace(basis_directed[3],epoch=1), [None,None], None, [True]*5,1,0)
    # Old T advances and is issued, D0 queries into T, fresh lookahead captures D1.
    rs = [Row(basis_directed[0],True), Row(basis_directed[0]),
          Row(basis_directed[2],True), Row(basis_directed[2]), Row(basis_directed[4],True)]
    ev = check_directed(rs,basis_directed[0],[basis_directed[6],None],
                        basis_directed[2].token,[True]*5)
    assert ev[0] and ev[1] and ev[3] is not None
    check_directed(rs,basis_directed[0],[basis_directed[6],None],(1,1 << 63),[True]*5)
    exhaustive = 0
    basis = [Key((1, (1 << 48)+i), i*8, i % 4, 0) for i in range(5)]
    for occupied in range(32):
        for live_mask in range(32):
            rs = [Row(k, bool(occupied & (1 << i)), i != 3) for i,k in enumerate(basis)]
            ls = [bool(live_mask & (1 << i)) for i in range(5)]
            for chosen in [None] + basis:
                for issued_key in [None, basis[2].token, basis[3].token]:
                    for ep in [0, 1]:
                        cur = replace(chosen, epoch=ep) if chosen is not None else None
                        # Contradictory incoming full owner and a fresh high-tag alias.
                        aheads = [replace(basis[0], va=128, epoch=ep),
                                  Key((1, 1 << 63), 256, 3, ep)]
                        rr, cc, _, _ = step(rs, cur, aheads, issued_key, ls, ep,
                                          True, True, True, 0, 1)
                        assert rr == cc, ('exhaustive mismatch', occupied, live_mask,
                                          chosen, issued_key, ep, rr, cc)
                        exhaustive += 1
    trace = [Row(ZERO) for _ in range(5)]
    turn = victim_turn = 0
    for n in range(60000):
        epoch = rng.randrange(3)
        # Alternate arbitrary pairwise-unique valid states with propagated traces.
        if n % 3 == 0:
            keys = [Key((rng.randrange(4), (1 << 48) + n*8+i), rng.randrange(8)*8,
                        rng.randrange(4), rng.randrange(3)) for i in range(5)]
            rows = [Row(k, bool(rng.randrange(2)), bool(rng.randrange(2))) for k in keys]
        else:
            rows = trace
        # Invalid payloads are arbitrary; never use them as cancellation authority.
        rows = [r if r.valid or rng.randrange(2) else
                Row(rng.choice(rows).key, False, bool(rng.randrange(2))) for r in rows]
        live = [rng.randrange(5) != 0 for _ in range(5)]
        def source():
            if rng.randrange(4) == 0:
                return None
            if rng.randrange(4):
                k = rng.choice(rows).key
                mode = rng.randrange(5)
                if mode == 1:
                    k = replace(k, va=k.va ^ 8)
                elif mode == 2:
                    k = replace(k, size=(k.size+1) % 4)
                elif mode == 3:
                    k = replace(k, token=(k.token[0], k.token[1] ^ (1 << 47)))
                return replace(k, epoch=epoch)
            return Key((rng.randrange(4), (1 << 63)+n), rng.randrange(8)*8, rng.randrange(4), epoch)
        current, a, b = source(), source(), source()
        possible = [r.key.token for r in rows] + [s.token for s in [current, a, b] if s is not None]
        issued = rng.choice(possible) if rng.randrange(2) else None
        args = (rows, current, [a,b], issued, live, epoch, rng.randrange(20)!=0,
                rng.randrange(8)!=0, bool(rng.randrange(2)), turn, victim_turn)
        ref, got, trace, ev = step(*args)
        assert ref == got, ('transition mismatch', n, args, ref, got)
        live_tokens = [r.key.token for r in trace if r.valid]
        assert len(live_tokens) == len(set(live_tokens)), ('ownership invariant', n)
        turn, victim_turn = ev[5:7]
        coverage['advance'] += ev[0]
        coverage['query'] += ev[1]
        coverage['capture'] += ev[3] is not None
        coverage['preempt'] += ev[4]
        coverage['turnover'] += ev[0] and ev[1]
        coverage['bad_current'] += current is not None and any(r.valid and
            r.key.token == current.token and (not live[i] or r.key.epoch != epoch)
            for i,r in enumerate(rows))
        coverage['conflict'] += any(conflict(s,t) for s in [current,a,b] if s is not None
                                   for t in [current,a,b] if t is not None)
        coverage['high_tag_alias'] += issued is not None and any(r.valid and
            r.key.token[0] == issued[0] and r.key.token != issued for r in rows)
        for mutant in mutants:
            if mutant not in killed:
                mref, mgot, _, _ = step(*args, mutant=mutant)
                if mref != mgot:
                    killed[mutant] = n
    assert set(killed) == set(mutants), ('surviving mutant', killed)
    assert all(coverage.values()), coverage
    print(json.dumps(dict(status='PASS_PURE_MODEL_NOT_RTL', random_transitions=60000, exhaustive_transitions=exhaustive, directed_transitions=directed,
                          coverage=coverage, mutants_killed=killed), indent=2))

if __name__ == '__main__':
    main()
