"""Complete frozen CPU output capture with architectural and owner invariants."""
import hashlib, math
from pathlib import Path

PREFIXES = {'result':'CPU_SV39_RESULT', 'perf':'BOARD_IPC', 'oracle':'CPU_SV39_PASS',
            'fabric':'FABRIC_IDLE_PASS', 'counts':'PASSIVE_SUPPLY_COUNTS',
            'ledger':'LEDGER_PASS', 'adoption':'ADOPTION_PASS'}
DETAILS = ('LEDGER_REASON','LEDGER_CROSS','ADOPTION_CROSS',
           'PASSIVE_OPPORTUNITY_BUCKET','PASSIVE_SUPPLY_WITNESS')
ARCHITECTURAL = ('mode','op','bytes','reps','retired','pc_hash','loads','stores','lsu_capacity')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''): h.update(block)
    return h.hexdigest()

def parse(text,prefix):
    lines=[line for line in text.splitlines() if line.startswith(prefix+' ')]
    assert len(lines)==1,('required unique prefix',prefix,len(lines))
    pairs=[item.split('=',1) for item in lines[0].split()[1:]]
    assert all(len(item)==2 for item in pairs) and len(dict(pairs))==len(pairs)
    return dict(pairs)

def extract(text):
    row={key:parse(text,prefix) for key,prefix in PREFIXES.items()}
    row['detailed_metrics']={prefix:[parse(line,prefix) for line in text.splitlines()
                            if line.startswith(prefix+' ')] for prefix in DETAILS}
    row['traffic_regions']=[parse(line,'LEDGER_TOTAL') for line in text.splitlines() if line.startswith('LEDGER_TOTAL ')]
    row['adoption_regions']=[parse(line,'ADOPTION_TOTAL') for line in text.splitlines() if line.startswith('ADOPTION_TOTAL ')]
    assert sum(len(row[key]) for key in ('result','perf','oracle','fabric'))==105
    return row

def capture_result(text,work,old,actual_fabric):
    row=extract(text)
    for key in PREFIXES: assert row[key].keys()==old[key].keys(),('complete metric schema',key)
    for key in ARCHITECTURAL: assert row['result'][key]==old['result'][key],('architectural mismatch',key)
    assert row['oracle']==old['oracle'],'independent complete reply/checksum oracle mismatch'
    for key in old['fabric']:
        if key!='samples' and not key.endswith('_held_cycles'):
            assert row['fabric'][key]==old['fabric'][key],('fabric invariant',key)
    assert row['perf']['name']==old['perf']['name']
    assert row['perf']['retired']==row['result']['retired']
    assert row['perf']['cycles']==row['result']['cycles']
    assert sum(int(row['perf'][key]) for key in ('zero_commit','single_commit','dual_commit'))==int(row['result']['cycles'])
    assert int(row['perf']['single_commit'])+2*int(row['perf']['dual_commit'])==int(row['result']['retired'])
    assert row['counts']['req_fire']==old['counts']['req_fire'],'architectural request fire count'
    assert row['adoption']['attached']==row['adoption']['actual_cpu_response'],'adoption response owner balance'
    for key in ('cache_e_cycle','known_error_owners','known_error_path','resident_useful_semantics'):
        assert row['adoption'][key]==old['adoption'][key],('adoption invariant',key)
    for key in ('traffic_regions','adoption_regions'):
        assert [x['region'] for x in row[key]]==[x['region'] for x in old[key]],key
        for actual,baseline in zip(row[key],old[key]): assert actual.keys()==baseline.keys(),key
    for prefix in DETAILS:
        schemas={tuple(sorted(x)) for x in old['detailed_metrics'][prefix]}
        assert all(tuple(sorted(x)) in schemas for x in row['detailed_metrics'][prefix]),prefix
    # Each of the 105 fields has an explicit architectural/independent-oracle,
    # accounting, or measured-performance expectation. Timing/traffic may change.
    expectations={}
    for section in ('result','perf','oracle','fabric'):
        for key,value in row[section].items():
            label=section+'.'+key
            if section=='result' and key in ARCHITECTURAL:
                expectations[label]='exact architectural expectation from identical guest'
            elif section=='oracle':expectations[label]='exact independent reply/checksum expectation'
            elif section=='fabric' and key!='samples' and not key.endswith('_held_cycles'):
                expectations[label]='exact idle fabric service invariant'
            elif key=='name':expectations[label]='exact benchmark/privilege name'
            else:
                number=float(value);assert math.isfinite(number) and number>=0,('invalid measured field',label,value)
                expectations[label]='nonnegative finite measured value; timing/traffic equality not required'
    assert len(expectations)==105
    capacities={'lsu_peak':actual_fabric['cpu']['memoryEntries'],
                'cache_owner_peak':actual_fabric['cache']['readMshrs'],
                'axi_read_peak':actual_fabric['ddr']['maxOutstanding']}
    assert int(row['result']['lsu_capacity'])==capacities['lsu_peak']
    for key,limit in capacities.items():
        assert int(row['result'][key])<=limit,('capacity exceeded',key)
    cycles=int(row['result']['cycles']);assert cycles>0
    assert abs(float(row['perf']['ipc'])-int(row['result']['retired'])/cycles)<=0.000001
    throughput=int(row['result']['bytes'])*int(row['result']['reps'])*100000000/cycles/1048576
    assert abs(float(row['result']['payload_MiBps'])-throughput)<=0.000001
    row['field_expectations']=expectations
    row['capacity_expectations_from_actual_fabric']=capacities
    row['raw']={name:sha(Path(work)/name) for name in ('supply-events.tsv','axi-events.tsv')}
    row['inclusive_cycles']=int(row['result']['cycles'])+int(row['result']['clean_tail'])
    row['baseline_inclusive_cycles']=int(old['result']['cycles'])+int(old['result']['clean_tail'])
    row['inclusive_delta']=row['inclusive_cycles']-row['baseline_inclusive_cycles']
    row['roi_delta']=int(row['result']['cycles'])-int(old['result']['cycles'])
    row['tail_delta']=int(row['result']['clean_tail'])-int(old['result']['clean_tail'])
    row['functional_fields_captured']=105
    row['performance_verdict']='PARENT_REVIEW_REQUIRED_NO_AUTOMATIC_SPEEDUP_CLAIM'
    row['cause_attribution']='PENDING_OPTIONAL_PASSIVE_BINDING_NO_DUT_PORTS'
    row['baseline_kind']='QUALIFIED_COMPACT_PUBLISHED_OPTIONAL_BRIDGE_NOT_FRESH_OFF'
    return row
