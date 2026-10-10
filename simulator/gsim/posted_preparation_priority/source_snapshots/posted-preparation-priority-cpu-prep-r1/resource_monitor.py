"""One-second process-tree RSS samples; transient peaks can be missed."""
from pathlib import Path
def samples(root_pid):
 statuses={}
 for folder in Path('/proc').iterdir():
  if not folder.name.isdigit():continue
  try:
   raw=(folder/'status').read_text();fields=dict(line.split(':',1) for line in raw.splitlines() if ':' in line)
   row={'pid':int(folder.name),'ppid':int(fields['PPid'].strip()),'name':fields['Name'].strip(),'state':fields['State'].strip()}
   for k in ('VmRSS','VmHWM','VmSize'):
    row[k+'_KiB']=int(fields[k].split()[0]) if k in fields else None
   statuses[row['pid']]=row
  except (FileNotFoundError,ProcessLookupError,PermissionError,ValueError,KeyError):pass
 keep={root_pid};changed=True
 while changed:
  new={pid for pid,row in statuses.items() if row['ppid'] in keep};changed=not new.issubset(keep);keep|=new
 rows=[statuses[pid] for pid in sorted(keep) if pid in statuses]
 try:
  mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line)
  available=int(mem['MemAvailable'].split()[0]);total=int(mem['MemTotal'].split()[0])
 except (OSError,ValueError,KeyError):available=total=None
 return {'processes':rows,'observed_process_tree_RSS_KiB':sum(x['VmRSS_KiB'] or 0 for x in rows),'MemAvailable_KiB':available,'MemTotal_KiB':total}
