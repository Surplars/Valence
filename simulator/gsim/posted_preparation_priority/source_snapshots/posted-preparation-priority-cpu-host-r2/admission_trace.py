"""Independent sparse-event ledger for canonical ON life1/life16 admission.
Schema 1 remains readable through the frozen life1 parser. Schema 2 proves each
attempt against an absolute birth deadline, not the observer's countdown alone.
"""
import json
from collections import Counter
from admission_trace_v1 import GATES, GEN, need, next_address, flags, genbin, check_state
from admission_trace_v1 import validate as validate_v1


def strict_json(text):
    def pairs(items):
        need(len({k for k, _ in items}) == len(items), 'duplicate JSON key')
        return dict(items)
    return json.loads(text, object_pairs_hook=pairs)


def gates_from_raw(r):
    need(len(r['mshrs']) == len(r['wbs']) == 2, 'owner shape')
    for m in r['mshrs']:
        need(m['phase'] in range(5), 'MSHR phase')
        need((m['address'] is not None) == bool(m['phase']) and
             (m['index'] is not None) == bool(m['phase']), 'invalid MSHR payload')
        need(m['phase'] or not (m['pf'] or m['store']), 'invalid MSHR origin')
        need(not m['store'] or m['pf'], 'store owner without PF')
        if m['phase']:
            need(0 <= m['index'] < 512, 'MSHR index')
    for w in r['wbs']:
        need((w['address'] is not None) == bool(w['live']), 'invalid WB payload')
        need(w['live'] or not w['pf'], 'invalid WB origin')
    live = any(m['phase'] and m['pf'] for m in r['mshrs'])
    release = any(w['live'] and w['pf'] for w in r['wbs'])
    need(r['pf_live'] == live and r['pf_release'] == release, 'phase-qualified owner mismatch')
    need(len(r['way_valid']) == len(r['way_dirty']) == len(r['way_tag']) == 2, 'way shape')
    for w in range(2):
        need((r['way_tag'][w] is not None) == bool(r['way_valid'][w]) and
             (r['way_valid'][w] or not r['way_dirty'][w]), 'invalid way payload')
    need(r['eviction_state'] in range(4), 'eviction state range')
    a, ix = r['candidate_address'], r['index']
    need(a % 64 == 0 and 0 <= ix < 512 and (ix & 255) == ((a >> 6) & 255), 'candidate address/index')
    w = ix // 256
    va = (r['way_tag'][w] << 14) | ((ix & 255) << 6) if r['way_valid'][w] else None
    need(r['victim_valid'] == r['way_valid'][w] and r['victim_dirty'] == r['way_dirty'][w]
         and r['victim_address'] == va, 'selected victim mismatch')
    need(r['victim_tracked_index_match'] == bool(r['tracked_valid'] and r['tracked_index'] == ix)
         and r['victim_tracked_address_match'] == bool(r['tracked_valid'] and va is not None and
                                                       r['tracked_address'] == va), 'tracked victim relation')
    present = 0x80200000 <= a < 0x100200000 and any(
        r['way_valid'][w] and r['way_tag'][w] == ((a >> 14) & 0x7ffff) for w in range(2))
    reserved = any(m['phase'] and (m['index'] & 255) == (ix & 255) for m in r['mshrs'])
    pending = any(w['live'] and w['address'] // 64 == a // 64 for w in r['wbs'])
    free = any(m['phase'] == 0 for m in r['mshrs'])
    need(r['cache_valid'] or not (r['needs_miss'] or r['demand_reserved'] or r['barrier_request']),
         'invalid demand payload')
    demand = r['cache_valid'] and ((r['needs_miss'] and not r['demand_reserved']) or
                                   r['barrier_request'] or r['write'])
    return list(map(bool, [not r['posted_allowed'], live, release, present, reserved, pending,
                          r['victim_valid'] and r['victim_dirty'] and not r['store'], not free,
                          demand, r['barrier'], r['flush_active'], r['flush'], r['bypass_state'] != 0,
                          r['probe_state'] != 0, r['tl_b_valid'], r['eviction_state'] != 0,
                          r['queued_eviction']]))


def validate(path, text, result=None):
    rows = [strict_json(l) for l in open(path)]
    summaries = [r for r in rows if r.get('event') == 'summary']
    need(len(summaries) == 1 and rows[-1] is summaries[0], 'missing/duplicate summary')
    summary = summaries[0]
    if summary.get('schema', 1) == 1:
        need('lifetime' not in summary and 'retained' not in summary['all'], 'schema2 downgraded to legacy')
        return validate_v1(path, text, result)
    need(summary['schema'] == 2 and summary['lifetime'] in (1, 16), 'unsupported schema/lifetime')
    lifetime = summary['lifetime']
    logs = [strict_json(l.split(' ', 1)[1]) for l in text.splitlines() if l.startswith('READ_PREFETCH_ADMISSION ')]
    need(logs == summaries, 'trace/log summary mismatch')
    sources, candidates, attempts, terminals, witnesses = {}, {}, {}, {}, {}
    counts = {k: dict(reads=0, candidate=[0, 0], allocate=[0, 0], useful=[0, 0],
                      retained=[0, 0], cancelled=[0, 0], generation_bins=[0]*10,
                      allocation_exclusive=[0]*18, allocation_overlapping=[0]*17) for k in ('all', 'roi')}
    live_id = None
    last_edge = 0
    last_read = None
    store_line = None
    store_sequential = False
    last_source_seq = 0
    release_edges = set()
    source_edges = {}
    boundaries = {}
    roi_active = False
    dims, seqdims, decision_cross = Counter(), Counter(), Counter()
    for r in rows[:-1]:
        e = r['event']
        need(e in ('read_accept', 'store_accept', 'history_clear', 'candidate', 'decision',
                   'allocation_witness', 'tracked_release', 'roi_boundary'), 'unknown event')
        need(r['edge'] >= last_edge, 'event reorder')
        last_edge = r['edge']
        if 'offer' in r:
            need(r['edge'] == r['offer'] + 1, 'wrong sample edge')
        if 'roi' in r:
            need(bool(r['roi']) == roi_active, 'event ROI does not match boundary')
        keys = ['all'] + (['roi'] if r.get('roi') else [])
        if e in ('read_accept', 'store_accept', 'decision'):
            check_state(r)
            need(r['cache_valid'] or not (r['ordinary'] or r['write'] or r['hint']), 'invalid request payload')
            need(bool(r['origin'] & 48) == bool(r['consume']) and
                 (not r['consume'] or bool(r['origin'] & 32) == bool(r['tracked_store'])), 'useful origin')
        if e in ('read_accept', 'store_accept'):
            seq = r['source_seq']
            need(seq > last_source_seq and seq not in sources, 'duplicate/reordered source sequence')
            last_source_seq = seq
            sources[seq] = r
            need(r['edge'] not in source_edges, 'two accepted sources on one edge')
            source_edges[r['edge']] = r
            need(r['cache_valid'] and r['cache_ready'] and r['ordinary'] and
                 bool(r['write']) == (e == 'store_accept'), 'not accepted source')
            if e == 'read_accept':
                sequential = bool(r['last_valid'] and r['address']//64 == r['last_line']+1 and r['address']//64 != 0)
                need(r['sequential'] == sequential, 'wrong read sequence')
                need(r['last_valid'] == (last_read is not None), 'wrong read history validity')
                if last_read is not None:
                    need(r['last_line'] == last_read['address']//64, 'wrong read history address')
                last_read = r
                need(r['bin'] == genbin(r), 'generation bin mismatch')
                generated = r['bin'] == 9
                for k in keys:
                    counts[k]['reads'] += 1
                    counts[k]['generation_bins'][r['bin']] += 1
                if r['roi']:
                    for k, v in flags(r).items():
                        dims[k] += bool(v)
                        seqdims[k] += bool(v and r['sequential'] and r['hint'])
            else:
                line = r['address']//64
                same = store_line is not None and line == store_line
                sequential = store_line is not None and line != 0 and line == store_line+1
                generated = bool(not r['flush'] and r['hint'] and r['available'] and
                                 (sequential or (same and store_sequential)))
                if not same:
                    store_sequential = sequential
                store_line = line
            need(bool(r['origin'] & 3) == generated and
                 (not generated or bool(r['origin'] & 2) == bool(r['write'])), 'source generator mismatch')
        elif e == 'roi_boundary':
            need(r['enter'] in (0, 1) and r['enter'] not in boundaries, 'duplicate ROI boundary')
            need(r['enter'] or 1 in boundaries, 'ROI exit before entry')
            need(r['id'] == live_id and (r['store'] is not None) == (live_id is not None), 'ROI carry identity')
            if live_id is not None:
                need(r['store'] == candidates[live_id]['store'], 'ROI carry origin')
            roi_active = bool(r['enter'])
            boundaries[r['enter']] = [int(live_id is not None and not r['store']), int(live_id is not None and bool(r['store']))]
        elif e == 'history_clear':
            store_line = None
            store_sequential = False
            if r['flush']:
                last_read = None
        elif e == 'candidate':
            i = r['id']
            need(i == len(candidates)+1 and live_id is None, 'duplicate/missing/overlapping candidate birth')
            need(r['source_seq'] in sources, 'candidate missing accepted source')
            q = sources[r['source_seq']]
            need(q['offer'] == r['offer'] and q['address'] == r['source_address'] and
                 bool(q['write']) == bool(r['store']) and q['origin'] & (1 << r['store']), 'candidate source/origin')
            need(r['hint'] == q['hint'] == 1 and r['address'] == next_address(r['source_address']), 'candidate address/permission')
            need(r['lifetime'] == lifetime and r['deadline'] == r['offer'] + lifetime, 'birth deadline')
            need(r['cancelled_on_emit'] == q['flush'], 'birth cancellation')
            candidates[i], attempts[i] = r, []
            if r['cancelled_on_emit']:
                terminals[i] = r
            else:
                live_id = i
            for k in keys:
                counts[k]['candidate'][r['store']] += 1
                counts[k]['cancelled'][r['store']] += r['cancelled_on_emit']
        elif e == 'decision':
            i = r['id']
            need(i == live_id and i in candidates and i not in terminals, 'unknown/duplicate terminal decision')
            q = candidates[i]
            age = r['offer'] - q['offer']
            need(age == len(attempts[i])+1 and 1 <= age <= lifetime, 'missing/duplicate/overdue attempt')
            need(r['deadline'] == q['offer']+lifetime and r['remaining'] == q['offer']+lifetime-r['offer']
                 and r['attempt'] == age and r['emitted_offer'] == q['offer'], 'fixed absolute deadline/countdown')
            need(all(r[a] == q[b] for a, b in [('source_seq', 'source_seq'), ('source_address', 'source_address'),
                 ('candidate_address', 'address'), ('store', 'store'), ('source_hint', 'hint')]), 'candidate continuity')
            need(r['candidate_valid'] and not (r['origin'] & 3), 'candidate generation priority')
            g = gates_from_raw(r)
            need(len(r['gates']) == 17 and all(x in (0, 1) for x in r['gates']) and r['gates'] == g, 'independent veto mismatch')
            ex = next((j for j, v in enumerate(g) if v), 17)
            allocate = not any(g)
            retain = not any(v for j, v in enumerate(g) if j != 15) and r['eviction_state'] in (1, 2) and age < lifetime
            cancel = not allocate and not retain
            need(r['exclusive'] == ex and r['allocate'] == allocate and r['retain'] == retain and r['cancel'] == cancel,
                 'allocation/retention/cancel mismatch')
            need(bool(r['origin'] & 12) == allocate and (not allocate or bool(r['origin'] & 8) == bool(r['store'])), 'allocation origin')
            need((r['slot'] is not None) == allocate, 'allocation slot validity')
            if allocate:
                need(r['slot'] in (0, 1) and r['mshrs'][r['slot']]['phase'] == 0, 'allocation steals occupied slot')
            attempts[i].append(r)
            if not retain:
                terminals[i] = r
                live_id = None
            for k in keys:
                for n, v in [('allocate', allocate), ('retained', retain), ('cancelled', cancel)]:
                    counts[k][n][r['store']] += v
                counts[k]['allocation_exclusive'][ex] += 1
                for j, v in enumerate(g):
                    counts[k]['allocation_overlapping'][j] += v
            if r['roi']:
                decision_cross[(bool(r['store']), ex, bool(r['victim_valid']), bool(r['victim_dirty']), bool(retain))] += 1
        elif e == 'allocation_witness':
            i = r['id']
            need(i in terminals and terminals[i].get('allocate') and i not in witnesses, 'unknown/duplicate allocation witness')
            q = terminals[i]
            need(r['edge'] == q['edge'] and r['phase'] in (1, 2) and
                 all(r[k] == q[k] for k in ('slot', 'index', 'store')) and r['address'] == q['candidate_address'], 'allocation owner/address')
            witnesses[i] = r
        elif e == 'tracked_release':
            need(r['edge'] not in release_edges, 'duplicate tracked release')
            release_edges.add(r['edge'])
            need(r['consume'] or r['invalidated'] or r['flush'], 'tracked release lacks cause')
            if r['consume']:
                matches = [source_edges[r['edge']]] if r['edge'] in source_edges and source_edges[r['edge']]['consume'] else []
                need(len(matches) == 1 and matches[0]['tracked_address'] == r['address'] and
                     bool(matches[0]['tracked_store']) == bool(r['store']), 'useful missing/wrong consumer')
                for k in keys:
                    counts[k]['useful'][r['store']] += 1
    need(not summary['roi']['cycles'] or 1 in boundaries, 'missing ROI entry')
    need(summary['roi_carry_in'] == boundaries.get(1, [0, 0]) and summary['roi_carry_out'] == boundaries.get(0, [0, 0]), 'ROI boundary summary')
    need(live_id is None and set(terminals) == set(candidates), 'missing terminal outcome')
    need(set(witnesses) == {i for i, r in terminals.items() if r.get('allocate')}, 'missing allocation witness')
    need(sum(bool(r['origin'] & 3) for r in sources.values()) == len(candidates), 'missing generator event')
    for k in ('all', 'roi'):
        for n, v in counts[k].items():
            need(summary[k][n] == v, 'summary mismatch '+k+'.'+n)
        for origin in (0, 1):
            carry_in = summary['roi_carry_in'][origin] if k == 'roi' else 0
            carry_out = summary['roi_carry_out'][origin] if k == 'roi' else 0
            need(counts[k]['candidate'][origin] + carry_in == counts[k]['allocate'][origin] +
                 counts[k]['cancelled'][origin] + carry_out, 'candidate/terminal boundary conservation')
    need(summary['predicted_savings'] is None, 'retention is not measured gain')
    if result is not None:
        r = result['roi']
        need(summary['roi']['cycles'] == r['cycles'], 'ROI cycle mismatch')
        for n, stem in [('candidate', 'candidate'), ('allocate', 'allocated'), ('useful', 'useful')]:
            need(summary['roi'][n] == [r[stem+'_read'], r[stem+'_store']], 'original PF counter mismatch '+n)
    return dict(status='PASS_FIXED_DEADLINE_CANDIDATE_OWNERSHIP', summary=summary,
                read_generation_bins=dict(zip(GEN, summary['roi']['generation_bins'])),
                read_overlapping_dimensions=dict(dims), sequential_hint_true_overlapping_dimensions=dict(seqdims),
                allocation_exclusive_bins=dict(zip(GATES+['allocated'], summary['roi']['allocation_exclusive'])),
                allocation_overlapping_dimensions=dict(zip(GATES, summary['roi']['allocation_overlapping'])),
                attempts=len([r for r in rows if r['event'] == 'decision']),
                terminal_candidates=len(terminals), retention_is_gain=False,
                candidate_victim_cross=[dict(store_origin=k[0], exclusive=(GATES+['allocated'])[k[1]],
                                            victim_valid=k[2], victim_dirty=k[3], retained=k[4], attempts=v)
                                        for k, v in decision_cross.items()])
