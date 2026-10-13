from pathlib import Path
import re,json,hashlib
R=Path(__file__).resolve().parent.parent; dst=R/'simulation-rtl';dst.mkdir(exist_ok=True)
changes={}
for p in (R/'rtl-on').glob('*.sv'):
 s=p.read_text()
 def convert(m):
  declarations=[]; assignments=[]
  for decl in re.findall(r'automatic logic\s+([^;]+);',m.group(0)):
   if '=' in decl:
    lhs,rhs=decl.split('=',1);name=re.search(r'(\w+)\s*$',lhs).group(1)
    declarations.append('logic '+lhs.strip()+';');assignments.append(name+' = '+rhs.strip()+';')
   else:declarations.append('logic '+decl+';')
  return '\n      '+'\n      '.join(declarations+assignments)+'\n      '
 n=re.sub(r'(?:\s*automatic logic\s+[^;]+;)+',convert,s);(dst/p.name).write_text(n)
 if n!=s:changes[p.name]=s.count('automatic logic')
(R/'tests/simulation-adaptations.json').write_text(json.dumps({'only_change':'automatic logic block temporaries -> static logic declarations and per-entry assignment (including initializers) for Icarus; no expressions or timing changes','files':changes},indent=2)+'\n')
s=(R/'rtl-on/TriSpeedManagedGmac.sv').read_text().split(');',1)[0].split('(',1)[1]
ports=[];direct=None;width=''
for part in s.split(','):
 part=' '.join(part.split());m=re.match(r'(input|output)\s*(\[[^]]+\])?\s*(\w+)',part)
 if m:direct,width,name=m.groups();width=width or ''
 else:name=part
 ports.append((direct,width,name))
decl='\n'.join(('reg' if d=='input' else 'wire')+' '+w+' '+n+(' = 0;' if d=='input' else ';') for d,w,n in ports)
conn=',\n'.join('.'+n+'('+n+')' for d,w,n in ports)
(R/'tests/mac_ports.svh').write_text(decl+'\nTriSpeedManagedGmac dut(\n'+conn+'\n);\n')
