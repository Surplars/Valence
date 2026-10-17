"""Mechanical public top-level API only; no model state access or behavior model."""
import pathlib,re,json,hashlib
root=pathlib.Path(__file__).resolve().parent.parent
header=root/'model-1-1/FullLineHomeGsim.h'
s=header.read_text()
sets=re.findall(r'^void set_(reset|io\$\$[A-Za-z0-9_$]+)\((\w+) val\);$',s,re.M)
gets=re.findall(r'^(uint\d+_t|unsigned _BitInt\(512\)) get_(io\$\$[A-Za-z0-9_$]+)\(\);$',s,re.M)
def name(x):return x[4:].replace('$$','.') if x.startswith('io$$') else x
assert len(sets)==len(re.findall(r'^void set_(?:reset|io\$\$[^ (]+)\(',s,re.M)), 'omitted public input'
assert len(gets)==len(re.findall(r'^.* get_io\$\$[^ (]+\(\);$',s,re.M)), 'omitted public output'
input_names={name(n) for n,t in sets}
output_names={name(n) for t,n in gets}
required_inputs={'reset','request.valid','response.ready','release.valid','releaseAck.ready','drain','holdA','holdC','holdD','holdE','holdLine','deniedD','corruptD','wrongOpcodeD','badCapD'}
required_inputs.update('request.bits.'+n for n in ('address','tag','grow','permissionOnly'))
required_inputs.update('release.bits.'+n for n in ('opcode','param','size','source','address','data','corrupt'))
required_inputs.update('axi.'+n+'.ready' for n in ('ar','aw','w'))
required_inputs.update(('axi.r.valid','axi.b.valid'))
required_inputs.update('axi.r.bits.'+n for n in ('id','data','resp','last'))
required_inputs.update('axi.b.bits.'+n for n in ('id','resp'))
assert required_inputs<=input_names,required_inputs-input_names
required_outputs={'request.ready','release.ready','response.valid','releaseAck.valid','drained','axi.b.ready','axi.r.ready'}
for n in ('ar','aw'):
 required_outputs.add('axi.'+n+'.valid')
 required_outputs.update('axi.'+n+'.bits.'+f for f in ('id','addr','len','size','burst'))
required_outputs.add('axi.w.valid');required_outputs.update('axi.w.bits.'+f for f in ('data','strb','last'))
for n in ('a','c','d','e','line'):
 required_outputs.update((n+'.valid',n+'Offered'))
for n in ('d','releaseAck'):
 required_outputs.update(n+'.bits.'+f for f in ('opcode','param','size','source','sink','denied','data','corrupt'))
for n in ('a','c'):
 required_outputs.update(n+'.bits.'+f for f in ('opcode','param','size','source','address','data','corrupt'))
required_outputs.update('line.bits.'+f for f in ('source','sink','cap','denied','corrupt','data'))
required_outputs.update('response.bits.'+f for f in ('tag','hasData','data','cap','error'))
required_outputs.update(('e.bits.sink','read.valid','read.bits.address'))
assert required_outputs<=output_names,required_outputs-output_names
setlines=[' setters.emplace("'+name(n)+'", [&](uint64_t v){ d.set_'+n+'(v); });' for n,t in sets]
getlines=[]
for typ,n in gets:
 if '512' in typ:
  for i in range(8):getlines.append(' std::cout << ",\\"'+name(n)+'.word'+str(i)+'\\":" << uint64_t(d.get_'+n+'() >> '+str(i*64)+');')
 else:getlines.append(' std::cout << ",\\"'+name(n)+'\\":" << uint64_t(d.get_'+n+'());')
source='''#include "FullLineHomeGsim.h"
#include <functional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
int main(){try{
 SFullLineHomeGsim d;
 std::unordered_map<std::string,std::function<void(uint64_t)>> setters;
SETTERS
 for(auto& [name,set]:setters){(void)name;set(0);}
 std::string line;unsigned cycles=0;
 while(std::getline(std::cin,line)){
  if(line=="quit")break;
  if(++cycles>20000)throw std::runtime_error("B0 driver cycle limit");
  std::istringstream in(line);std::string item;
  while(in>>item){auto eq=item.find('=');if(eq==std::string::npos)throw std::runtime_error("malformed input");
   auto n=item.substr(0,eq);if(!setters.count(n))throw std::runtime_error("unknown input "+n);
   size_t used=0;auto val=item.substr(eq+1);auto v=std::stoull(val,&used,0);
   if(used!=val.size())throw std::runtime_error("trailing input");setters.at(n)(v);
  }
  // Exactly one GSIM edge: promotes prior NEXT, evaluates current outputs,
  // and computes new NEXT. Returned pins describe this logical pre-edge fire.
  d.step();std::cout<<"{\\"cycle\\":"<<cycles;
GETTERS
  std::cout<<"}\\n"<<std::flush;
 }
 return 0;
}catch(const std::exception& e){std::cerr<<"B0_DRIVER_FAIL "<<e.what()<<"\\n";return 1;}}
'''.replace('SETTERS','\n'.join(setlines)).replace('GETTERS','\n'.join(getlines))
(root/'host/driver.cpp').write_text(source)
(root/'host/API.json').write_text(json.dumps({'header_sha256':hashlib.sha256(header.read_bytes()).hexdigest(),'inputs':[name(n) for n,t in sets],'outputs':[(name(n),t) for t,n in gets]},indent=2)+'\n')
