#!/usr/bin/env python3
"""Literal native state, ports, hierarchy and all-RAM audit of the exact pair."""
from pathlib import Path
import copy,json,re
import run as b
H=b.HERE;A=H/'analysis';E=b.OUT
def main():
 p=b.read(H/'pins.json');b.guard(p);receipt=b.read(E/'receipt.json')
 b.need(receipt['status']=='PASS_TWO_FRESH_NATIVE_EXPORTS_ONLY','native execution incomplete')
 b.need(all(x['exit']==0 and x['guard'] is None for x in receipt['steps']),'native stage failure')
 A.mkdir(exist_ok=False);c=b.load('distinct_native_census',H/'helpers/reachable_census.py');c.OUT=A
 negatives=[]
 for name,fn in [('unsupported_state',lambda:c.c.declarations('logic [63:0] silently_omitted;')),
                 ('unparsed_reg',lambda:c.c.declarations('reg [N:0] state;')),
                 ('unknown_module',lambda:c.c.structural_instances('module X(); MadeUpAlias child(); endmodule',{'X'})),
                 ('conditional_generate',lambda:c.c.structural_instances('module X(); if (1) begin Y child(); end endmodule',{'X','Y'})),
                 ('unknown_ram_ports',lambda:c.memory_geometry({'arrays':[{'name':'Memory','width':64,'depth':32}]},'module M(input wrong); reg [63:0] Memory[0:31]; endmodule'))]:
  try:fn()
  except (RuntimeError,AssertionError) as e:negatives.append({'name':name,'expected_reject':str(e)})
  else:raise RuntimeError('negative unexpectedly accepted '+name)
 rows={};actual={};profiles={}
 for mode in ['off','on']:
  d=E/mode;r=b.read(d/'receipt.json')
  for n,h in r['artifacts'].items():b.need(b.sha(n)==h,'native export changed '+n)
  actual[mode]=b.read(d/'actual-parameters.json');profiles[mode]=b.read(d/'profile.json')
  # The unchanged strict census consumes its historical receipt schema. This
  # metadata adapter binds the original new receipt and links the same RTL bytes.
  adapter=A/('input-'+mode);adapter.mkdir();(adapter/'rtl').symlink_to(d/'rtl',target_is_directory=True)
  b.save(adapter/'receipt.json',{'status':'PASS_RTL_EXPORT_ONLY','original_native_receipt_sha256':b.sha(d/'receipt.json'),
    'source_sha256':p['production_files'],'profile':{'lsu_entries':4},
    'rtl_sha256':{'rtl/'+x.name:b.sha(x) for x in sorted((d/'rtl').iterdir()) if x.is_file()}})
  rows[mode]=c.extend(adapter);rows[mode]['directory']=str(adapter);b.save(A/(mode+'-census.json'),rows[mode])
 expected=copy.deepcopy(actual['off']);expected['entryProfile']['distinctWayRelease']=True
 for row in expected['cacheConcurrency']:row['values']['distinctWayRelease']=True
 expected['experiment']='distinct-way-release-native-on';expected['canonicalOptions']=sorted(expected['canonicalOptions']+['--distinct-way-release'])
 b.need(expected==actual['on'],'unexplained actual constructor difference')
 expectedProfile=copy.deepcopy(profiles['off']);expectedProfile['profile']['distinctWayRelease']=True;expectedProfile['cache']['distinctWayRelease']=True
 b.need(expectedProfile==profiles['on'],'unexplained complete profile difference')
 comparison=c.compare(rows['off'],rows['on'],'off-on');b.save(A/'comparison.json',comparison)
 before,after=rows['off'],rows['on']
 ramdiff={key:{'before':before['reachable_ram_instances'].get(key),'after':after['reachable_ram_instances'].get(key)} for key in set(before['reachable_ram_instances'])|set(after['reachable_ram_instances']) if before['reachable_ram_instances'].get(key)!=after['reachable_ram_instances'].get(key)}
 b.save(A/'ram-differences.json',ramdiff)
 hierarchy=lambda r:{key:value['module'] for key,value in r['reachable_paths'].items()}
 issued={mode:[v for v in row['modules']['NonBlockingCoherentLineCache']['scalar_registers'] if re.fullmatch('acquireIssued_[01]',v['name'])] for mode,row in rows.items()}
 historical=b.BASE/'posted-preparation-priority-native-r1/execution/on'
 old=c.extend(historical);old['directory']=str(historical)
 oldProfile=b.read(historical/'profile.json');baseProfile=copy.deepcopy(profiles['off'])
 del baseProfile['profile']['distinctWayRelease'];del baseProfile['cache']['distinctWayRelease']
 b.need(baseProfile==oldProfile,'historical native profile differs')
 history=c.compare(old,before,'published-equivalent-off');b.save(A/'historical-off-comparison.json',history)
 result={'schema':'distinct-way-release-native-census-v1','status':'PASS_LITERAL_NATIVE_PAIR_CENSUS',
   'source_head':p['head'],'source_tree':p['tree'],'execution_receipt_sha256':b.sha(E/'receipt.json'),'pins_sha256':b.sha(H/'pins.json'),
   'source_guard_checked':True,'complete_actual_constructor_difference_only':'distinctWayRelease in entry profile and 3 cache constructors; experiment/options metadata',
   'table':{mode:{**r['production_reachable_totals'],'production_instances':r['production_module_instance_count'],'ram_instances':len(r['reachable_ram_instances']),
        'cache_scalar_reg_bits':r['modules']['NonBlockingCoherentLineCache']['scalar_reg_bits'],'home_scalar_reg_bits':r['modules']['MixedCoherentLineHome']['scalar_reg_bits'],'issued_registers':issued[mode]} for mode,r in rows.items()},
   'delta':comparison['delta'],'all_ports_equal':all(x['ports_equal'] for x in comparison['modules']),
   'hierarchy_equal':hierarchy(before)==hierarchy(after),'all_ram_geometry_ports_and_raw_helper_bytes_equal':not ramdiff,
   'changed_raw_modules':[x['module'] for x in comparison['modules'] if not x['exact_bytes_equal']],
   'historical_off':{'receipt_sha256':b.sha(historical/'receipt.json'),'exact_all_raw_modules_equal':all(x['exact_bytes_equal'] for x in history['modules']),
      'delta':history['delta'],'changed_raw_modules':[x['module'] for x in history['modules'] if not x['exact_bytes_equal']]},
   'parser_negative_controls':negatives,'limits':['Native declarations and geometry, not mapped LUT/FF/BRAM/PPA/STA.',
      'Actual cache/home runtime correctness is separately bound by focused-r2; CPU net benefit remains separate.',
      'Resource reuse flags are absent in this published-equivalent baseline and remain equivalent to OFF.']}
 b.need(result['delta']=={'scalar_reg_bits':2,'array_reg_bits':0},'unexpected native state delta')
 b.need(result['all_ports_equal'] and result['hierarchy_equal'] and not ramdiff,'unexpected native geometry/port difference')
 b.need(issued['off']==[] and sum(v['width'] for v in issued['on'])==2,'issued bits mismatch')
 b.save(A/'SUMMARY.json',result);b.guard(p)
 print(json.dumps(result,indent=2));print('SUMMARY_SHA256 '+b.sha(A/'SUMMARY.json'))
if __name__=='__main__':main()
