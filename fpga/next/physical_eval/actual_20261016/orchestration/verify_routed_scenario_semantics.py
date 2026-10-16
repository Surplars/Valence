from pathlib import Path
from collections import Counter
import hashlib,json,re,sys
root=Path(sys.argv[1]);final_mode=len(sys.argv)>2 and sys.argv[2]=='final';run=root/('run-postroute-physopt-r1'if final_mode else'run-route-r1')
full=(run/('reports/postroute-1000/actual-constraints.xdc'if final_mode else'reports/routed-1000/actual-constraints.xdc')).read_text()
timing=(run/'timing-only.xdc').read_text()
commands={re.match(r'^(\w+)',line).group(1)for line in timing.splitlines()if re.match(r'^(\w+)',line)}
full_commands={re.match(r'^(\w+)',line).group(1)for line in full.splitlines()if re.match(r'^(\w+)',line)}
if [line for line in full.splitlines()if line.startswith('create_interface ')]!=['create_interface interface_ddr4_0']:
    raise RuntimeError('Unknown physical interface definition')
if full_commands-{'set_property','create_waiver','create_interface'} != commands:
    raise RuntimeError(('Full/timing command kinds differ',full_commands,commands))
if not commands <= {'set','current_instance','create_clock','create_generated_clock','set_clock_groups','set_clock_uncertainty','set_clock_latency','set_input_delay','set_output_delay','set_false_path','set_max_delay','set_min_delay','set_multicycle_path','set_bus_skew','set_case_analysis','set_disable_timing','set_max_time_borrow','set_input_jitter','set_system_jitter','set_clock_sense','set_data_check','set_max_transition','set_max_fanout','set_max_capacitance','set_load','set_driving_cell','set_input_transition','set_units','set_propagated_clock'}:
    raise RuntimeError(('Unclassified timing export command',commands))
def select(text):
    scope='';result=[]
    for line in text.splitlines():
        match=re.match(r'^(\w+)',line)
        if not match:continue
        command=match.group(1)
        if command=='current_instance':
            scope=''if line.strip()=='current_instance -quiet'else line.split(maxsplit=1)[1].strip()
        elif command in commands:result.append((scope,line.strip()))
    return result
if select(full)!=select(timing):
    raise RuntimeError(('Full/timing ordered scoped semantic difference',len(select(full)),len(select(timing))))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
receipt={'fullTimingCommandMultisetExactlyPreserved':True,'fullTimingCommandsOrderAndIpScopesExactlyPreserved':True,'onlyExcludedFullXdcCommandKinds':sorted(full_commands-commands),'timingCommandCounts':dict(Counter(re.match(r'^(\w+)',line).group(1)for line in timing.splitlines()if re.match(r'^(\w+)',line))),'fullXdcSha256':sha(run/('reports/postroute-1000/actual-constraints.xdc'if final_mode else'reports/routed-1000/actual-constraints.xdc')),'timingOnlyXdcSha256':sha(run/'timing-only.xdc'),'physicalConstraintsRetainedFromRoutedCheckpoint':True,'scenarios':{}}
for rate in (100,10):
    scene=root/(f'run-final-sta-{rate}-r1'if final_mode else f'run-route-sta-{rate}-r1');text=(scene/'scenario.xdc').read_text()
    before=timing.splitlines();after=text.splitlines()
    diff=[(a,b)for a,b in zip(before,after)if a!=b]
    if len(before)!=len(after)or len(diff)!=3 or sum(a.startswith('create_clock ')for a,b in diff)!=2 or sum(a.startswith('create_generated_clock ')for a,b in diff)!=1:
        raise RuntimeError(('Scene difference not exact three media clocks',rate,diff))
    receipt['scenarios'][str(rate)]={'sha256':sha(scene/'scenario.xdc'),'changedCommands':diff}
(run/'scenario-semantics-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
