"""Authoritative constructor + FIR + generated ABI geometry; padded C arrays are not capacity."""
import math,re
from contract import *
def module(text,name):
 m=re.search(r'^  (?:public )?module '+re.escape(name)+r'\s*:.*?(?=^  (?:public )?(?:module|extmodule) |\Z)',text,re.M|re.S)
 require(m is not None,'missing actual FIR module '+name);return m[0]
def verify_fir_geometry(text,p):
 r,q,l=p['core']['robEntries'],p['core']['physicalRegs'],p['core']['memoryEntries'];bits=(r-1).bit_length();countbits=r.bit_length()
 require(r in (16,32,64)and q in(48,64)and l==4 and p['core']['tagBits']==64,'unsupported actual constructor')
 ledger=module(text,'RenameRob');backend=module(text,'IntegerBackend');lsu=module(text,'ParallelLoadStoreUnit')
 for expr,body,label in [(rf'regreset head : UInt<{bits}>,',ledger,'ledger index'),(rf'regreset count : UInt<{countbits}>,',ledger,'ledger count'),(rf'regreset free : UInt<1>\[{q}\],',ledger,'physical free depth'),(rf'reg entries : [^\n]*\}}\[{r}\],',ledger,'ROB exact depth'),(rf'reg queue : [^\n]*\}}\[{r}\],',backend,'backend queue exact depth'),(rf'regreset ready : UInt<1>\[{q}\],',backend,'PRF readiness depth')]:require(re.search(expr,body),'FIR '+label+' mismatch')
 require(f'token : {{ index : UInt<{bits}>, tag : UInt<64>'in backend,'full token index/tag width mismatch')
 require(len(re.findall(r'^    inst slots_\d+ of LoadStoreUnit(?:_\d+)? ',lsu,re.M))==l,'actual LSU owner count mismatch')
 return dict(rob_entries=r,physical_regs=q,lsu_entries=l,rob_bits=bits,tag_bits=64,header_padding_does_not_define_capacity=True)
def verify_header(text,p,legacy=False):
 r,q,l=p['core']['robEntries'],p['core']['physicalRegs'],p['core']['memoryEntries']
 require(r==64 and p['core']['reconstructIssueTokenIndex'] is True and p['core']['sharedMemoryAddressState'] is True,'resource ABI requires exact joint ON ROB64')
 require('board$platform$core$core$core$backend$queue$$renamed$$token$$index' not in text,'joint ON stored queue index unexpectedly retained')
 require(re.search(re.escape('uint64_t board$platform$core$core$core$backend$queue$$renamed$$token$$tag[64];')+r' // width = 64,',text),'raw queue tags are not exactly 64 by 64 bits')
 require(re.search(re.escape('uint64_t board$platform$core$core$core$backend$storeAddress[64];')+r' // width = 64,',text),'shared store address is not exactly 64 by 64 bits')
 require('board$platform$core$core$core$backend$loadBeat' not in text and 'board$platform$core$core$core$backend$loadLanes' not in text,'joint ON duplicate load state unexpectedly retained')
 for stem,minimum in [('pending',r),('queue$$renamed$$token$$tag',r),('ready',q),('ledger$free',q)]:
  m=re.search(re.escape('board$platform$core$core$core$backend$'+stem)+r'\[(\d+)\]',text);require(m is not None and int(m[1])>=minimum,'actual generated array too short '+stem)
 for stem in ('ownerReady$ready1_','ownerReady$ready2_','storeSafeRange_'):
  indices={int(x)for x in re.findall(re.escape('board$platform$core$core$core$backend$'+stem)+r'(\d+)\s*;',text)};require(indices==set(range(r)),'actual scalar getter range differs '+stem)
 for name in ('get_lineage$$owner$$accepted$$valid','get_lineage$$owner$$drained$$valid','get_canonical$$startValid'):
  require(name+'('in text,'actual scalar ABI missing '+name)
 if not legacy:
  for name in ('RobEntries','RobBits','PhysicalRegs','LsuEntries','RobOccupancy','FreePhysical','RenameOffer0','RenameOffer1','RenameAccepted0','RenameAccepted1','RenameWritesRd0','RenameWritesRd1','RenameFresh0','RenameFresh1','RegisterEnough0','RegisterEnough1','DispatchReady','Recovering','TagExhausted'):require('get_capacity'+name+'('in text,'capacity scalar missing '+name)
 else:require((r,q,l)==(16,48,4),'legacy ABI only authorized for exact donor capacity')
 for field in read(HERE/'PASSIVE-ABI.json')['scalars']:
  require('get_'+field['name']+'('in text,'actual frontier scalar ABI missing '+field['name'])
 return dict(legacy=legacy,scalar_owner_range=r,physical_active_range=q)
def verify_actual(folder,p,legacy=False):
 f=(folder/'BoardSocGsim.fir').read_text();h=(folder/'BoardSocGsim.h').read_text();g=verify_fir_geometry(f,p);a=verify_header(h,p,legacy)
 census=load('capacity_census',ROOT/'simulator/gsim/posted_cpu/verify_model.py');c=census.verify_posted_model(f,True,rob_entries=p['core']['robEntries'])
 if p['core']['memoryProofFrontier']:
  bank=module(f,'MemoryProofFrontier');require('UInt<64>' in bank and 'UInt<32>'in bank and '[16]'in bank,'actual bank geometry/identity missing')
 else:require(not re.search(r'^  (?:public )?module MemoryProofFrontier\s*:',f,re.M),'OFF unexpectedly contains proof bank')
 v=load('capacity_dma_fir',ROOT/'simulator/gsim/posted_board_lineage/profile_check.py');structure=v.verify_fir(folder/'BoardSocGsim.fir')
 require('node _startEviction_T_4 = and(UInt<1>(0h1), UInt<1>(0h0))'in f and 'node startEviction = and(_startEviction_T_3, _startEviction_T_6)'in f,'legacy eviction alias not source-proven')
 return dict(full_profile=p,geometry=g,header=a,structure=structure,census=c,actual_parameters=read(folder/'actual-parameters.json'),fir_sha256=sha(folder/'BoardSocGsim.fir'),header_sha256=sha(folder/'BoardSocGsim.h'))
