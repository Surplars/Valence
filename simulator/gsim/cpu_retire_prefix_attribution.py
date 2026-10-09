#!/usr/bin/env python3
"""Bounded exact-model retirement attribution; no RTL build or production edit.

Instrument the hash-validated hot observer in a fresh output directory, replay
only the identical read-4KiB guest on the qualified older-prefix OFF/ON pair, and require all
existing result metrics to remain exact. Generated scalar identities are bound
by complete model receipts. Diagnostic negatives corrupt observations only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import cpu_retire_prefix_provenance as proof
import cpu_retire_prefix_board as mlp
import build_cpu_hot_bandwidth as guests
import fpga_next_board as board
import run as common
from cpu_hot_bandwidth import parse

require, sha = guests.require, guests.sha
PREFIX = 'd.board$platform$core$core$core$backend$'


def instrument(source):
    def replace(old, new):
        nonlocal source
        require(source.count(old) == 1, 'instrumentation anchor drift: ' + old[:70])
        source = source.replace(old, new)
    replace('    PerfCounts perf;', '    PerfCounts perf;\n    std::array<uint64_t,64> retireReasons{};uint64_t doneHeadChecks=0,orderCycles=0,olderRetireCycles=0,olderRetired=0,checkedAtHead=0,invalidCheckedOwner=0;')
    replace('        perf.sample(d);cpuStarts', '''        const bool rawEnable=b.bit(16);
        const bool branch=PREFIXbranchRedirectValid;
        bool order=PREFIXorderCheckValid;
        bool orderBlocked=order;
#if RETIRE_PREFIX_ENABLED
        if(order){
            ++orderCycles;
            int position=-1;
            const unsigned count=PREFIXledger$count;
            check(count<=16,"ROB count exceeds selected geometry");
            for(unsigned i=0,index=b.head.index;i<count;++i,index=(index+1)%16)
                if(index==PREFIXorderCheckIndex && PREFIXledger$entries$$tag[index]==PREFIXorderCheckTag)
                    position=int(i);
            orderBlocked=position<=0;
            invalidCheckedOwner+=position<0; checkedAtHead+=position==0;
            check((position>=0&&b.commits<=unsigned(position))||b.commits==0,"checked or younger owner retired during check");
            if(b.commits){++olderRetireCycles;olderRetired+=b.commits;}
        }
#else
        orderCycles+=order;
#endif
        const bool replay=PREFIXreplayPendingValid;
        const bool recovery=PREFIXledger$recoveryCycle;
        check(recovery==bool(PREFIXledger$recovering||PREFIXledger$acceptRecovery),"recovery cycle equation mismatch");
        const bool exception=PREFIXledger$entries$$exception[b.head.index];
        if(injection=="--inject-retire-equation"&&b.headValid&&b.headDone&&rawEnable&&!branch&&!replay&&!recovery&&!exception)orderBlocked=!orderBlocked;
        const unsigned reason=unsigned(!rawEnable)|(unsigned(branch)<<1)|(unsigned(orderBlocked)<<2)|
            (unsigned(replay)<<3)|(unsigned(recovery)<<4)|(unsigned(exception)<<5);
        if(b.headValid&&b.headDone){
            ++doneHeadChecks;
            check(bool(d.get_io$$commit0())==(reason==0),"exact done-head commit equation mismatch");
        }
        perf.sample(d);cpuStarts'''.replace('PREFIX', PREFIX))
    replace('        ++buckets[bucket];', '''        ++buckets[bucket];
        if(bucket=="done_awaiting_retire"){
            check(reason!=0,"unattributed done-head retirement hold");++retireReasons[reason];
        }''')
    replace('        uint64_t total=0;for(auto [bucket,n]:buckets)', '''        uint64_t attributed=0;
        for(unsigned mask=0;mask<retireReasons.size();++mask)if(retireReasons[mask]){
            attributed+=retireReasons[mask];
            std::cout<<"RETIRE_REASON name="<<name<<" mask="<<mask<<" cycles="<<retireReasons[mask]<<"\\n";
        }
        check(attributed==(buckets.count("done_awaiting_retire")?buckets.at("done_awaiting_retire"):0),"retirement attribution conservation");
        std::cout<<"RETIRE_ATTRIBUTION name="<<name<<" done_head_checks="<<doneHeadChecks<<" attributed="<<attributed<<" order_cycles="<<orderCycles
            <<" older_retire_cycles="<<olderRetireCycles<<" older_retired="<<olderRetired
            <<" checked_at_head="<<checkedAtHead<<" invalid_checked_owner="<<invalidCheckedOwner<<"\\n";
        uint64_t total=0;for(auto [bucket,n]:buckets)''')
    replace('    unsigned observedLiveOwners=0;bool observedStart=false;',
            '    bool previousOrderStart=false;\n    unsigned observedLiveOwners=0;bool observedStart=false;')
    replace('        if(b.reset){data.advance(b,p,backend);backend.advance(b);++cycle;return;}', '''        bool observedOrder=PREFIXorderCheckValid;
        if(injection=="--inject-order-history")observedOrder=!observedOrder;
        if(b.reset)previousOrderStart=false;
        else {check(observedOrder==previousOrderStart,"load-order check history mismatch");previousOrderStart=b.bit(3)&&b.bit(8);}
        if(b.reset){data.advance(b,p,backend);backend.advance(b);++cycle;return;}'''.replace('PREFIX', PREFIX))
    replace('const std::array<std::string,10> modes', 'const std::array<std::string,12> modes')
    replace('"--inject-upper-live","--inject-upper-token","--inject-reserve-guard"};',
            '"--inject-upper-live","--inject-upper-token","--inject-reserve-guard",\n            "--inject-retire-equation","--inject-order-history"};')
    return source


def link_command(inputs, side, generated, binary):
    model = inputs.models[side]
    return [str(inputs.cxx), '-DRETIRE_PREFIX_ENABLED=' + str(int(side == 'on')),
            '-I' + str(common.HERE / 'harness'),
            *proof.hot_flags('read-4096', model['model'], inputs.cases['read-4096']['directory']),
            str(generated), *map(str, model['objects']), '-ldl', '-o', str(binary)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    path, out = args.receipt.resolve(), args.out.resolve()
    require(not out.exists(), 'choose a fresh diagnostic output directory')
    inputs = proof.HotInputs(path)
    inputs.add(Path(__file__).resolve())
    inputs.check_compiler_version()
    original = inputs.state
    source = common.HERE / 'harness/cpu_retire_prefix_hot.cpp'
    out.mkdir(parents=True)
    generated = out / 'observer.cpp'
    generated.write_text(instrument(source.read_text()))
    generated_hash = sha(generated)
    state = {'schema': 'valence-cpu-older-prefix-retire-attribution-v1', 'status': 'RUNNING',
        'hot_receipt': str(path), 'hot_receipt_sha256': sha(path), 'inputs': dict(inputs.files),
        'instrumented_source_sha256': generated_hash,
        'reason_bits': ['raw_commit_disabled', 'branch_redirect', 'load_order_check',
                       'pending_load_replay', 'recovery_cycle', 'head_exception'],
        'commands': [], 'steps': {}, 'cases': {}, 'binaries': {},
        'artifacts': {generated.name: generated_hash},
        'limits': ['Generated internal scalars bound to exact model receipts.',
                   'Counters attribute existing holds; no changed RTL, mapped timing, or hypothetical performance claim.']}
    contracts = {}

    def save():
        (out / 'receipt.json').write_text(json.dumps(state, indent=2) + '\n')

    def guard():
        inputs.guard()
        for name in proof.quote_dependencies():
            require(not (out / name).exists(), 'diagnostic header shadow: ' + name)
        require(generated.read_text() == instrument(source.read_text()) and sha(generated) == generated_hash,
                'instrumented observer drift')
        for name, contract in contracts.items():
            proof.cached_step(out, state, name, **contract)
        expected_artifacts = {generated.name} | {str(p.relative_to(out))
            for contract in contracts.values() for p in contract['products']}
        require(set(state['artifacts']) == expected_artifacts, 'diagnostic artifact inventory drift')

    def step(name, command, products=(), expected=0, anchor=None):
        guard()
        contract = dict(argv=command, products=products, expected=expected, anchor=anchor)
        log = out / (name + '.log')
        start = time.monotonic()
        with log.open('x') as stream:
            run = subprocess.run(command, cwd=common.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                timeout=240, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = log.read_text()
        record = {'name': name, 'command': command, 'exit': run.returncode, 'actual_exit': run.returncode,
            'expected_exit': expected, 'anchor': anchor, 'status': 'PASS' if run.returncode == expected else 'FAIL',
            'seconds': time.monotonic() - start, 'log': log.name, 'log_sha256': sha(log),
            'artifacts': {str(p.relative_to(out)): sha(p) for p in products if p.is_file()}}
        state['commands'].append(record)
        state['steps'][name] = record
        state['artifacts'].update(record['artifacts'])
        contracts[name] = contract
        save()
        proof.cached_step(out, state, name, **contract)
        guard()
        return text

    save()
    try:
        for side in proof.LABELS:
            binary = out / (side + '-run')
            step(side + '-link', link_command(inputs, side, generated, binary), products=(binary,))
            state['binaries'][str(binary)] = sha(binary)
            run = [str(binary), str(inputs.cases['read-4096']['directory'] / 'guest.bin')]
            text = step(side + '-run', run, anchor='HOT_PASS')
            actual, expected = parse(text), original['cases'][side]['read-4096']
            require(all(actual[key] == expected[key] for key in actual), 'instrumentation changed benchmark metrics')
            reasons = {}
            for line in text.splitlines():
                if line.startswith('RETIRE_REASON '):
                    values = dict(field.split('=', 1) for field in line.split()[1:])
                    require(values['mask'] not in reasons.setdefault(values['name'], {}), 'duplicate retirement reason')
                    reasons[values['name']][values['mask']] = int(values['cycles'])
            state['cases'][side] = {'result': actual['result'], 'reasons': reasons, 'binary_sha256': sha(binary)}
            save()
            for mode, anchor in (('retire-equation', 'exact done-head commit equation mismatch'),
                                 ('order-history', 'load-order check history mismatch')):
                step(side + '-negative-' + mode, run + ['--inject-' + mode], expected=1, anchor=anchor)
        require(set(state['cases']) == set(proof.LABELS), 'incomplete diagnostic case inventory')
        require(set(state['steps']) == {side + suffix for side in proof.LABELS for suffix in
            ('-link', '-run', '-negative-retire-equation', '-negative-order-history')}, 'diagnostic step inventory drift')
        require(state['commands'] == list(state['steps'].values()), 'diagnostic command/step disagreement')
        guard()
        state['status'] = 'PASS_EXACT_MODEL_RETIREMENT_ATTRIBUTION'
    except BaseException as error:
        state['status'] = 'FAIL'
        state['error'] = str(error)
        save()
        raise
    save()
    print(state['status'], out / 'receipt.json', flush=True)


if __name__ == '__main__':
    main()
