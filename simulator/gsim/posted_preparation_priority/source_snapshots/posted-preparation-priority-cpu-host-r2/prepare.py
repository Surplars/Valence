#!/usr/bin/env python3
"""Read/hash/parse-only preparation audit. Does not invoke compiler, linker, model or DUT."""
import ast
from contract import *
from run import PRESERVED,DONOR

def inspect():
 src=source();g=guest()
 for side in PROFILES:profile(expected_profile(side),side)
 pair_profiles(expected_profile('off'),expected_profile('on'))
 flags=read(HERE/'canonical-flags.json');require(set(flags['on'])-set(flags['off'])=={'--posted-preparation-priority'} and set(flags['off'])<=set(flags['on']),'option treatment delta')
 for n in PRESERVED:require(sha(HERE/n)==sha(DONOR/n),'preserved independent oracle changed '+n)
 for p in HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
 old=(DONOR/'host.cpp').read_text();new=(HERE/'host.cpp').read_text()
 for start,end in [('static void buffers(','struct Observed'),('static uint64_t expectedWord(uint64_t n)','int main(')]:require(old[old.index(start):old.index(end)]==new[new.index(start):new.index(end)],'independent full-word/row oracle changed')
 for path in ('simulator/gsim/harness/board_boot.cpp','simulator/gsim/harness/board_ddr_multiid.h','simulator/gsim/harness/rv64gc_board.cpp','fpga/firmware/rv64gc_smoke.S','fpga/firmware/sample_app.ld'):require(sha(ROOT/path)==sha(DONOR/'source'/path),'immutable driver/smoke source changed '+path)
 abi=read(HERE/'PASSIVE-ABI.json');host=(HERE/'proof_observer.hpp').read_text()
 for f in abi['scalars']:
  short=f['name'][2:];pattern=(('if(s.v['+f['guard'][2:]+'])')if f['guard']else'')+'s.v['+short+']=d.get_'+f['name']+'();'
  require(pattern in host,'new observer missing exact valid-before-payload read '+short)
 require(len(abi['scalars'])==len({f['name']for f in abi['scalars']}),'duplicate passive ABI scalar')
 smoke=(ROOT/'simulator/gsim/harness/rv64gc_board.cpp').read_text()
 require('get_io$$commit0Pc()'in smoke and 'get_io$$commit1Pc()'in smoke and 'token'not in smoke.lower(),'smoke independent scalar PC ABI')
 return dict(status='SOURCE_ONLY_PREPARED_NOT_COMPILED_NOT_QUALIFIED',source_manifest_sha256=sha(HERE/'SELECTED-SOURCE.json'),production_head=src['head'],guest=g,typed_core_fields=140,profiles=['off','on'],capacity=[64,64,4],proof_rows=16,passive_scalars=len(abi['scalars']),Python_AST='PARSED_ONLY',host_logic_controls='PENDING_NOT_EXECUTED',actual_header_Cpp_syntax='PENDING_NEW_OFF_ON_HEADERS',Scala_wrapper_compile='PENDING',model_receipts={'off':None,'on':None},focused_aggregate=None,rv64gc_short={'off':None,'on':None},runtime={'case19_off':None,'case19_on':None,'case21_off':None,'case21_on':None},heavy_started=False,DUT_executed=False)
if __name__=='__main__':print(json.dumps(inspect(),indent=2))
