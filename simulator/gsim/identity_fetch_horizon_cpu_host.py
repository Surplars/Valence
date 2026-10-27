"""New passive OLD-member capture of unchanged certified CPU hosts.

The original hosts, program bytes, service law and archived receipts are never
edited. Header declarations are checked per model; NO $NEXT or inferred epoch
is sampled. This helper does not compile or simulate when imported.
"""
from pathlib import Path
import itertools
from collections import deque
import re
import struct
import certified_ingress_cpu_host as certified
import advisory_owner_trace as trace
cpu = trace.cpu
ROOT = cpu.common.ROOT
TOP = trace.TOP
INVENTORY = ROOT/'build/fetch-packet-supply-assessment-20261025-r1/existing-member-inventory.json'


def adapters(model):
    return certified.adapters(model)


def capture_fields(fir, header):
    fields = trace.schema(fir, header)
    for f in fields:
        f['expression'] = 'd.get_' + f['getter'] + '()'
        f['capture'] = 'raw; validity metadata is not a sampling filter'
    declarations = {}
    for m in re.finditer(r'^uint(8|16|32|64)_t ([A-Za-z0-9_$]+)((?:\[\d+\])*); // width = (\d+), lineno = \d+$', header, re.M):
        declarations[m[2]] = (m[0], [int(n) for n in re.findall(r'\[(\d+)\]',m[3])], int(m[4]))
    # Preserve the independently reviewed original semantic anchors. A member
    # must still exist; renamed/eliminated anchors need a new explicit review.
    selected = {re.sub(r'\[\d+\]', '', f['expression'][2:]) for f in cpu.read(INVENTORY)['fields']}
    for name in declarations:
        if '$NEXT' in name:
            continue
        if (re.fullmatch(r'tile\$frontend\$(valid|bases|contexts|words|errors|pageFaults|replace)', name) or
            re.match(r'tile\$frontend\$demandOwners\$(entries|heldOffer|_io_request_bits_T|io\$\$request|io\$\$head)', name) or
            re.fullmatch(r'tile\$frontend\$(wantedPacket|cachedTarget|thirdEligible.*|horizonCovered.*|returning.*)', name) or
            re.match(r'tile\$frontend\$suppliedPackets_window\$(contents|present|context|regions|regionIds|offsets)', name) or
            re.match(r'tile\$fetchAdapter\$pipeline\$(held|heldCommand|liveCommand|_engine_io_command_bits_T|nextToken|nextResult)', name) or
            re.match(r'tile\$fetchAdapter\$pipeline\$engine\$(translationCommand|translationSlot|identity|translating|issued)', name) or
            re.match(r'tile\$fetchAdapter\$pipeline\$engine\$ledger\$(live|done|tokens|data|errors|pages|head|tail|count|io\$\$)', name) or
            re.match(r'tile\$fetchAdapter\$pipeline\$engine\$permission\$(valid|owner|captured|savedMask|savedErrors|mask|errors|checkedMask|checkedErrors|release)', name) or
            re.match(r'tile\$fetchAdapter\$pipeline\$engine\$returns\$routes\$(ram|enq_ptr_value|deq_ptr_value|maybe_full|io_deq_bits_MPORT)', name)):
            selected.add(name)
    for name in sorted(selected):
        cpu.need('$NEXT' not in name and name in declarations, 'missing OLD direct member: '+name)
        declaration, dims, width = declarations[name]
        cpu.need(width <= 64, 'wide member needs explicit chunk schema: '+name)
        for indices in itertools.product(*(range(n) for n in dims)):
            suffix = ''.join('['+str(n)+']' for n in indices)
            fields.append({'getter':'internal.'+name+suffix, 'expression':'d.'+name+suffix,
                'width':width, 'when':'raw OLD; consumer must qualify', 'declaration':declaration})
    cpu.need(len({f['getter'] for f in fields}) == len(fields), 'duplicate capture field')
    return fields


def prepare_capture(model, out, sources):
    model, out = Path(model).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    header, fir = model/(TOP+'.h'), model/(TOP+'.fir')
    fields = capture_fields(fir.read_text(), header.read_text())
    cpu.save(out/'trace-schema.json', fields)
    lines = ['#pragma once', '#include "advisory_owner_trace.h"', 'namespace advisory_owner_trace {',
             'template<class D> void Observer::observe(D &d) {']
    lines += ['record(uint64_t('+f['expression']+'));' for f in fields]
    lines += ['++cycles;', '}', '}']
    (out/'advisory_owner_trace_generated.h').write_text('\n'.join(lines)+'\n')
    for kind, source in sources.items():
        after, diff = trace.adapt(kind, Path(source))
        (out/(kind+'.cpp')).write_text(after)
        (out/(kind+'.diff')).write_text(diff)
    inputs = {str(p):cpu.sha(p) for p in (Path(__file__).resolve(), trace.HEADER,
        Path(trace.__file__), INVENTORY, header, fir, *(Path(p) for p in sources.values()))}
    plan = {'schema':'valence-advisory-owner-exact-trace-plan-v1', 'model':str(model), 'output':str(out),
        'kinds':list(sources), 'sources':{k:str(Path(v).resolve()) for k,v in sources.items()},
        'fields_per_cycle':len(fields), 'inputs':inputs, 'new_DUT_compilations':0,
        'scope':'Raw OLD actual members, complete 64-bit owner/token/context; no NEXT, writes or extra settle',
        'prepared':{str(p):cpu.sha(p) for p in out.iterdir() if p.is_file()}}
    cpu.save(out/'plan.json',plan)
    return plan


def run_capture(plan, tools, first_build):
    return trace.run_prepared(plan, tools, first_build)


def collect_capture(plan, enabled):
    out = Path(plan['output'])
    fields = cpu.read(out/'trace-schema.json')
    indices = {f['getter']:i for i,f in enumerate(fields)}
    def at(row, name):
        key = name if name in indices else 'internal.'+name
        cpu.need(key in indices, 'missing required direct capture '+name)
        return row[indices[key]]
    front = 'tile$frontend$'
    owner = front+'demandOwners$'
    pipe = 'tile$fetchAdapter$pipeline$'
    ledger = pipe+'engine$ledger$'
    results = {}
    for path in sorted(out.glob('*.bin')):
        payload = path.read_bytes()
        cpu.need(len(payload) % (8*len(fields)) == 0, 'partial trace row')
        cycles = accepted = third = empty = captured = returns = 0
        observations = []
        pending = deque()
        held_offer = None
        for row in struct.iter_unpack('<'+'Q'*len(fields), payload):
            current, context = at(row,front+'currentBase'), at(row,front+'context')
            count = at(row,owner+'count')
            held = at(row,owner+'held')
            cpu.need(count <= 2 and count+held <= 2, 'actual owner/held credit overflow')
            cpu.need(at(row,ledger+'count') == count, 'frontend/global-result atomic credit mismatch')
            cpu.need(len(pending) == count, 'independent accepted obligations disagree with OLD hardware count')
            for position, obligation in enumerate(pending):
                oslot = (at(row,owner+'head')+position)&1
                lslot = (at(row,ledger+'head')+position)&1
                cpu.need(at(row,owner+f'entries$$base[{oslot}]') == obligation['base'] and
                    at(row,owner+f'entries$$context[{oslot}]') == obligation['context'] and
                    at(row,ledger+f'tokens[{lslot}]') == obligation['token'],
                    'actual full address/context and ledger token do not name the accepted owner')
            cpu.need(sum(at(row,owner+'valid['+str(i)+']') for i in range(2)) == count, 'owner valid/count mismatch')
            oldhead = at(row,owner+'head')
            bases = [(current+8*i)&((1<<64)-1) for i in range(3)]
            covered = []
            for address in bases:
                index = (address>>3)&15
                cache = any(at(row,front+f'valid[{index}][{w}]') and
                    at(row,front+f'bases[{index}][{w}]') == address and
                    at(row,front+f'contexts[{index}][{w}]') == context for w in range(2))
                owned = any(at(row,owner+f'valid[{i}]') and not at(row,owner+f'entries$$stale[{i}]') and
                    at(row,owner+f'entries$$base[{i}]') == address and
                    at(row,owner+f'entries$$context[{i}]') == context for i in range(2))
                live = (at(row,front+'returningPayload') and count and
                    at(row,owner+f'entries$$base[{oldhead}]') == address and
                    at(row,owner+f'entries$$context[{oldhead}]') == context and
                    not at(row,owner+f'entries$$stale[{oldhead}]'))
                covered.append(bool(cache or owned or live))
            eligible = bool(enabled and not(context&4) and current+23 < 1<<64 and
                0x80200000 <= current+16 and current+23 < 0x80220000)
            index = 0 if not covered[0] else 2 if covered[1] and eligible else 1
            cpu.need(at(row,front+'wanted') == bases[index], 'independent OLD cache/owner/return selector mismatch')
            fire = at(row,'io$$virtualFetchFire')
            offer = at(row,owner+'_io_request_valid_T_4')
            offered = (at(row,owner+'_io_request_bits_T$$base'),
                at(row,owner+'_io_request_bits_T$$context'), at(row,owner+'_io_request_bits_T$$mask'))
            command = (at(row,pipe+'_engine_io_command_bits_T$$satp'),
                at(row,pipe+'_engine_io_command_bits_T$$privilege'),
                at(row,pipe+'heldCommand$$sum') if at(row,pipe+'held') else at(row,'io$$vm$$sum'),
                at(row,pipe+'heldCommand$$mxr') if at(row,pipe+'held') else at(row,'io$$vm$$mxr'))
            if held:
                cpu.need(offer and held_offer is not None and offered == held_offer['payload'] and
                    command == held_offer['command'], 'actual held address/context/mask/full VM command drift')
            else:
                cpu.need(held_offer is None, 'held reservation vanished without acceptance')
            original_third = held_offer['third'] if held else bool(index == 2)
            if offer and not held:
                cpu.need(offered[0] == bases[index], 'first public offer differs from independent nominal address')
                if not fire:
                    held_offer = {'payload':offered,'command':command,'third':original_third,
                                  'eligible':eligible,'first_offer_cycle':cycles}
            ret = at(row,pipe+'_io_virtual_response_valid_T')
            accepted += fire; returns += ret
            empty += at(row,'io$$packetPresent') == 0
            captured += at(row,'tile$core$core$core$fetchPacket$circular$_captured_T')
            if ret:
                cpu.need(pending and at(row,pipe+'nextResult') == pending[0]['token'],
                    'actual returned token does not match independent oldest accepted command')
                pending.popleft()['return_cycle'] = cycles
            if fire:
                request = at(row,owner+'_io_request_bits_T$$base')
                mask = at(row,owner+'_io_request_bits_T$$mask')
                token = at(row,pipe+'nextToken')
                isthird = original_third
                cpu.need(not isthird or (held_offer['eligible'] if held else eligible),
                    'third fetch escaped original identity safe RAM eligibility')
                third += isthird
                observations.append({'cycle':cycles,'base':request,'mask':mask,
                    'context':at(row,owner+'_io_request_bits_T$$context'),
                    'command_satp':at(row,pipe+'_engine_io_command_bits_T$$satp'),
                    'command_privilege':at(row,pipe+'_engine_io_command_bits_T$$privilege'),
                    'token':token,'old_owner_count':count,'old_result_count':at(row,ledger+'count'),
                    'third':bool(isthird),'current_base':current,'covered':covered})
                pending.append(observations[-1])
                held_offer = None
            cycles += 1
        cpu.need(cycles > 0, 'empty trajectory')
        cpu.need(not pending and held_offer is None, 'full-work capture ended before fetch obligations drained')
        results[path.stem] = {'cycles':cycles,'accepted_requests':accepted,'third_requests':third,
            'accepted_request_duty':accepted/cycles,'packet_empty_cycles':empty,'raw_capture_signal_sum':captured,
            'virtual_return_valid_cycles':returns,'request_observations':observations,
            'trace_sha256':cpu.sha(path)}
    cpu.need(results, 'no actual capture trajectories')
    result = {'status':'PASS_IDENTITY_FETCH_HORIZON_DIRECT_OLD_CAPTURE', 'enabled':enabled,
        'scope':'all sampled OLD scheduler states, actual full owner/token requests; independent architectural hosts retain trap/order/drain checks',
        'fields_per_cycle':len(fields),'schema_sha256':cpu.sha(out/'trace-schema.json'),'trajectories':results}
    cpu.save(out/'identity-fetch-analysis.json',result)
    return result
