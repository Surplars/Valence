#!/usr/bin/env python3
"""Bounded exact-model retirement attribution; no RTL build or production edit.

Instrument the hash-validated hot observer in a fresh output directory, replay
only the identical read-4KiB guest on the qualified LSU2/4 pair, and require all
existing result metrics to remain exact. Generated scalar identities are bound
by complete model receipts. Diagnostic negatives corrupt observations only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import cpu_mlp_bandwidth_board as mlp
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
    replace('    PerfCounts perf;', '    PerfCounts perf;\n    std::array<uint64_t,64> retireReasons{};uint64_t doneHeadChecks=0;')
    replace('        perf.sample(d);cpuStarts', '''        const bool rawEnable=b.bit(16);
        const bool branch=PREFIXbranchRedirectValid;
        bool order=PREFIXorderCheckValid;
        const bool replay=PREFIXreplayPendingValid;
        const bool recovery=PREFIXledger$recoveryCycle;
        check(recovery==bool(PREFIXledger$recovering||PREFIXledger$acceptRecovery),"recovery cycle equation mismatch");
        const bool exception=PREFIXledger$entries$$exception[b.head.index];
        if(injection=="--inject-retire-equation"&&b.headValid&&b.headDone&&rawEnable&&!branch&&!replay&&!recovery&&!exception)order=!order;
        const unsigned reason=unsigned(!rawEnable)|(unsigned(branch)<<1)|(unsigned(order)<<2)|
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
        std::cout<<"RETIRE_ATTRIBUTION name="<<name<<" done_head_checks="<<doneHeadChecks<<" attributed="<<attributed<<"\\n";
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


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args(); path=args.receipt.resolve(); out=args.out.resolve()
    require(not out.exists(),'choose a fresh diagnostic output directory'); out.mkdir(parents=True)
    original=json.loads(path.read_text()); receipt_hash=sha(path)
    require(original.get('status')=='PASS_SOURCE_MATCHED_CPU_LSU_CAPACITY_BOARD','qualified capacity pair required')
    require(original.get('schema')=='valence-cpu-lsu-capacity-board-v1','wrong capacity receipt schema')
    source=common.HERE/'harness/cpu_flow_bandwidth.cpp'
    frozen={**original['inputs'],str(Path(__file__).resolve().relative_to(common.ROOT)):sha(__file__)}
    shared=original['model_request']['shared_options']
    require(shared==dict(dma_line_transfers=True,dma_line_entries=4,dma_line_yield_cycles=0),'current shared profile required')
    board_inputs=board.source_inventory()
    binaries={}
    def guard():
        guests.stable(path,receipt_hash,'qualified capacity receipt')
        host=original['host_compiler'];guests.stable(host['path'],host['sha256'],'host compiler')
        actual_guest,_=mlp.normalize_guests(original['guest_input']['path'])
        require(actual_guest==original['guest_input'],'guest manifest drift')
        for name,digest in frozen.items():guests.stable(common.ROOT/name,digest,'diagnostic source')
        for name,digest in binaries.items():guests.stable(Path(name),digest,'diagnostic binary')
        for owners in (2,4):
            rec=original['models']['lsu'+str(owners)]
            guests.stable(rec['receipt'],rec['receipt_sha256'],'model receipt')
            mlp.validate_model(rec['receipt'],1,board_inputs,original['compiler'],lsu_entries=owners,**shared)
    guard()
    generated=out/'observer.cpp'; generated.write_text(instrument(source.read_text())); generated_hash=sha(generated)
    state={'schema':'valence-cpu-mlp-retire-attribution-v1','status':'RUNNING','capacity_receipt':str(path),
           'capacity_receipt_sha256':receipt_hash,'inputs':frozen,'instrumented_source_sha256':generated_hash,
           'reason_bits':['raw_commit_disabled','branch_redirect','load_order_check','pending_load_replay','recovery_cycle','head_exception'],
           'commands':[],'cases':{},'binaries':binaries,'limits':['Generated internal scalars bound to exact model receipts.',
           'Counters attribute existing holds; no changed RTL, mapped timing, or hypothetical performance claim.']}
    def save():(out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    def step(name,command,expected=0,anchor=None):
        guard();guests.stable(generated,generated_hash,'instrumented observer')
        if name.endswith('-link'):guests.stable(command[0],original['host_compiler']['sha256'],'compiler argv0 binary')
        log=out/(name+'.log'); start=time.monotonic()
        with log.open('w') as stream:
            run=subprocess.run(command,cwd=common.ROOT,stdout=stream,stderr=subprocess.STDOUT,
                               timeout=240,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=log.read_text();state['commands'].append({'name':name,'command':command,'exit':run.returncode,
            'seconds':time.monotonic()-start,'log':log.name,'log_sha256':sha(log)})
        save();require(run.returncode==expected and (anchor is None or anchor in text),name+' failed\n'+text[-5000:])
        return text
    save()
    try:
        for owners in (2,4):
            side='lsu'+str(owners); case=side+'-read-4096'; binary=out/(side+'-run')
            command=list(original['steps'][case+'-link']['command'])
            require(command.count(str(source))==1,'link source drift');command[command.index(str(source))]=str(generated)
            require(command.count('-o')==1,'link output drift');command[command.index('-o')+1]=str(binary)
            command.insert(1,'-I'+str(common.HERE/'harness'))
            step(side+'-link',command)
            binaries[str(binary)]=sha(binary);save()
            run=list(original['steps'][case+'-run']['command']);run[0]=str(binary)
            text=step(side+'-run',run,anchor='HOT_PASS')
            actual=parse(text); expected=original['cases'][side]['read-4096']
            require(actual['result']==expected['result'] and actual['pipeline']==expected['pipeline'] and
                    actual['distributions']==expected['distributions'] and actual['performance']==expected['performance'],
                    'instrumentation changed benchmark metrics')
            reasons={}
            for line in text.splitlines():
                if line.startswith('RETIRE_REASON '):
                    values=dict(field.split('=',1) for field in line.split()[1:]);reasons.setdefault(values['name'],{})[values['mask']]=int(values['cycles'])
            state['cases'][side]={'result':actual['result'],'reasons':reasons,'binary_sha256':sha(binary)};save()
            for mode,anchor in (('retire-equation','exact done-head commit equation mismatch'),('order-history','load-order check history mismatch')):
                step(side+'-negative-'+mode,run+['--inject-'+mode],expected=1,anchor=anchor)
        guard();guests.stable(generated,generated_hash,'final instrumented observer')
        state['status']='PASS_EXACT_MODEL_RETIREMENT_ATTRIBUTION'
    except BaseException as error:
        state['status']='FAIL';state['error']=str(error);save();raise
    save();print(state['status'],out/'receipt.json',flush=True)

if __name__=='__main__':main()
