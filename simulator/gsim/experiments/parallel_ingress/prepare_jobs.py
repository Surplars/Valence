from pathlib import Path
import json,hashlib,re
import sys
assert len(sys.argv) == 3, "work directory and yosys required"
D=Path(sys.argv[1]).resolve();Y=Path(sys.argv[2]).resolve()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
s=(D/'Contract.v').read_text();mut=s.replace('module Contract(','module ObservationMutant(').replace('output helper_inputs_ok,residual_ok,all_ok','output helper_inputs_ok,residual_ok,all_ok,old_valid,new_valid,mutated_valid,mutant_ok')
mut=mut.replace('endmodule','assign old_valid = off_io_physical_request_valid;\nassign new_valid = on_io_physical_request_valid;\nassign mutated_valid = ~on_io_physical_request_valid;\nassign mutant_ok = (old_valid == mutated_valid);\nendmodule')
(D/'ObservationMutant.v').write_text(mut)
base=f'read_json {D}/residual.json\n'
jobs=[]
for name,prop in [('helper_inputs','helper_inputs_ok'),('residual','residual_ok')]:
 text=base+f'read_verilog {D}/Contract.v\nhierarchy -check -top Contract\nproc\nflatten\n'
 for p in ['helper_inputs_ok','residual_ok','all_ok']:
  if p!=prop:text+=f'delete -port Contract/w:{p}\n'
 text+=f'opt_expr\nopt_merge\nopt_clean -purge\ncheck -assert\nsat -verify -prove {prop} 1 -show {prop} -dump_json {D}/{name}.wave.json\n'
 (D/(name+'.ys')).write_text(text);jobs.append({'name':name,'expected_exit':0,'property':prop})
# Observation-chain negative, no RTL mutation: flip only the candidate physical-valid observation.
# All inputs/state fixed zero. Physical-valid itself is independent of helper result, and actual empty checked queue makes old/new zero.
ports=re.findall(r'input\s+(?:\[(\d+):0\]\s+)?(\w+)',s.split(');',1)[0]);assignment={n:0 for _,n in ports};sets=' '.join(f"-set {n} {int(w)+1 if w else 1}'h0" for w,n in ports)
text=base+f'read_verilog {D}/ObservationMutant.v\nhierarchy -check -top ObservationMutant\nproc\nflatten\n'
for p in ['helper_inputs_ok','residual_ok','all_ok']:text+=f'delete -port ObservationMutant/w:{p}\n'
text+='opt_expr\nopt_merge\nopt_clean -purge\ncheck -assert\n'+f'sat -verify -prove mutant_ok 1 {sets} -show-inputs -show old_valid -show new_valid -show mutated_valid -show mutant_ok -dump_json {D}/negative.wave.json\n'
(D/'negative.ys').write_text(text);jobs.append({'name':'negative','expected_exit':1,'property':'mutant_ok'})
(D/'NEGATIVE_ASSIGNMENT.json').write_text(json.dumps({'assignment':assignment,'scope':'Host observation valid-bit flip only, no RTL change; fixed empty state means actual physical valid0 regardless of helper symbols. Expected old0/new0/mutated1/mutant0.'},indent=2)+'\n')
files={str(p):sha(p) for p in D.iterdir() if p.is_file() and p.name not in ['PROOF_PREPARATION.json']}
files[str(Y)]=sha(Y)
(D/'PROOF_PREPARATION.json').write_text(json.dumps({'status':'PREPARED_NOT_SOLVED','tool':str(Y),'tool_sha256':sha(Y),'seconds_per_job':60,'jobs':jobs,'files':files,'scope':'Full original input/state domain, all raw outputs and complete92FF/2143state Q/D/CLK; helper equivalence decomposition has no lifecycle or stablePMP assumptions.'},indent=2)+'\n')
print(sha(D/'PROOF_PREPARATION.json'))
