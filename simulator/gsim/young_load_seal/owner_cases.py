#!/usr/bin/env python3
"""Bounded existing owner oracle plus explicit no-intent-seal progress checks."""
from pathlib import Path
import argparse, json, sys
p=argparse.ArgumentParser(allow_abbrev=False)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--executable',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();sys.path.insert(0,str(a.source/'simulator/gsim/posted_merge_rebuild'))
from fixture import Scenario, positive, negative, require
out=a.output;out.mkdir(exist_ok=False)
reports=positive(a.executable,out)
# A held backend instruction need not seal an accepted owner to make progress.
s=Scenario(a.executable,out,'unsealed-owner-progress')
first=s.authored(0x8000000000000001,value=0x1122334455667788)
s.accept(first);s.finish(first);reports.append(s.close())
# Real head/system intent seals joining but leaves all old owner duties live.
s=Scenario(a.executable,out,'sticky-seal-preserves-owner-progress')
first=s.authored(0x8000000000000001,value=0x1122334455667788)
s.accept(first);s.clock(seal=1);s.clock()
second=s.authored(0x8000000000000002,address=4168,value=0x99aabbccddeeff00,ticket=1)
query=s.payload(second,new=False);query['enq.valid']=0;s.pending=None
r=s.clock(**query);require(not r['canJoin'],'sticky head/system seal reopened')
s.finish(first);reports.append(s.close())
# Refill VALID itself excludes an otherwise legal same-line member on that edge.
s=Scenario(a.executable,out,'refill-offer-excludes-overlay')
first=s.authored(0x8000000000000001,value=0x1122334455667788)
s.accept(first);s.ack(first);s.acquire(first)
second=s.authored(0x8000000000000002,address=4168,value=0x99aabbccddeeff00,ticket=1)
query=s.payload(second,new=False);query['enq.valid']=0;s.pending=None
r=s.clock(**{**query,**s.fill_payload(first)})
require(not r['canJoin'] and r['refillReady'],'refill offer admitted overlay or blocked reserved fill')
s.consume('installValid','installReady');s.consume('drained.valid','drainReady');s.consume('released.valid','releaseReady')
reports.append(s.close())
controls=[negative(a.executable,out,n) for n in ['bad-ack','stale-refill','wrong-wb-ticket']]
result={'status':'PASS_POSTED_OWNER_RESPONSIBILITY_COMPONENT','scope':'environmental owner component only, no CPU/cache/home execution claim','cases':reports,'negative_controls':controls}
(out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
