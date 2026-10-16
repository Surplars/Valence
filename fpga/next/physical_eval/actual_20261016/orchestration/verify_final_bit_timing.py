from pathlib import Path
import json,re,sys
root=Path(sys.argv[1]);result={}
for rate,run in ((1000,root/'run-postroute-physopt-r1/reports/postroute-1000'),(100,root/'run-final-sta-100-r1'),(10,root/'run-final-sta-10-r1')):
    lines=(run/'timing_summary.rpt').read_text().splitlines()
    for i,line in enumerate(lines):
        if 'WNS(ns)'in line and'TNS(ns)'in line:
            values=next(x.split()for x in lines[i+1:i+6]if re.match(r'\s*-?\d+\.\d+',x));break
    else:raise RuntimeError(('No timing summary',rate))
    metrics={name:float(values[index])for name,index in(('WNS',0),('TNS',1),('WHS',4),('THS',5),('WPWS',8),('TPWS',9))}
    if min(metrics.values())<0:raise RuntimeError(('Actual three-speed timing violation',rate,metrics))
    result[str(rate)]=metrics
(root/'run-postroute-physopt-r1/final-three-speed-timing.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
