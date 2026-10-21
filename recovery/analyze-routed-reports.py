"""Read saved native reports; never launch or mutate a Vivado design."""
from pathlib import Path
import argparse, hashlib, json, re

p = argparse.ArgumentParser()
p.add_argument('directory', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executed-constraints-commit', help='Explicit override only for a documented historical receipt mismatch')
a = p.parse_args()
root = a.directory
text = (root/'diagnostic-timing.rpt').read_text(errors='replace')
lines = text.splitlines()
metrics = ['WNS(ns)', 'TNS(ns)', 'TNS Failing Endpoints', 'TNS Total Endpoints',
           'WHS(ns)', 'THS(ns)', 'THS Failing Endpoints', 'THS Total Endpoints']
pulse = ['WPWS(ns)', 'TPWS(ns)', 'TPWS Failing Endpoints', 'TPWS Total Endpoints']

def table(section, names, numeric):
    start = next(i for i, s in enumerate(lines) if s.strip() == '| '+section)
    h = next(i for i in range(start+2, len(lines)) if all(x in lines[i] for x in names+numeric))
    positions = [lines[h].index(k) for k in names] + [lines[h].index(numeric[0])]
    result = []
    for s in lines[h+2:]:
        if not s.strip(): break
        m = re.search(r'(?<!\S)[+-]?\d+(?:\.\d+)?(?=\s|$)', s)
        if not m: raise ValueError('Unknown timing row: '+s)
        row = {k: s[b:e].strip() for k,b,e in zip(names, positions, positions[1:])}
        values = list(map(float, s[m.start():].split()))
        row.update(dict.fromkeys(numeric))
        if len(values) == len(numeric): keys = numeric
        elif section == 'Intra Clock Table' and len(values) == 4: keys = pulse
        elif len(values) == 4: keys = metrics[:4]
        else: raise ValueError('Unexpected timing columns: '+s)
        row.update(zip(keys, values)); result.append(row)
    return result

intra = table('Intra Clock Table', ['Clock'], metrics+pulse)
inter = table('Inter Clock Table', ['From Clock','To Clock'], metrics)
other = table('Other Path Groups Table', ['Path Group','From Clock','To Clock'], metrics)
paths = []
for name in ['diagnostic-timing.rpt','diagnostic-cpu-setup.rpt','diagnostic-fabric-setup.rpt',
             'diagnostic-uart-setup.rpt','diagnostic-cpu-hold.rpt','diagnostic-fabric-hold.rpt']:
    body = (root/name).read_text(errors='replace')
    matches = list(re.finditer(r'Slack \((?:VIOLATED|MET)\)\s*:\s*([+-]?\d+\.\d+)ns', body))
    for j,m in enumerate(matches):
        block = body[m.start():matches[j+1].start() if j+1<len(matches) else len(body)]
        row = {'report':name, 'slack_ns':float(m[1])}
        for key in ['Source','Destination','Path Group','Path Type','Requirement','Data Path Delay','Logic Levels']:
            z = re.search(r'^\s*'+re.escape(key)+r':\s*(.+)$',block,re.M)
            row[key] = z[1].strip() if z else None
        paths.append(row)

h = next(i for i,s in enumerate(lines) if s.lstrip().startswith('WNS(ns)'))
global_metrics = dict(zip(['WNS','TNS','setup_failing_endpoints','setup_total_endpoints',
    'WHS','THS','hold_failing_endpoints','hold_total_endpoints','WPWS','TPWS',
    'pulse_failing_endpoints','pulse_total_endpoints'], map(float,lines[h+2].split())))
files = [f for f in root.iterdir() if f.is_file() and (f.suffix in ('.rpt','.dcp','.xdc')
         or f.name.endswith('inputs.json') or f.name=='implementation-console.log')]
hashes = {f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in files}
inputs = json.loads((root/'implementation-inputs.json').read_text(encoding='utf-8-sig'))
route_text = (root/'diagnostic-route.rpt').read_text()
fully_routed = int(re.search(r'# of fully routed nets\.+\s*:\s*(\d+)', route_text)[1])
route_errors = int(re.search(r'# of nets with routing errors\.+\s*:\s*(\d+)', route_text)[1])
resources = {}
for line in (root/'diagnostic-utilization.rpt').read_text().splitlines():
    fields = [x.strip() for x in line.split('|')[1:-1]]
    if fields and fields[0] in ('CLB LUTs', 'CLB Registers', 'Block RAM Tile', 'URAM', 'DSPs', 'Bonded IOB'):
        value = dict(used=float(fields[1]), available=float(fields[-2]), percent=float(fields[-1]))
        if fields[0] in resources and resources[fields[0]] != value:
            raise ValueError('Ambiguous utilization row: '+line)
        resources[fields[0]] = value
if len(resources) != 6: raise ValueError('Incomplete utilization report')
result = {'global_ns':global_metrics,'intra_clock':intra,'inter_clock':inter,'other_groups':other,
    'detailed_paths':paths,'files':hashes,
    'native_exit':json.loads((root/'implementation-exit.json').read_text(encoding='utf-8-sig')),
    'source_commit':inputs['rtl_source_commit'],
    'executed_constraints_commit':a.executed_constraints_commit or inputs['preparation_commit'],
    'recorded_preparation_commit':inputs['preparation_commit'],
    'profile_sha256':inputs['profile_sha256'],
    'route_fully_routed_nets':fully_routed,'route_errors':route_errors,'resources':resources,
    'final_signoff':False,'bitstream_generated':False}
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('GLOBAL',global_metrics)
print('ROUTED_DCP',hashes['routed-diagnostic-unqualified.dcp'])
for title, rows in [('INTRA',intra),('INTER',inter),('OTHER',other)]:
    for row in rows:
        if row['WNS(ns)'] is not None and row['WNS(ns)']<0: print(title,json.dumps(row))
worst = [r for r in paths if r['report']=='diagnostic-timing.rpt' and r['Path Type'] and 'Min' not in r['Path Type']]
for row in sorted(worst,key=lambda r:r['slack_ns'])[:7]: print('PATH',json.dumps(row))
