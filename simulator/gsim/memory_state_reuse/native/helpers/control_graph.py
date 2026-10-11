import re
from run_native import require, sha

def combinational_graph(path):
 text=path.read_text();body=re.sub(r'//[^\n]*','',re.sub(r'/\*.*?\*/','',text,flags=re.S))
 require(not re.search(r'\balways_(?:comb|latch)\b|always\s*@\s*\*',body),'unsupported combinational procedural block')
 regs=set()
 for high,low,decl in re.findall(r'\breg\b\s*(?:\[(\d+):(\d+)\]\s*)?([^;]+);',body):
  for item in decl.split(','):
   m=re.match(r'\s*([\w$]+)',item);require(m is not None,'bad register');regs.add(m[1])
 eq={}
 for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_$]*)(?:\s*\[[^;=\]]+\])*\s*=(?!=)\s*([^;]+);',body,re.S):
  name,expr=m.groups()
  if name not in regs:eq.setdefault(name,[]).append(expr)
 # Add the actual planner input expression to the dependency graph. Child outputs
 # remain explicit leaves; normal firtool separately checks the whole design.
 planner=re.search(r'\bMemoryPreparationSelector\s+planner\s*\(',body)
 if planner:
  start=body.index('.io_eligible',planner.end());p=body.index('(',start)+1;depth=1;q=p
  while depth:
   depth+=(body[q]=='(')-(body[q]==')');q+=1
  eq['planner::eligible']=[body[p:q-1]]
 deps={n:sorted(set(t for expr in exprs for t in re.findall(r'\b[A-Za-z_][A-Za-z0-9_$]*\b',expr)))for n,exprs in eq.items()};state={};cycles=[]
 def visit(n,stack):
  if n in regs or n not in deps:return
  if state.get(n)==1:cycles.append(stack[stack.index(n):]+[n]);return
  if state.get(n)==2:return
  state[n]=1
  for d in deps[n]:visit(d,stack+[n])
  state[n]=2
 for n in deps:visit(n,[])
 require(not cycles,'local combinational cycle found')
 def closure(n,seen=None):
  seen=set()if seen is None else seen
  if n in seen:return seen
  seen.add(n)
  if n not in regs:
   for ch in deps.get(n,[]):closure(ch,seen)
  return seen
 cone=closure('planner::eligible')if planner else set()
 return dict(status='PASS_BOUNDED_WIRE_AND_AUTOMATIC_TEMPORARY_GRAPH_ACYCLIC',module_sha256=sha(path),equations=len(eq),register_cutpoints=sorted(regs),all_equation_dependencies=deps,cycles=cycles,planner_eligible_expression=eq.get('planner::eligible'),planner_eligible_cone=sorted(cone),planner_eligible_register_cutpoints=sorted(cone&regs),planner_eligible_leaf_inputs=sorted(n for n in cone if n not in regs and n not in deps),limits=['Bounded intra-module graph; child outputs are leaves, registers cut cycles.','Normal firtool checks whole lowered design for combinational loops. Neither check is formal equivalence or STA.'])
