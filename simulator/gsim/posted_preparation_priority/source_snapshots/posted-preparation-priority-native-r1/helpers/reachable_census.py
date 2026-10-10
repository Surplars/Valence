#!/usr/bin/env python3
"""Strict native declaration/hierarchy census; no module/expression normalization."""
from pathlib import Path
import collections,difflib,hashlib,importlib.util,json,re
OUT=Path(__file__).resolve().parent;ROOT=OUT.parent/'source'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('strict_native_census',Path(__file__).with_name('lsu_capacity_census.py'));c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
def save(name,data):
 with (OUT/name).open('x') as stream:stream.write(json.dumps(data,indent=2)+'\n')
def scalar_records(text):
 rows=[]
 for high,low,body in re.findall(r'\breg\b\s*(?:\[(\d+):(\d+)\]\s*)?([^;]+);',c.strip(text)):
  width=abs(int(high)-int(low))+1 if high else 1
  for item in body.strip().split(','):
   item=item.strip()
   if re.fullmatch(r'[\w$]+',item):rows.append({'name':item,'width':width})
 return rows

def ports(text):
 header=re.match(r'\s*module\s+\w+\s*\((.*?)\);',c.strip(text),re.S);c.require(header,'header')
 out={};direction=None;width=None
 for item in header[1].split(','):
  m=re.fullmatch(r'\s*(?:(input|output|inout)\s+(?:\[(\d+):(\d+)\]\s*)?)?(\w+)\s*',item);c.require(m,'unsupported ANSI port '+item)
  if m[1]:direction=m[1];width=abs(int(m[2])-int(m[3]))+1 if m[2] else 1
  c.require(direction and width,'port lacks preceding type');out[m[4]]={'direction':direction,'width':width}
 return out

def memory_geometry(module,text):
 arrays=module['arrays']
 if not arrays:return None
 c.require(len(arrays)==1 and arrays[0]['name']=='Memory','unsupported non-helper array')
 p=ports(text);groups=collections.defaultdict(dict)
 for n,row in p.items():
  m=re.fullmatch(r'(R\d+|W\d+)_(addr|en|clk|data|mask)',n);c.require(m,'unsupported memory port '+n)
  groups[m[1]][m[2]]=row
 report=[]
 for n,fields in sorted(groups.items()):
  c.require(set(fields)=={'addr','en','clk','data'} or (n.startswith('W') and set(fields)=={'addr','en','clk','data','mask'}),'memory port fields')
  c.require(fields['addr']['direction']=='input' and fields['en']=={'direction':'input','width':1} and fields['clk']=={'direction':'input','width':1},'memory address/control direction')
  c.require(fields['data']=={'direction':'output' if n.startswith('R') else 'input','width':arrays[0]['width']},'memory data shape')
  r={'port':n,'kind':'read' if n.startswith('R') else 'write','address_bits':fields['addr']['width'],'data_bits':fields['data']['width']}
  if n.startswith('R'):
   c.require(re.search(r'assign\s+'+n+r'_data\s*=.*?Memory\[',text,re.S),'unsupported read implementation')
   r['latency']=int(bool(re.search(r'\breg\s+(?:\[\d+:\d+\]\s*)?_'+n+r'_addr_d0\b',text)))
  else:
   c.require('always @(posedge '+n+'_clk)' in text and 'Memory['+n+'_addr]' in text,'unsupported write implementation');r['latency']=1;r['mask_bits']=fields.get('mask',{}).get('width',1);c.require(r['data_bits']%r['mask_bits']==0,'mask granularity');r['mask_granularity_bits']=r['data_bits']//r['mask_bits']
  report.append(r)
 return {**arrays[0],'bits':arrays[0]['width']*arrays[0]['depth'],'ports':report}

def extend(directory):
 r=c.census(directory);texts={n:(directory/'rtl'/m['file']).read_text() for n,m in r['modules'].items()}
 for n,m in r['modules'].items():
  m['ports']=ports(texts[n]);m['scalar_registers']=scalar_records(texts[n]);c.require(sum(x['width'] for x in m['scalar_registers'])==m['scalar_reg_bits'],'scalar recompute')
  m['ram_geometry']=memory_geometry(m,texts[n]);c.require(not re.search(r'\b(?:assert|assume|cover)\s*\(|\$(?:fatal|error)\b',c.strip(texts[n])),'verification remains')
 paths={};external={}
 def walk(n,path,stack):
  c.require(n not in stack,'cycle')
  if n not in r['modules']:external[path]=n;return
  m=r['modules'][n];paths[path]={'module':n,'sha256':m['sha256'],'scalar_reg_bits':m['scalar_reg_bits'],'array_reg_bits':m['array_reg_bits']}
  for ch in m['children']:walk(ch['module'],path+'/'+ch['instance'],stack+[n])
 walk('FpgaNextSocTop','FpgaNextSocTop',[])
 r['reachable_paths']=paths;r['excluded_external_paths']=external
 r['all_definition_totals']={k:sum(m[k] for m in r['modules'].values()) for k in ['scalar_reg_bits','array_reg_bits']}
 r['production_reachable_totals']={k:sum(m[k] for m in paths.values()) for k in ['scalar_reg_bits','array_reg_bits']}
 r['production_module_instance_count']=len(paths)
 r['unreachable_definitions']=sorted(set(r['modules'])-{x['module'] for x in paths.values()})
 r['reachable_ram_instances']={p:{'module':m['module'],'helper_sha256':m['sha256'],**r['modules'][m['module']]['ram_geometry']} for p,m in paths.items() if m['array_reg_bits']}
 c.require(sum(x['bits'] for x in r['reachable_ram_instances'].values())==r['production_reachable_totals']['array_reg_bits'],'all RAM reconciles')
 return r

def compare(a,b,label):
 diffdir=OUT/('diffs-'+label);diffdir.mkdir(exist_ok=False);rows=[]
 for name in sorted(set(a['modules'])|set(b['modules'])):
  x=a['modules'].get(name);y=b['modules'].get(name)
  row={'module':name,'before_sha256':x and x['sha256'],'after_sha256':y and y['sha256'],'exact_bytes_equal':bool(x and y and x['sha256']==y['sha256']),'ports_equal':bool(x and y and x['ports']==y['ports'])}
  if not row['ports_equal']:row['ports']={'before':x and x['ports'],'after':y and y['ports']}
  if not row['exact_bytes_equal']:
   tx=(Path(a['directory'])/'rtl'/x['file']).read_text() if x else ''
   ty=(Path(b['directory'])/'rtl'/y['file']).read_text() if y else ''
   dest=diffdir/(name+'.diff');dest.write_text(''.join(difflib.unified_diff(tx.splitlines(True),ty.splitlines(True),fromfile='before/'+name,tofile='after/'+name)));row['diff']={'path':str(dest.relative_to(OUT)),'sha256':sha(dest)}
  rows.append(row)
 pathrows=[]
 for p in sorted(set(a['reachable_paths'])|set(b['reachable_paths'])):
  x=a['reachable_paths'].get(p);y=b['reachable_paths'].get(p)
  if x==y:continue
  regx={r['name']:r['width'] for r in a['modules'][x['module']]['scalar_registers']} if x else {}
  regy={r['name']:r['width'] for r in b['modules'][y['module']]['scalar_registers']} if y else {}
  regdiff=[{'name':n,'before_width':regx.get(n,0),'after_width':regy.get(n,0)} for n in sorted(set(regx)|set(regy)) if regx.get(n)!=regy.get(n)]
  row={'path':p,'before':x,'after':y,'scalar_delta':(y or {}).get('scalar_reg_bits',0)-(x or {}).get('scalar_reg_bits',0),'array_delta':(y or {}).get('array_reg_bits',0)-(x or {}).get('array_reg_bits',0),'scalar_register_differences':regdiff}
  c.require(sum(r['after_width']-r['before_width'] for r in regdiff)==row['scalar_delta'],'reg diff sum');pathrows.append(row)
 return {'before_receipt_sha256':a['receipt_sha256'],'after_receipt_sha256':b['receipt_sha256'],'normalization_rules':[],'delta':{k:b['production_reachable_totals'][k]-a['production_reachable_totals'][k] for k in ['scalar_reg_bits','array_reg_bits']},'definition_total_delta':{k:b['all_definition_totals'][k]-a['all_definition_totals'][k] for k in ['scalar_reg_bits','array_reg_bits']},'modules':rows,'reachable_path_differences':pathrows,'external_paths_equal':a['excluded_external_paths']==b['excluded_external_paths']}
