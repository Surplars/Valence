from pathlib import Path
import re,json,hashlib,difflib
R=Path(__file__).resolve().parent.parent
H=lambda s:hashlib.sha256(s.encode()).hexdigest()
rows=[];diff=[]
strip=lambda s:re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',lambda m:' '*len(m.group(0)),s,flags=re.S)
for p in sorted((R/'rtl-on').glob('*.sv')):
 original=p.read_text();converted=(R/'simulation-rtl'/p.name).read_text();clean=strip(original)
 groups=list(re.finditer(r'(?:\s*automatic logic\s+[^;]+;)+',original))
 if not groups:
  assert original==converted,p.name;continue
 assert not re.search(r'\b(task|function|fork|join|wait)\b',clean),p.name+' unsupported reentrant/delayed context'
 # Scope tokens from the actual generated native input, independent of regex conversion.
 stack=[];blocks=[]
 for token in re.finditer(r'\b(begin|end)\b',clean):
  if token.group()=='begin':stack.append(token.start())
  else:
   assert stack,p.name+' unbalanced end';start=stack.pop();blocks.append((start,token.end()))
 assert not stack,p.name+' unbalanced begin'
 replacements=[]
 for n,g in enumerate(groups):
  containers=[b for b in blocks if b[0]<g.start() and g.end()<b[1]];assert containers
  lo,hi=min(containers,key=lambda b:b[1]-b[0]);outer_lo,outer_hi=max(containers,key=lambda b:b[1]-b[0])
  assert re.search(r'always\s*@[^;]+$',clean[max(0,outer_lo-300):outer_lo]),p.name+' declaration outside an always block'
  body=clean[g.end():hi]
  declarations=[];initializers=[];vars=[]
  for d in re.findall(r'automatic logic\s+([^;]+);',g.group()):
   lhs,*right=d.split('=',1);name=re.search(r'(\w+)\s*$',lhs).group(1);vars.append(name)
   declarations.append('logic '+lhs.strip()+';')
   if right:
    rhs=right[0].strip();assert not re.search(r'\b'+name+r'\b',strip(rhs)),(p.name,name,'self initializer')
    initializers.append(name+' = '+rhs+';')
  witnesses=[];assigned=set()
  for d in re.findall(r'automatic logic\s+([^;]+);',g.group()):
   lhs,*right=d.split('=',1);name=re.search(r'(\w+)\s*$',lhs).group(1)
   if right:
    used=set(re.findall(r'\b\w+\b',strip(right[0])))&set(vars)
    assert used<=assigned,(p.name,name,'initializer depends on uninitialized peer',used-assigned)
    assigned.add(name);witnesses.append({'variable':name,'kind':'ordered per-entry initializer','rhs_sha256':H(right[0].strip())})
   else:
    use=re.search(r'\b'+name+r'\b',body);assert use,(p.name,name,'unused temp')
    after=body[use.end():];assert re.match(r'\s*=\s*[^=]',after),(p.name,name,'first occurrence not blocking assignment')
    prefix=body[:use.start()]
    assert not re.search(r'\b(if|else|case|begin|end|for|while|repeat)\b',prefix),(p.name,name,'first assignment conditional')
    rhs=after.split(';',1)[0].split('=',1)[1]
    assert not re.search(r'\b'+name+r'\b',rhs),(p.name,name,'self before assign')
    witnesses.append({'variable':name,'kind':'unconditional first blocking assignment before all reads','first_assignment_line':original[:g.end()+use.start()].count('\n')+1,'rhs_sha256':H(rhs.strip())})
  # Expected replacement is spelled independently; the executable stream keeps
  # every initializer in declaration order before the unchanged original body.
  replacement='\n      '+'\n      '.join(declarations+initializers)+'\n      '
  replacements.append((g.start(),g.end(),replacement))
  rows.append({'file':p.name,'group':n,'declaration_line':original[:g.start()].count('\n')+1,'native_file_sha256':H(original),'simulation_file_sha256':H(converted),'enclosing_native_block_sha256':H(original[lo:hi]),'native_declarations_sha256':H(g.group()),'converted_declarations_and_initializers_sha256':H(replacement),'scope':'same enclosing begin/end in non-reentrant always block','variables':witnesses})
 expected=original
 for a,b,new in reversed(replacements):expected=expected[:a]+new+expected[b:]
 assert expected==converted,p.name+' non-declaration byte change'
 diff.extend(difflib.unified_diff(original.splitlines(True),converted.splitlines(True),fromfile='rtl-on/'+p.name,tofile='simulation-rtl/'+p.name))
report={'status':'PASS_BOUNDED_NATIVE_TEMPORARY_LIFETIME_AUDIT','groups':len(rows),'variables':sum(len(r['variables']) for r in rows),'only_scope':'generated full-MAC native procedural temporaries; not a general SystemVerilog transformation proof','rows':rows,'no_task_function_fork_wait':True,'scope_and_initializer_order_preserved':True,'first_assignment_dominates_each_noninitialized_temporary_read':True}
(R/'tests/simulation-bridge-audit.json').write_text(json.dumps(report,indent=2)+'\n')
(R/'tests/simulation-bridge.diff').write_text(''.join(diff))
print(report['status'],'groups',report['groups'],'variables',report['variables'])
