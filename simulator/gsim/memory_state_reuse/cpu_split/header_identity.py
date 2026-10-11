"""Allow only newly required contiguous subStep method declarations, never data."""
from pathlib import Path
import hashlib,re
sha=lambda b:hashlib.sha256(b).hexdigest()
def need(x,m):
 if not x:raise RuntimeError(m)
def declarations(data):
 return [(int(m[1]),m[0])for m in re.finditer(rb'^void subStep([0-9]+)\(\);\n',data,re.M)]
def verify(old_path,new_path):
 old=Path(old_path).read_bytes();new=Path(new_path).read_bytes();a=declarations(old);b=declarations(new)
 need(a and b and [x[0]for x in a]==list(range(len(a)))and [x[0]for x in b]==list(range(len(b))),'subStep declarations not exact contiguous official sequence')
 need(len(b)>=len(a)and b[:len(a)]==a,'original subStep API removed or changed')
 normalized=new
 for unused,line in b[len(a):]:
  need(normalized.count(line)==1,'added subStep declaration not unique');normalized=normalized.replace(line,b'',1)
 need(normalized==old,'header differs outside the exact added subStepN declarations')
 return {'old_sha256':sha(old),'new_sha256':sha(new),'old_substeps':len(a),'new_substeps':len(b),'removed_for_comparison':[line.decode().strip()for _,line in b[len(a):]],'all_other_header_bytes_exact':True,'state_members':len(members(old.decode()))}
def members(text):
 body=text.split('class SBoardSocGsim {\npublic:\n',1)[1].rsplit('};',1)[0];out=[]
 for line in body.splitlines():
  if not line.strip():continue
  m=re.fullmatch(r'(?:u?int(?:8|16|32|64)_t|bool|(?:unsigned )?_BitInt\([0-9]+\))\s+([^;]+);(?:\s*//.*)?',line)
  if m:
   for part in m[1].split(','):
    var=re.fullmatch(r'\s*([A-Za-z_$][A-Za-z0-9_$]*)(?:\[[0-9]+\])*\s*',part)
    if not var:
     need('('in part,'unrecognized state declaration '+line);break
    out.append(var[1])
  else:need('('in line and line.rstrip().endswith(';'),'unrecognized class line '+line)
 need(len(out)==len(set(out))and len(out)>10000,'incomplete or duplicate state inventory');return out
def layout_probe(path):
 names=members(Path(path).read_text());s='#include "BoardSocGsim.h"\n#include <cstddef>\n#include <cstdio>\nint main(){\n'
 s+='std::printf("MODEL %zu %zu\\n",sizeof(SBoardSocGsim),alignof(SBoardSocGsim));\n'
 for name in names:s+='std::printf("'+name+' %zu %zu %zu\\n",offsetof(SBoardSocGsim,'+name+'),sizeof(((SBoardSocGsim*)nullptr)->'+name+'),alignof(decltype(SBoardSocGsim::'+name+')));\n'
 return s+'return 0;}\n'
