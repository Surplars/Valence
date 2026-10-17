#!/usr/bin/env python3
"""Bound saved-observation oracle sensitivity. Never invokes or imports a DUT.

Each invocation uses a fresh immutable positive-suite Ledger. Only a copy of
one bound saved frame is mutated. The accepted-owner ledger and authored epoch
publication/external completion events are never mutated.
"""
import argparse
import copy
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
BOUND = {
    'backend-smoke/trace.jsonl.gz': '16f0423fb263f3fd88a87db688600d19b835135768da88c1259151b2b31a4cc9',
    'backend-smoke/RESULT.json': 'ac3360a888d0b8c746e46817c11e620b5bb63abebe4809674130c6158ad47183',
    'host-backend/FREEZE.json': '79ffeb1a861f27e83fb51e129b95c7611f875729239920a6c1ea6b7abc9d740b',
    'host-backend/oracle.py': 'a8bd59fdaf2c2b48d9d14994b0ccf7c78c77cb0ddaff77c653838ec6d6847de9',
    'host-backend/decoded.py': '2d1a17f8cd74a6ad77b0000124ddce21230c91605c869ce78cfef79f4df75279',
    'host-backend/ports.py': '48bc54e8565d2fa233816e3e718ac3b8b9e8cbf05c63205ef407f77f08253c44',
    'host-backend/SCHEMA.json': '5fba1da1ffb07a21354738884380670f14cac159b0535136a7abed659231c2f9',
}
CONTROLS = {
    'head-token': dict(cycle=184, anchor='backend_head_token_mismatch', error='INDEPENDENT_HEAD_FULL_TOKEN'),
    'younger-qualified': dict(cycle=119, anchor='backend_younger_qualified_issue', error='YOUNGER_READ_MINTED_BEFORE_ACTUAL_HEAD'),
    'external-release': dict(cycle=113, anchor='backend_external_owner_early_release', error='EXTERNAL_BUSY_INDEPENDENT_LEDGER'),
}


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_inputs():
    for relative, expected in BOUND.items():
        require(digest(TASK / relative) == expected, 'BOUND_SOURCE_OR_TRACE_CHANGED: ' + relative)
    frozen = json.loads((TASK / 'host-backend/FREEZE.json').read_text())
    for b in frozen['bindings']:
        f = Path(b['path'])
        require(f.stat().st_size == b['bytes'] and digest(f) == b['sha256'], 'FROZEN_POSITIVE_BINDING_CHANGED: ' + str(f))
    baseline = json.loads((TASK / 'backend-smoke/RESULT.json').read_text())
    require(baseline['status'] == 'PASS' and baseline['driver_returncode'] == 0 and baseline['error'] is None and
            baseline['cycles'] == 226 and baseline['trace_sha256'] == BOUND['backend-smoke/trace.jsonl.gz'],
            'BOUND_POSITIVE_RESULT')
    rows = [json.loads(line) for line in gzip.open(TASK / 'backend-smoke/trace.jsonl.gz', 'rt')]
    require(len(rows) == 226 and [r['actual']['cycle'] for r in rows] == list(range(1, 227)), 'EXACT_BOUND_FRAME_SEQUENCE')
    # These are retained authored environment events. Their timing is never
    # inferred from busy-low observations or from a mutated frame.
    names = ('authored_stable_external_epoch_published', 'authored_external_posted_completion')
    events = {name: [e for e in baseline['events'] if e['name'] == name] for name in names}
    require(all(len(value) == 1 for value in events.values()), 'EXACT_AUTHORED_EVENT_CARDINALITY')
    publish, complete = events[names[0]][0], events[names[1]][0]
    require(publish['cycle'] == 104 and publish['epoch'] == 1 and complete['cycle'] == 194 and
            complete['token'] == [2, 18], 'BOUND_AUTHORED_EVENT_IDENTITIES')
    return baseline, rows, publish, complete


def inject(mode, row, model, rows):
    control = CONTROLS[mode]
    original = row['actual']; inp = row['input']; c = original['cycle']
    require(c == control['cycle'] and row['checked'], 'CONTROL_CYCLE_PREMISE')
    store = model.roles.get('posted-store')
    require(store is not None and store.token == (2, 18) and store.retired == 111 and store.responded == 112 and
            model.external == {store.token} and not model.pending and model.published and
            inp['io.posted.externalBusy'] == 1 and inp['io.posted.contextEpoch'] == 1 and
            inp['io.loadPrecheck.epoch'] == 1 and inp['io.loadPrecheck.stable'] == 1 and
            inp['io.posted.blockNew'] == 0 and original['observation.postedBusy'] == 1 and
            original['io.memoryBusy'] == 1, 'INDEPENDENT_RETAINED_EXTERNAL_OWNER_PREMISE')
    patch = []
    if mode == 'external-release':
        require(not original['io.posted.busy'] and not original['observation.headValid'] and
                not original['io.memory.request.valid'] and not original['observation.start.valid'],
                'EARLY_RELEASE_AFTER_REAL_SERVICE_DRAIN_PREMISE')
        patch = [('input', 'io.posted.externalBusy', 0)]
    else:
        read, divide = model.roles.get('head-read'), model.roles.get('older-divide')
        require(read is not None and divide is not None and read.token == (4, 20) and divide.token == (3, 19) and
                read.accepted == 116 and divide.accepted == 115 and not read.started and
                model.registers[10] == 0x80200000 and model.registers[0] == 0,
                'ACCEPTED_FULL_TOKEN_READY_OPERANDS_PREMISE')
        require(original['observation.headValid'] and not original['observation.headDone'],
                'ACTUAL_VALID_UNFINISHED_HEAD_PREMISE')
        p = 'observation.start.bits.'
        active = {'token.index': read.token[0], 'token.tag': read.token[1], 'pc': read.instruction.pc,
                  'address': read.expected['address'], 'data': read.expected['store_data'],
                  'atomic': 0, 'atomicOp': 0, 'store': 0, 'size': 3, 'unsigned': 0,
                  'accessDenied': 0, 'virtualized': 0, 'precheckedLoad': 0, 'forward.valid': 0,
                  'postedProof.valid': 0, 'canonicalStoreEpoch.valid': 0, 'frozenStoreProof.valid': 0}
        require(all(original[p + k] == v for k, v in active.items()), 'ACCEPTED_READ_ACTIVE_PAYLOAD_PREMISE')
        require(original['observation.startReady'] == 1, 'ORIGINAL_START_READY_PREMISE')
        if mode == 'head-token':
            require(original['observation.headPending'] == 1 and
                    tuple(model.order) == (read.token,) and divide.retired == 183 and
                    (original['observation.headToken.index'], original['observation.headToken.tag']) == read.token and
                    original['observation.start.valid'] == original['observation.eligible'] ==
                    original[p + 'collectionHeadRead'] == 1, 'REAL_HEAD_START_BEFORE_TAG_MUTATION')
            patch = [('actual', 'observation.headToken.tag', read.token[1] ^ (1 << 63))]
        else:
            require(original['observation.headPending'] == 0 and
                    tuple(model.order) == (divide.token, read.token) and not divide.retired and
                    (original['observation.headToken.index'], original['observation.headToken.tag']) == divide.token and
                    original['observation.start.valid'] == original['observation.eligible'] ==
                    original[p + 'collectionHeadRead'] == 0 and
                    original['io.headProfile.candidateLoadPc'] == read.instruction.pc,
                    'ORIGINAL_INVALID_YOUNGER_PAYLOAD_UNDER_DIV_HEAD')
            # Exact saved payload diagnostic, including inactive fields. The
            # original cycle119 valid is ZERO; this does not assert selection.
            later = rows[183]['actual']
            require(all(original[k] == later[k] for k in original if k.startswith(p) and
                        k != p + 'collectionHeadRead'), 'FULL_SAVED_START_PAYLOAD_DIAGNOSTIC')
            patch = [('actual', 'observation.start.valid', 1),
                     ('actual', 'observation.eligible', 1),
                     ('actual', p + 'collectionHeadRead', 1)]
    mutated = copy.deepcopy(row)
    changes = []
    for section, field, value in patch:
        before = mutated[section][field]
        require(before != value, 'NONVACUOUS_MUTATION')
        mutated[section][field] = value
        changes.append(dict(section=section, field=field, before=before, after=value))
    receipt = dict(anchor=control['anchor'], cycle=c, mode=mode, expected_error=control['error'],
        scope='saved-observation oracle sensitivity only; no DUT stimulus or DUT execution',
        changes=changes, original_frame=row, mutated_frame=mutated,
        independent_owner_state=dict(order=[list(t) for t in model.order],
            external=[list(t) for t in sorted(model.external)], pending=dict(model.pending),
            owners=[asdict(model.owners[t]) for t in model.order] + [asdict(store)]))
    return mutated, receipt


def canonical_owner_structure(value):
    """Lossless for this owner schema: only tuple/list representation differs."""
    def verify(item):
        if isinstance(item, dict):
            require(all(type(k) is str for k in item), 'OWNER_JSON_KEY_CONVERSION_RISK')
            for v in item.values():
                verify(v)
        elif isinstance(item, (tuple, list)):
            for v in item:
                verify(v)
        else:
            require(item is None or type(item) in (bool, int, str), 'OWNER_JSON_UNSUPPORTED_SCALAR')
    verify(value)
    return json.loads(json.dumps(value, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['positive', *CONTROLS], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = dict(status='FAIL', mode=args.mode, scope='saved-observation oracle sensitivity',
                  dut_executed=False, native_child_started=False, mutation_count=0,
                  successful_replay_frames=0, rejected_cycle=None, anchor=None, error=None,
                  source_sha256=digest(Path(__file__)), bindings=BOUND)
    exit_code = 2
    try:
        baseline, rows, publish, complete = bound_inputs()
        # Import only the verified frozen host's pure independent ledger/catalog.
        # No cases.py, generated model, native executable or subprocess is used.
        sys.path.insert(0, str(TASK / 'host-backend'))
        from decoded import Instruction
        from oracle import Ledger, Violation, schema
        from ports import INPUT_WIDTHS, OUTPUT_WIDTHS
        model = Ledger()
        result['authored_events'] = [publish, complete]
        mutation = None
        for source_row in rows:
            row = source_row
            c = row['actual']['cycle']
            if args.mode != 'positive' and c == CONTROLS[args.mode]['cycle']:
                row, mutation = inject(args.mode, source_row, model, rows)
                result['mutation_count'] += 1
                result['anchor'] = mutation['anchor']
                with (args.output / 'MUTATION.json').open('x') as out:
                    json.dump(mutation, out, indent=2); out.write('\n')
                print('BACKEND_OBSERVATION_ANCHOR', mutation['anchor'], 'cycle=' + str(c), flush=True)
            inp, actual = row['input'], row['actual']
            schema(inp, INPUT_WIDTHS); schema(actual, OUTPUT_WIDTHS, ('cycle',))
            if row['checked']:
                offers = tuple(Instruction(**op) if op else None for op in row['offers'])
                try:
                    model.observe(inp, actual, offers)
                except Violation as exc:
                    if args.mode != 'positive' and mutation is not None and result['mutation_count'] == 1 and \
                            c == CONTROLS[args.mode]['cycle'] and str(exc) == CONTROLS[args.mode]['error']:
                        result.update(status='REJECTED', rejected_cycle=c, error=str(exc), expected_rejection=True,
                                      counts_before_rejection=dict(model.counts))
                        exit_code = 1
                        break
                    raise
            result['successful_replay_frames'] = c
            if c == publish['cycle']:
                model.publish(actual)
            if c == complete['cycle']:
                owner = model.find(tuple(complete['token']))
                model.external_complete(owner)
        else:
            require(args.mode == 'positive' and result['mutation_count'] == 0, 'NEGATIVE_CONTROL_ESCAPED')
            expected = model.final(rows[-1]['actual'])
            require(dict(model.counts) == baseline['counts'], 'POSITIVE_REPLAY_ALL_COUNTERS')
            require(canonical_owner_structure([asdict(o) for o in model.owners.values()]) ==
                    canonical_owner_structure(baseline['owners']), 'POSITIVE_REPLAY_FULL_OWNER_LIFETIMES')
            require(model.registers == baseline['architectural_registers'], 'POSITIVE_REPLAY_ARCHITECTURAL_VALUES')
            result.update(status='PASS', expected_rejection=False, counts=dict(model.counts),
                          expected_exact_counts=expected, final_external=[], final_pending={}, final_order=[])
            exit_code = 0
    except Exception as exc:
        result['error'] = str(exc)
        print('BACKEND_OBSERVATION_FAILURE', str(exc), file=sys.stderr, flush=True)
    finally:
        result['process_exit_expected'] = exit_code
        with (args.output / 'RESULT.json').open('x') as out:
            json.dump(result, out, indent=2); out.write('\n')
    print('BACKEND_OBSERVATION_RESULT', result['status'], args.mode, flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
