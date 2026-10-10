#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,subprocess,re
B=Path(__file__).resolve().parent;R=B.parent;S=R/'posted-preparation-priority-implementation-r1/source';O=B/'generic-off-bridge-r2';O.mkdir(exist_ok=False)
BASE='7c5191ed205f9716bc137c09c4ad993afc7755de';CAND='aa37b6a00666ee9be4284ea1793cd376c0775344';OLD='527a3ebe9b77a33656f12666b9bd4315bd77ec71';FETCH='1b33d35a057a2685a12172f9b2e20c0b907080c5'
def git(*a):return subprocess.check_output(['git',*a],cwd=S,text=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(Path(p).resolve()),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_text())
def source(head,name):
 s=git('show',head+':src/main/scala/core/ooo/'+name);p=O/(head[:8]+'-'+name);p.write_text(s);return s,p
oldtree=git('rev-parse',OLD+':src/main').strip();basetree=git('rev-parse',BASE+':src/main').strip();assert oldtree==basetree=='e7293a0d02bca43cbb860b20c137f1e244631517'
a,ap=source(BASE,'IntegerBackend.scala');b,bp=source(CAND,'IntegerBackend.scala')
start='                if (p.postedPreparationPriority) {\n';end='                } else Mux(originalMemoryMask.orR, originalMemoryMask, preparedStoreMask)\n'
assert b.count(start)==b.count(end)==1
lo=b.index(start);hi=b.index(end,lo)+len(end)
folded=b[:lo]+'                Mux(originalMemoryMask.orR, originalMemoryMask, preparedStoreMask)\n'+b[hi:]
assert folded==a,'candidate OFF elaboration branch differs from baseline entire backend'
(O/'selected-off-IntegerBackend.scala').write_text(folded)
fo,fp=source(OLD,'MemoryProofFrontier.scala');fn,np=source(FETCH,'MemoryProofFrontier.scala')
first='''    // Only the opt-in path adds mask gating; OFF retains the original elaboration path.
    val fetchChainMask = if (p.memoryProofFetchChain)
        Some(candidateMask & ~ownerBit(tokens(candidateRow).index)) else None
    val candidateIndex = oldest(if (p.memoryProofFetchChain)
        Mux(scanState === fetch, fetchChainMask.get, candidateMask) else candidateMask)
'''
assert fn.count(first)==1;fold=fn.replace(first,'    val candidateIndex = oldest(candidateMask)\n')
block='''    // Forward combinational predicates keep the original final cancellation/reset logic
    // and declaration order untouched. Neither option elaborates any hardware when OFF.
    val fetchChainCancel = if (p.memoryProofFetchChain) Some(Wire(Bool())) else None
    val fetchChainRoundReset = if (p.memoryProofFetchChain) Some(Wire(Bool())) else None
    if (p.memoryProofFetchChain) {
        // Keep the current payload read/capture intact; only register the next directory
        // row for the following FETCH. A prior reset may have erased the failed owner's bit.
        when(candidateRead && !selectedRead && queryMayRun && live(candidateRow) &&
            !readPayload.write && knownSetConflict && !fetchChainCancel.get &&
            !fetchChainRoundReset.get && fetchChainMask.get.orR) {
            candidateRow := directory(candidateIndex)
            scanState := fetch
            scanAttempted := scanAttempted | ownerBit(readProof.token.index) | ownerBit(candidateIndex)
        }
    }
'''
assert fold.count(block)==1;fold=fold.replace(block,'')
for block in ['''    if (p.memoryProofFetchChain) {
        fetchChainCancel.get := losesAllowed || io.flushQueries || !io.precheck.stable ||
            (consumeRows.asUInt.orR && !io.frontierAccepted)
    }
''','''    if (p.memoryProofFetchChain) {
        fetchChainRoundReset.get := positiveResult || removedRows.orR || io.consume.valid ||
            oldLineMask =/= VecInit(io.liveLines.map(_.valid)).asUInt ||
            !(positive & io.pending & io.ordinary & ~io.stores & ~scanAttempted).orR
    }
''']:
 assert fold.count(block)==1;fold=fold.replace(block,'')
assert fold==fo,'fetch-chain OFF elaboration branch differs from original frontier body'
(O/'selected-fetch-off-MemoryProofFrontier.scala').write_text(fold)
native=R/'posted-preparation-priority-native-r1';historical=R/'frontier-fetch-chain-native-r1'
after=read(native/'execution/off/receipt.json');before=read(historical/'execution/off/receipt.json');cmp=read(native/'analysis/historical-baseline-comparison.json')
assert after['git_head']==CAND and before['git_head']==FETCH
assert cmp['after_receipt_sha256']==sha(native/'execution/off/receipt.json') and cmp['before_receipt_sha256']==sha(historical/'execution/off/receipt.json')
assert after['rtl_sha256']==before['rtl_sha256'] and len([x for x in after['rtl_sha256']if x.endswith('.sv')])==274
assert len(cmp['modules'])==274 and all(x['exact_bytes_equal'] and x['ports_equal']for x in cmp['modules']) and cmp['normalization_rules']==[] and cmp['reachable_path_differences']==[] and cmp['external_paths_equal']
assert all(v==0 for v in cmp['delta'].values()) and all(v==0 for v in cmp['definition_total_delta'].values())
actual=[]
for name,digest in after['rtl_sha256'].items():
 p=native/'execution/off'/name;q=historical/'execution/off'/name
 assert sha(p)==sha(q)==digest
 actual.append({'name':name,'sha256':digest,'bytes':p.stat().st_size})
pa=after['full_profile'];pb=before['full_profile'];focused=read(B/'model-off-r1/profile.json')
assert focused==pa,'focused OFF and native actual constructor products differ'
for group in ['core','profile']:
 assert pa[group].pop('postedPreparationPriority')is False
 assert pb[group].pop('memoryProofFetchChain')is False
assert pa==pb,'historical native parameters differ beyond two absent/default-false flags'
actualParams=read(native/'execution/off/actual-parameters.json');assert actualParams['allActualParametersEqualExpected']is True
actualReceipt=read(native/'analysis/actual-pair.json');assert actualReceipt['complete_profile_arities']==[140,32,11]
refs=[ref(p)for p in [ap,bp,fp,np,O/'selected-off-IntegerBackend.scala',O/'selected-fetch-off-MemoryProofFrontier.scala',native/'execution/off/receipt.json',historical/'execution/off/receipt.json',native/'analysis/historical-baseline-comparison.json',native/'execution/off/actual-parameters.json',native/'analysis/actual-pair.json',B/'model-off-r1/profile.json',Path(__file__)]]
r={'status':'PASS_GENERIC_OFF_STRUCTURAL_EQUIVALENCE','baseline_head':BASE,'candidate_head':CAND,'comparison':'exact_semantic_structure','raw_byte_equality_claimed':False,'production_body_equal':True,'ports_equal':True,'state_equal':True,'scope':'Source elaboration OFF-branch identity plus literal actual native OFF artifacts for the exact focused constructor profile. Not a universal formal proof or mapped timing claim.','baseline_production_tree':basetree,'old_production_head':OLD,'old_production_tree':oldtree,'historical_native_head':FETCH,'native_literal_comparison':{'before_head':FETCH,'after_head':CAND,'normalization_rules':[],'modules':actual,'exact_raw_module_bytes_equal':True},'source_elaboration_steps':['7c519 src/main raw git tree equals527a src/main','1b33 MemoryProofFrontier with memoryProofFetchChain=false selects entire original527a frontier body','aa37 IntegerBackend with postedPreparationPriority=false selects entire original7c519 backend body'],'actual_profile_equal_after_removing_absent_default_false_flags':True,'complete_constructor_arities':[140,32,11],'artifacts':refs}
(O/'generic-off.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(ref(O/'generic-off.json')))
