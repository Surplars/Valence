"""Strict d5805c6 OFF comparison: exactly one reviewed source locator relocation.

Historical normalizer untouched; strings, assertion predicates and functional
bytes remain exact. No inferred/dynamic mapping accepted from emitted output.
"""
import hashlib
import re
import subprocess
import buffered_return_flow_cpu as prior
COMMIT = 'd5805c648aae30cf6c7004fdd0c5a86a4a84b988'
PATH = 'src/main/scala/core/ooo/integration/MappedMachineCore.scala'
OLD_LINE, NEW_LINE, COUNT = 150, 153, 1
OLD = b'Assertion failed at MappedMachineCore.scala:150'
NEW = b'Assertion failed at MappedMachineCore.scala:153'
RX = re.compile(rb'(intrinsic\(circt_chisel_ifelsefatal<format = ")'
                rb'Assertion failed at MappedMachineCore\.scala:150'
                rb'(\\n", label = "chisel3_builtin">,)')

def relocate_old(data):
    result,count=RX.subn(lambda m:m[1]+NEW+m[2],data)
    prior.need(count==COUNT,'exact approved OFF diagnostic occurrence changed')
    return result

def compare(a,b):
    return relocate_old(prior.row.normalize_fir(a)) == prior.row.normalize_fir(b)

def validate(a,b):
    old=subprocess.check_output(['git','show',COMMIT+':'+PATH],cwd=prior.common.ROOT,text=True).splitlines()
    new=(prior.common.ROOT/PATH).read_text().splitlines()
    prior.need(old[OLD_LINE-1]==new[NEW_LINE-1] and old[OLD_LINE-1].strip() == 'when(core.io.memory.request.fire) { assert(adapter.io.virtual.request.fire) }',
               'OFF diagnostic source assertion changed')
    prior.need(compare(a,b),'OFF_FIR_DRIFT beyond one reviewed diagnostic source locator')
    normalized=prior.row.normalize_fir(b)
    line=next(x for x in normalized.splitlines() if NEW in x)
    # Mutate the existing final assertion enable argument, not a guessed name.
    call=re.search(rb'(label = "chisel3_builtin">, [^,]+, [^,]+, )([^\)]+)(\))',line)
    prior.need(call is not None,'OFF assertion negative anchor absent')
    predicate=line.replace(call[0],call[1]+b'UInt<1>(0h0)'+call[3],1)
    logic=next(x for x in normalized.splitlines() if b'connect supply_states_bore, state' in x)
    tests=[('diagnostic_body',normalized.replace(NEW,b'Assertion FAILED at MappedMachineCore.scala:153',1)),
           ('unapproved_source_line',normalized.replace(NEW,b'Assertion failed at MappedMachineCore.scala:154',1)),
           ('assert_predicate',normalized.replace(line,predicate,1)),
           ('logic',normalized.replace(logic,logic.replace(b', state',b', UInt<2>(0h0)'),1))]
    for name,mutant in tests:
        prior.need(mutant!=normalized and not compare(a,mutant),'OFF comparator accepted '+name)
    return {'status':'PASS_EXACT_OFF_WITH_ONE_DIAGNOSTIC_RELOCATION','old_commit':COMMIT,
        'mapping':[{'file':PATH,'old_line':OLD_LINE,'new_line':NEW_LINE,'occurrences':COUNT,
                    'identical_assertion':old[OLD_LINE-1].strip()}],
        'source_sha256':prior.sha(prior.common.ROOT/PATH),'negative_calibrations':[x[0] for x in tests],
        'old_sha256':hashlib.sha256(a).hexdigest(),'new_sha256':hashlib.sha256(b).hexdigest()}
