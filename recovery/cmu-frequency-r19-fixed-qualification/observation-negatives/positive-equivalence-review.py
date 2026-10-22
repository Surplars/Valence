#!/usr/bin/env python3
"""Narrow static review, not a simulator or formal-equivalence proof."""
import ast
import hashlib
import json
import re
from pathlib import Path
ROOT=Path.cwd()
HERE=ROOT/'out/cmu-frequency-r19/fixed-native-observation-negatives-r1'
OLD=ROOT/'out/cmu-frequency-r19/fixed-native-final-v2'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
old_tb=(OLD/'testbench.source.sv').read_text()
new_tb=(HERE/'testbench.source.sv').read_text()
old_runner=(OLD/'runner.source.py').read_text()
new_runner=(HERE/'runner.source.py').read_text()
prior=json.loads((OLD/'receipt.json').read_text())
assert prior['status']=='PASS'
assert sha(OLD/'testbench.source.sv')==prior['source_sha256']['simulator/gsim/common/i1_runtime_fixed_tb.sv']
assert sha(OLD/'runner.source.py')==prior['source_sha256']['simulator/gsim/common/i1_runtime_fixed_native.py']
# Specialize only the changed sites at negative=0. Other negative hooks are
# identical in both files and are deliberately left untouched for this comparison.
old_positive=old_tb
for text in ['        if(negative==1 && packetWordIndex==0) expectedPacketWord=expectedPacketWord^1;\n',
             '      if(negative==1 && wirePosition==23) expectedWireByte=expectedWireByte^1;\n']:
    assert old_positive.count(text)==1
    old_positive=old_positive.replace(text,'')
old_positive=old_positive.replace(' (negative==3 ? GUARD_DATA^32\'h1 : GUARD_DATA)', 'GUARD_DATA')
new_positive=new_tb
# Exact newly added branch text only. Reject any deviation rather than using
# broad statement stripping, whole-file regex normalization, or whitespace folding.
branches = ['''        if(negative==1 && packetWordIndex==0) begin
          observedPacketWord=observedPacketWord^64'h1;
          $display("FIXED_NEGATIVE_OBSERVATION RX word=%0d original=%h observed=%h expected=%h",
              packetWordIndex,packetMemoryRequestData,observedPacketWord,expectedPacketWord);
        end
''', '''      if(negative==1 && wirePosition==23) begin
        observedWireByte=observedWireByte^8'h1;
        $display("FIXED_NEGATIVE_OBSERVATION TX byte=%0d original=%h observed=%h expected=%h",
            wirePosition,gmiiTxData,observedWireByte,expectedWireByte);
      end
''', '''      if(negative==3) begin
        data[63:32]=data[63:32]^32'h1;
        $display("FIXED_NEGATIVE_OBSERVATION GUARD original=%h observed=%h expected=%h",
            memory_read(32'h3038),data[63:32],GUARD_DATA);
      end
''']
for branch in branches:
    assert new_positive.count(branch)==1
    new_positive=new_positive.replace(branch,'')
for comment in ['        // Fault only the checker input copy; expected payload and DUT are unchanged.\n',
                '      // Mutate only the sampled wire byte, never the expected byte or expected CRC.\n',
                '      // data is a local readback copy; backing RAM and GUARD_DATA stay untouched.\n']:
    assert new_positive.count(comment)==1
    new_positive=new_positive.replace(comment,'')
# These blocking assignments have the same 4-state widths as their source wires,
# precede all reads in the same always body, and introduce no timing control.
for declaration,original in [('expectedPacketWord, observedPacketWord','expectedPacketWord'),
                             ('expectedWireByte, observedWireByte','expectedWireByte')]:
    assert new_positive.count(declaration)==1
    new_positive=new_positive.replace(declaration,original)
for assignment in ['        observedPacketWord=packetMemoryRequestData;\n','      observedWireByte=gmiiTxData;\n']:
    assert new_positive.count(assignment)==1
    new_positive=new_positive.replace(assignment,'')
new_positive=new_positive.replace('observedPacketWord','packetMemoryRequestData').replace('observedWireByte','gmiiTxData')
assert old_positive==new_positive,'The complete positive TB did not reduce to byte-identical text'
def function(text,name):
    return ast.dump(next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)
assert function(old_runner,'guest')==function(new_runner,'guest')
assert function(old_runner,'run')==function(new_runner,'run')
# The command construction, case loops and positive success checks are unchanged.
start='            if args.single_ratio and args.single_ratio != name:'
end="        negative_cases = [] if subset else "
old_loop=old_runner[old_runner.index(start):old_runner.index(end)]
new_loop=new_runner[new_runner.index(start):new_runner.index('        if args.negative_only:\n')]
assert old_loop==new_loop
positive_logs=[c for c in prior['cases'] if re.fullmatch('(unrelated|reversed)-case-[0-3]',c['name'])]
assert len(positive_logs)==8 and all(c['returncode']==0 for c in positive_logs)
checks={
 'complete_tb_at_negative_zero_after_identity_alias_elimination_byte_identical': True,
 'positive_tb_normalized_sha256':hashlib.sha256(old_positive.encode()).hexdigest(),
 'guest_generation_function_ast_identical':True,
 'native_process_runner_function_ast_identical':True,
 'positive_case_command_construction_loop_and_success_checks_byte_identical':True,
 'positive_clock_ratios_and_scenarios_unchanged_without_negative_only':True,
 'dut_and_fixture_sources_unchanged':True,
}
current=json.loads((ROOT/'out/cmu-frequency-r19/fixed-r3-emission.json').read_text())
for name,digest in prior['source_sha256'].items():
    if name.startswith(('src/main/','src/test/')):
        assert sha(ROOT/name)==digest,(name,'DUT source drift')
record={
 'status':'PASS_STATIC_POSITIVE_MODE_REVIEW',
 'scope':'Static exact-text specialization at the three changed negative hooks plus same-width blocking-alias elimination; not a formal proof and not a rerun of the positive matrix.',
 'prior_receipt':{'path':str((OLD/'receipt.json').relative_to(ROOT)),'sha256':sha(OLD/'receipt.json')},
 'old_tb_sha256':sha(OLD/'testbench.source.sv'),'new_tb_sha256':sha(HERE/'testbench.source.sv'),
 'old_runner_sha256':sha(OLD/'runner.source.py'),'new_runner_sha256':sha(HERE/'runner.source.py'),
 'checks':checks,
 'old_evidence_scope':'The prior final-v2 receipt retains 8 passing positive cases. Its negative-1 and negative-3 mutated reference values and do not establish observed-data corruption rejection. Its TX negative hook was not executed by that default negative matrix.',
 'new_evidence_scope':'This new subset runs RX packet observation bit flip, RX guard readback-copy bit flip, and TX GMII observed-byte bit flip. Expected packet bytes, expected CRC, GUARD_DATA, DUT, and backing RAM are not modified.',
 'positive_cases_rerun':0,
 'old_positive_logs_sha256':{c['name']+'.log':sha(OLD/(c['name']+'.log')) for c in positive_logs},
 'review_script_sha256':sha(HERE/'positive-equivalence-review.py'),
}
(HERE/'positive-equivalence-review.json').write_text(json.dumps(record,indent=2)+'\n')
print(record['status'])
