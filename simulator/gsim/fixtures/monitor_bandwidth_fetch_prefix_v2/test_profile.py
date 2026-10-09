#!/usr/bin/env python3
"""Targeted fixed-history / one-prefix profile checks; no model execution."""
import copy
import sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parents[1])]
import compare as c
import cpu_retire_prefix_board as model
from prepare import require
profile=dict(dma_line_transfers=True,dma_line_entries=4,dma_line_yield_cycles=0,lsu_entries=4,fetch_previous_packet=True)
off=model.expected_model_plan(1,load_order_older_retire=False,**profile)
on=model.expected_model_plan(1,load_order_older_retire=True,**profile)
c.pair_plan(off,on)
negative=0
def reject(fn):
    global negative
    try:fn()
    except RuntimeError:negative+=1;return
    raise RuntimeError('invalid prefix/history profile accepted')
for name,value in [('fetch_previous_packet',False),('fetch_previous_packet',1),('parameters',off['parameters'][:-1]),('passive_probes',False)]:
    bad=copy.deepcopy(on);bad[name]=value;reject(lambda:c.pair_plan(off,bad))
for name,value in [('fetch_previous_packet',False),('fetch_previous_packet',1),('parameters',off['parameters']+['--load-order-older-retire'])]:
    bad=copy.deepcopy(off);bad[name]=value;reject(lambda:c.pair_plan(bad,on))
for wrong in (0,1,'true',None):
    reject(lambda wrong=wrong:model.expected_model_plan(1,load_order_older_retire=wrong,**profile))
for flag in (0,1):
    flags=c.driver.compile_flags(Path('/model'),Path('/repo'),Path('/out'),flag)
    require('-DFETCH_PREVIOUS_PACKET=1' in flags and '-DOLDER_PREFIX_ENABLED='+str(flag) in flags,'fixed history / prefix compile macro drift')
print(f'PASS_FETCH_PREFIX_PROFILE_HOST negatives={negative} fixed_history=1 only_prefix_differs=1')
