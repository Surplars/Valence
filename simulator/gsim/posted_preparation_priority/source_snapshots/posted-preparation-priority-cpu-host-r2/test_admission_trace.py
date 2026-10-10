import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path
from admission_trace import validate, need

p = Path(os.environ['ADMISSION_FIXTURE_DIR'])
configured_life = os.environ.get('PREFETCH_CANDIDATE_CYCLES')
base = p / ('fixture-life'+configured_life) if configured_life else p / 'fixture'
rows = [json.loads(l) for l in base.with_suffix('.jsonl').read_text().splitlines()]
life = rows[-1]['lifetime']
need(configured_life is None or int(configured_life) == life, 'fixture/config lifetime mismatch')
binary = Path(os.environ.get('ADMISSION_TEST_BINARY', str(p/('test-life'+str(life)) if configured_life else p/'test_admission')))
log = base.with_suffix('.log').read_text()
positive = validate(base.with_suffix('.jsonl'), log)

def first(x, event, pred=lambda r: True):
    return next(r for r in x if r['event'] == event and pred(r))

cases = {
    'schema_downgrade': lambda x: first(x, 'summary').pop('schema'),
    'candidate_address': lambda x: first(x, 'candidate').update(address=1),
    'candidate_source': lambda x: first(x, 'candidate').update(source_seq=999),
    'candidate_origin': lambda x: first(x, 'candidate').update(store=1),
    'candidate_hint': lambda x: first(x, 'candidate').update(hint=0),
    'candidate_deadline': lambda x: first(x, 'candidate').update(deadline=999),
    'candidate_cancel': lambda x: first(x, 'candidate').update(cancelled_on_emit=1),
    'source_hint': lambda x: first(x, 'decision').update(source_hint=0),
    'held_origin': lambda x: first(x, 'decision').update(store=1),
    'held_address': lambda x: first(x, 'decision').update(candidate_address=0x802000c0),
    'deadline_refresh': lambda x: first(x, 'decision').update(remaining=life),
    'absolute_deadline': lambda x: first(x, 'decision').update(deadline=999),
    'attempt_number': lambda x: first(x, 'decision').update(attempt=2),
    'read_history': lambda x: first(x, 'read_accept', lambda r:r['last_valid']).update(last_line=9),
    'allocation_origin': lambda x: first(x, 'allocation_witness').update(store=1),
    'allocation_address': lambda x: first(x, 'allocation_witness').update(address=2),
    'allocation_index': lambda x: first(x, 'allocation_witness').update(index=4),
    'allocation_missing': lambda x: first(x, 'decision', lambda r:r['allocate']).update(allocate=0),
    'allocation_cancel': lambda x: first(x, 'decision', lambda r:r['allocate']).update(cancel=1),
    'invalid_tracked_payload': lambda x: first(x, 'read_accept').update(tracked_address=5),
    'invalid_way_payload': lambda x: first(x, 'decision').update(way_tag=[None,99]),
    'invalid_mshr_payload': lambda x: first(x, 'decision')['mshrs'][0].update(address=99),
    'invalid_wb_payload': lambda x: first(x, 'decision')['wbs'][0].update(address=99),
    'invalid_demand_payload': lambda x: first(x, 'decision').update(needs_miss=1),
    'wrong_useful_origin': lambda x: first(x, 'tracked_release').update(store=1),
    'wrong_roi_carry': lambda x: first(x, 'roi_boundary').update(id=1,store=0),
    'allocation_steals_slot': lambda x: first(x, 'decision', lambda r:r['allocate'])['mshrs'][0].update(phase=2,index=17,address=0x80200440),
}
if life > 1:
    cases.update({
        'retain_missing': lambda x: first(x, 'decision', lambda r:r['retain']).update(retain=0,cancel=1),
        'retain_extra': lambda x: first(x, 'decision', lambda r:r['allocate']).update(retain=1,allocate=0),
        'refresh_both_deadline_and_remaining': lambda x: first(x, 'decision', lambda r:r['attempt']==2).update(deadline=999,remaining=14),
        'cancel_then_continue': lambda x: first(x, 'decision').update(retain=0,cancel=1),
    })
for event in ['read_accept', 'candidate', 'decision', 'allocation_witness', 'tracked_release', 'roi_boundary', 'summary']:
    cases['missing_'+event] = lambda x,e=event:x.pop(next(i for i,r in enumerate(x) if r['event']==e))
    cases['duplicate_'+event] = lambda x,e=event:x.insert(next(i for i,r in enumerate(x) if r['event']==e),copy.deepcopy(first(x,e)))
for gate in range(17):
    cases['veto_'+str(gate)] = lambda x,g=gate:first(x,'decision')['gates'].__setitem__(g,not first(x,'decision')['gates'][g])

rejected=[]
with tempfile.TemporaryDirectory() as td:
    q=Path(td)/'poison.jsonl'
    for name,mut in cases.items():
        bad=copy.deepcopy(rows);mut(bad);q.write_text(''.join(json.dumps(r)+'\n' for r in bad))
        try: validate(q,log)
        except (ValueError,KeyError,TypeError): rejected.append(name)
        else: raise AssertionError('negative escaped '+name)
    # These process-level controls must fail nonzero, independently of C++ catch tests.
    process_controls={}
    for mode in ['poison_refresh','poison_overdue','poison_origin','poison_payload']:
        env=dict(os.environ,READ_PREFETCH_TRACE=str(q))
        out=subprocess.run([str(binary),mode],env=env,capture_output=True,text=True)
        need(out.returncode != 0 and 'ADMISSION_REJECT' in out.stderr,'nonzero poison escaped '+mode)
        process_controls[mode]=dict(returncode=out.returncode,error=out.stderr.strip())
    fixtures={}
    for mode in ['fixture_store','fixture_expire','fixture_carry','fixture_flush','fixture_birth_flush']:
        dest=p/('life'+str(life)+'-'+mode+'.jsonl')
        out=subprocess.run([str(binary),mode],env=dict(os.environ,READ_PREFETCH_TRACE=str(dest)),capture_output=True,text=True)
        need(out.returncode==0,'fixture failed '+mode+': '+out.stderr)
        dest.with_suffix('.log').write_text(out.stdout)
        fixtures[mode]=validate(dest,out.stdout)['summary']
    need(fixtures['fixture_store']['all']['allocate']==[0,1],'store lifetime endpoint')
    need(fixtures['fixture_expire']['all']['cancelled']==[1,0] and fixtures['fixture_expire']['all']['allocate']==[0,0],'expiration endpoint')
print(json.dumps(dict(status='PASS_FIXED_DEADLINE_PARSER_CONTROLS',lifetime=life,rejected=rejected,process_controls=process_controls,
                     positive=positive['summary'],fixtures=fixtures),indent=2))
