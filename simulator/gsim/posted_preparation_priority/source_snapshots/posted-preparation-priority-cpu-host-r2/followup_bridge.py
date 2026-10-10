"""Same-host follow-ups require this candidate's complete measured case19 gain."""
from contract import read,sha,require,exact
from pathlib import Path

def verify(path,current,pins_sha,case):
 import pair
 g=pair.verify(path)
 require(g['status']=='PASS_CASE19_NET_GAIN'and g['case']==19 and case in g['permitted_followup_cases']and case in(21,18,6,0),'new posted-preparation-priority actual case19 net gain required')
 require(g['pins_sha256']==pins_sha and exact(read(g['pins_path']),current),'followup source/host/model/guest pins changed')
 return dict(path=str(Path(path).resolve()),sha256=sha(path),verification='PASS_SAME_PINS_FULL_NEW_CASE19_CLOSURE',new_case_execution_required=True,prior_variant_gain_inherited=False)
