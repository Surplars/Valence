#!/usr/bin/env python3
"""Host-only preparation checks; no Java, firtool, GSIM or compiler invocation."""
import ast,copy,json,subprocess,tempfile
from pathlib import Path
import run_native as b
import audit_native as audit
h=b.HERE;src=b.SOURCE
for p in h.rglob('*.py'):ast.parse(p.read_text())
backend=src/'src/main/scala/core/ooo/IntegerBackend.scala';current=backend.read_text();old=subprocess.check_output(['git','show','7c5191ed205f9716bc137c09c4ad993afc7755de:src/main/scala/core/ooo/IntegerBackend.scala'],cwd=src,text=True)
start=current.index('                if (p.postedPreparationPriority) {');end=current.index('\n            } else originalMemoryMask',start)
assert current[:start]+'                Mux(originalMemoryMask.orR, originalMemoryMask, preparedStoreMask)'+current[end:]==old,'production backend differs outside narrow compile-time candidate branch'
block=current[start:end]
for required in ['postedBusy && !virtualized && originalMemoryMask.orR','allOriginalLoads && !blockPostedStart && !interruptDrain && !contextMemoryEpoch','!fpMemoryEpoch && !ledger.io.recovering','Mux(postedPreparationWindow, originalMemoryMask | preparedStoreMask, originalPreparationMask)','!originalMemoryMask(i) || (request.memory && !request.store && !request.atomic','!request.system && !request.mulDiv && request.controlFlow === ControlFlow.none']:
 assert required in block,required
for bad in ['lsu.io.start','planner.io','memoryIssued','stagedMemoryIndex','new Memory','Reg(']:assert bad not in block,bad
authority=['MemoryPreparationSelector.scala','PostedStoreMerge.scala','PostedStoreCpu.scala','ParallelLoadStoreUnit.scala','MemoryProofFrontier.scala']
unchanged={}
for n in authority:
 rel='src/main/scala/core/ooo/'+n;prior=subprocess.check_output(['git','show','7c5191ed205f9716bc137c09c4ad993afc7755de:'+rel],cwd=src);assert prior==(src/rel).read_bytes();unchanged[n]=b.sha(src/rel)
diff=subprocess.check_output(['git','diff','7c5191ed205f9716bc137c09c4ad993afc7755de','HEAD','--','src/main/scala/core/ooo/IntegerBackend.scala'],cwd=src,text=True);(h/'source-control.diff').write_text(diff)
profiles={s:b.read(h/f'expected-profile-{s}.json')for s in ['off','on']};assert b.diffs(profiles['off'],profiles['on'])==[{'path':'/core/postedPreparationPriority','off':False,'on':True},{'path':'/profile/postedPreparationPriority','off':False,'on':True}]
for p in profiles.values():
 assert (p['core']['robEntries'],p['core']['physicalRegs'],p['profile']['dataTranslationEntries'],p['core']['memoryEntries'],p['profile']['dmaLineEntries'])==(64,64,16,4,4)
 assert p['core']['memoryProofFrontier']and p['cache']['storePrefetchLruVictim']and p['profile']['postedPrefetchCoexistence']and p['core']['postedPrefetchHeadOffer']and p['core']['preparedStoreLookahead']and p['cache']['storeNextLinePrefetch']and p['cache']['storePrefetchMruInsertion']and p['cache']['prefetchCandidateCycles']==1
 assert not p['core']['translatedResponseEmptyFlow']and not p['core']['precheckedDataRequestFlow']and not p['core'].get('memoryProofFetchChain',False)
with tempfile.TemporaryDirectory(prefix='native-preparation-',dir=h)as d:
 p=Path(d)/'graph.sv';p.write_text('module Fixture(input a, output b);\n  reg q;\n  wire x = q & a;\n  assign b = x;\n  always @(posedge a) begin\n    automatic logic t = x;\n    q <= t;\n  end\nendmodule\n');g=audit.combinational_graph(p);assert g['equations']==3
 p.write_text(p.read_text().replace('endmodule','wire cycle_a = cycle_b;\nwire cycle_b = cycle_a;\nendmodule'))
 try:audit.combinational_graph(p)
 except RuntimeError as e:assert 'cycle'in str(e)
 else:raise AssertionError('cycle was accepted')
 p.write_text('module Fixture(input a); always_comb begin q = a; end endmodule')
 try:audit.combinational_graph(p)
 except RuntimeError as e:assert 'unsupported'in str(e)
 else:raise AssertionError('unsupported procedural form accepted')
report=dict(status='PASS_HOST_ONLY_SOURCE_PROFILE_AND_GRAPH_PREPARATION',production_commit=b.COMMIT,production_tree=b.TREE,backend_sha256=b.sha(backend),backend_outside_exact_candidate_branch_byte_equal_to_base=True,unchanged_authority_files=unchanged,source_diff_sha256=b.sha(h/'source-control.diff'),exact_profile_arities=[140,32,11],actual_exports_or_parameters_evaluated=False,graph_checks=['register-cut DAG accepted','automatic temporary included','injected cycle rejected','unsupported always_comb rejected'],scope='Source-only risk audit: no launched/ready/seal/PMP/ACK authority changed; actual native exports still pending.')
b.save(h/'preparation-checks.json',report);print(json.dumps(report,indent=2))
