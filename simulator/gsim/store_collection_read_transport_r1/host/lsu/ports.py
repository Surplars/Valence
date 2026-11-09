"""Source-derived semantic ports; NOT a guessed generated C++ API.

Selected ON fixture only. Bind these scalar names to an emitted public header
before generating a driver. Scalars representing Vec elements are normalized
here; actual array getters/setters remain a later mechanical binding decision.
"""
REQUEST_WIDTHS = dict(returnHandle=3, atomic=1, atomicOp=5, address=64, write=1,
                      size=2, data=64, mask=8, virtualized=1, precheckedLoad=1,
                      translationEpoch=32, prefetchNextAllowed=1, uncached=1)
RESPONSE_WIDTHS = dict(returnHandle=3, data=64, error=1, pageFault=1)
TOKEN_WIDTHS = {'index': 4, 'tag': 64}
PROOF_WIDTHS = {'token.index': 4, 'token.tag': 64, 'epoch': 32, 'address': 64,
                'data': 64, 'mask': 8, 'size': 2, 'headAuthorized': 1,
                'physicalPmpAllowed': 1, 'originalPhysical': 1, 'integerOrigin': 1,
                'legacyPostedAccepted': 1, 'finalChecked': 1}
ORIGIN_WIDTHS = {'token.index': 4, 'token.tag': 64, 'epoch': 32}
FROZEN_WIDTHS = dict(address=64, physicalAddress=64, size=3, mask=8)
COMPLETE_WIDTHS = {'token.index': 4, 'token.tag': 64, 'data': 64, 'nextPc': 64,
                   'exception': 1, 'cause': 64, 'tval': 64}


def fields(prefix, widths):
    return {prefix + '.' + n: w for n, w in widths.items()}


def valid(prefix, widths):
    return {prefix + '.valid': 1, **fields(prefix + '.bits', widths)}


OP_WIDTHS = {'token.index': 4, 'token.tag': 64, 'pc': 64, 'address': 64,
             'data': 64, 'atomic': 1, 'atomicOp': 5, 'store': 1, 'size': 2,
             'unsigned': 1, 'accessDenied': 1, 'virtualized': 1,
             'precheckedLoad': 1, 'physicalAddress': 64, 'translationEpoch': 32,
             'collectionHeadRead': 1, 'forward.valid': 1, 'forward.bits': 64,
             'canonicalStoreEpoch.valid': 1, 'canonicalStoreEpoch.bits': 32}
OP_WIDTHS.update(valid('postedProof', PROOF_WIDTHS))
OP_WIDTHS.update(valid('frozenStoreProof', FROZEN_WIDTHS))
INPUT_WIDTHS = dict.fromkeys(['reset', 'start.valid', 'parallel',
    'candidateAdmission.precheckedLoad', 'candidateAdmission.parallel',
    'boundHeadStoreOverlapQualified', 'memory.request.ready',
    'memory.response.valid', 'complete.ready', 'fastStoreRetire', 'fastLoadRetire'], 1)
INPUT_WIDTHS.update(fields('start.bits', OP_WIDTHS))
INPUT_WIDTHS.update(valid('issueDestination', {'value': 6}))
# Scalar Valid(UInt) has a bits leaf, not a value member.
INPUT_WIDTHS['issueDestination.bits'] = INPUT_WIDTHS.pop('issueDestination.bits.value')
INPUT_WIDTHS.update(valid('relaxStoreOwner', TOKEN_WIDTHS))
INPUT_WIDTHS.update(fields('memory.response.bits', RESPONSE_WIDTHS))
INPUT_WIDTHS.update({'cancel.' + str(n): 1 for n in range(4)})

OUTPUT_WIDTHS = dict.fromkeys(['start.ready', 'issueAvailable',
    'candidateIssueAvailable', 'ordinaryLoadCapacity.available',
    'boundHeadStoreOverlapAccepted', 'memory.request.valid',
    'memory.response.ready', 'collectionHeadRead', 'complete.valid',
    'busy', 'discarded', 'forwarded'], 1)
OUTPUT_WIDTHS.update({'ordinaryLoadCapacity.slot': 2, 'ordinaryLoadCapacity.actualSlot': 2})
OUTPUT_WIDTHS.update(valid('completedIssueDestination', {'value': 6}))
OUTPUT_WIDTHS['completedIssueDestination.bits'] = OUTPUT_WIDTHS.pop('completedIssueDestination.bits.value')
OUTPUT_WIDTHS.update(fields('memory.request.bits', REQUEST_WIDTHS))
OUTPUT_WIDTHS.update(fields('complete.bits', COMPLETE_WIDTHS))
OUTPUT_WIDTHS.update(valid('fastLoadPreview', COMPLETE_WIDTHS))
OUTPUT_WIDTHS.update(valid('postedProof', PROOF_WIDTHS))
OUTPUT_WIDTHS.update(valid('canonicalStoreOrigin', ORIGIN_WIDTHS))
OUTPUT_WIDTHS.update(valid('frozenStoreProof', FROZEN_WIDTHS))
OUTPUT_WIDTHS.update(valid('requestOwner', TOKEN_WIDTHS))
OUTPUT_WIDTHS.update(valid('forwardStore', {'token.index': 4, 'token.tag': 64,
                                          'address': 64, 'size': 2, 'data': 64}))
for slot in range(4):
    OUTPUT_WIDTHS.update(fields('owner.' + str(slot), TOKEN_WIDTHS))
    OUTPUT_WIDTHS['live.' + str(slot)] = 1
    OUTPUT_WIDTHS['phase.' + str(slot)] = 2
    OUTPUT_WIDTHS['loadResultPublish.' + str(slot) + '.valid'] = 1
    OUTPUT_WIDTHS['loadResultPublish.' + str(slot) + '.bits'] = 6
    OUTPUT_WIDTHS.update(valid('heldLoadValue.' + str(slot), dict(destination=6, data=64)))
INPUTS, OUTPUTS = list(INPUT_WIDTHS), list(OUTPUT_WIDTHS)
REQUEST, RESPONSE, COMPLETE = list(REQUEST_WIDTHS), list(RESPONSE_WIDTHS), list(COMPLETE_WIDTHS)
