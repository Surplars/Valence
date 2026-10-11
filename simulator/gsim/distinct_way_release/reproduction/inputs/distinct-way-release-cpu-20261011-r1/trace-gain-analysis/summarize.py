#!/usr/bin/env python3
"""Small, non-mutating-input supplement: exact time partitions, not causal estimates."""
import hashlib,json,pathlib
HERE=pathlib.Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
p=HERE/'analysis.json';a=read(p)
mfile=HERE.parent/'case19-metrics-comparison.json';m=read(mfile)
parts={}
for side in ('baseline','on'):
 v=a['runs'][side]['metrics'];accept=v['demand_accept_minus_pf_allocation']['sum'];refill=v['demand_refill_minus_pf_allocation']['sum'];span=v['group_span']['sum']
 parts[side]={'pf_allocation_to_demand_accept':accept,'demand_accept_to_demand_refill':refill-accept,'demand_refill_to_next_pf_or_accepted_roi_end':span-refill}
deltas={k:parts['baseline'][k]-parts['on'][k] for k in parts['baseline']}
assert sum(deltas.values())==a['accounting']['observed_kernel_gain']==46769
b=m['baseline']['axi']['roi'];n=m['candidate']['axi']['roi']
idle_delta=b['whole_bus_empty']-n['whole_bus_empty']
other_delta=(b['cycles']-b['whole_bus_empty'])-(n['cycles']-n['whole_bus_empty'])
assert idle_delta+other_delta==46769
out={
 'schema':'distinct-way-release-exact-time-accounting-v1',
 'status':'PASS_ORIGINAL_RAW_JOINS_AND_EXACT_NONOVERLAPPING_ACCOUNTING',
 'comparison_scope':a['scope'],
 'inputs':{'analysis_sha256':sha(p),'metrics_comparison_sha256':sha(mfile),'script_sha256':sha(pathlib.Path(__file__))},
 'per_run_disjoint_group_intervals':parts,
 'baseline_minus_on_interval_cycles':deltas,
 'kernel_gain_cycles':46769,
 'roi_prefix_delta_cycles':a['accounting']['roi_prefix_delta'],
 'whole_bus_partition_baseline_minus_on':{'whole_bus_empty_cycles':idle_delta,'all_other_cycles':other_delta,'total':idle_delta+other_delta},
 'read_outstanding_without_R_valid':{'baseline':b['read_outstanding_without_r_valid'],'on':n['read_outstanding_without_r_valid']},
 'read_outstanding_cycle_sum':{'baseline':b['read_outstanding_cycle_sum'],'on':n['read_outstanding_cycle_sum']},
 'prefetch_allocation_to_refill_sum':{'baseline':a['runs']['baseline']['metrics']['pf_refill_minus_pf_allocation']['sum'],'on':a['runs']['on']['metrics']['pf_refill_minus_pf_allocation']['sum']},
 'interpretation':'All 2015 matched ordinary different-way dirty ReleaseData C bursts finish before the matched store-prefetch first D beat with ON, versus zero in baseline. This bounds C before PF E under the pinned engine. Group interval differences and bus partitions account for elapsed time exactly; they do not independently establish exclusive stall causes. No DDR latency reduction or hidden-DDR-latency claim.',
 'remaining_unknown':a['unknown'],
}
(HERE/'gap-accounting.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
print(json.dumps({'interval_deltas':deltas,'bus_partition':out['whole_bus_partition_baseline_minus_on']}))
