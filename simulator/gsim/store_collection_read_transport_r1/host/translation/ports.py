"""Explicit scalar ABI for the isolated selected checked adapter.

No DUT model or oracle is imported here. Header names are mechanically derived
and must be checked against the emitted header before compiling the driver.
"""

REQUEST_WIDTHS = dict(returnHandle=3, atomic=1, atomicOp=5, address=64, write=1,
                      size=2, data=64, mask=8, virtualized=1, precheckedLoad=1,
                      translationEpoch=32, prefetchNextAllowed=1, uncached=1)
RESPONSE_WIDTHS = dict(returnHandle=3, data=64, error=1, pageFault=1)
PROOF_WIDTHS = {'token.index': 4, 'token.tag': 64, 'epoch': 32, 'address': 64,
                'data': 64, 'mask': 8, 'size': 2, 'headAuthorized': 1,
                'physicalPmpAllowed': 1, 'originalPhysical': 1, 'integerOrigin': 1,
                'legacyPostedAccepted': 1, 'finalChecked': 1}
ORIGIN_WIDTHS = {'token.index': 4, 'token.tag': 64, 'epoch': 32}
FROZEN_WIDTHS = dict(address=64, physicalAddress=64, size=3, mask=8)
VM_WIDTHS = dict(satp=64, sum=1, mxr=1, dataPrivilege=2)
TRANSLATION_REQUEST_WIDTHS = dict(virtualAddress=64, rootPpn=44, asid=16,
                                  mode=4, privilege=2, access=2, sum=1, mxr=1)
TRANSLATION_RESPONSE_WIDTHS = {'physicalAddress': 64, 'pageFault': 1, 'accessFault': 1,
                               'level': 3, 'napot': 1, 'global': 1, 'pbmt': 2}
CERTIFICATE_WIDTHS = {'origin.' + n: w for n, w in ORIGIN_WIDTHS.items()}
CERTIFICATE_WIDTHS.update(virtualAddress=64, size=3, mask=8, physicalAddress=64)
REQUEST = list(REQUEST_WIDTHS)
RESPONSE = list(RESPONSE_WIDTHS)
PROOF = list(PROOF_WIDTHS)
ORIGIN = list(ORIGIN_WIDTHS)
FROZEN = list(FROZEN_WIDTHS)
ROUTES = ['ingressPass', 'identityPass', 'ingressQueued', 'translatedEnqueue',
          'translatedDequeue', 'checkedEnqueue', 'checkedDequeue']


def fields(prefix, widths):
    return {prefix + '.' + n: w for n, w in widths.items()}


def valid(prefix, widths):
    return {prefix + '.valid': 1, **fields(prefix + '.bits', widths)}


INPUT_WIDTHS = dict.fromkeys([
    'reset', 'virtual.request.valid', 'virtual.response.ready',
    'physical.request.ready', 'physical.response.valid', 'collectionRead',
    'posted.aggregateDrained', 'posted.externalBusy', 'translation.request.ready',
    'precheckFlush', 'pmpRawChanged'], 1)
INPUT_WIDTHS.update(fields('virtual.request.bits', REQUEST_WIDTHS))
INPUT_WIDTHS.update(fields('physical.response.bits', RESPONSE_WIDTHS))
INPUT_WIDTHS.update(valid('posted.upstreamProof', PROOF_WIDTHS))
INPUT_WIDTHS.update(valid('translation.response', TRANSLATION_RESPONSE_WIDTHS))
INPUT_WIDTHS.update(valid('loadPrecheck.request', dict(address=64, size=3, write=1)))
INPUT_WIDTHS.update(valid('translationPeek.response', TRANSLATION_RESPONSE_WIDTHS))
INPUT_WIDTHS.update(valid('canonicalStoreOrigin', ORIGIN_WIDTHS))
INPUT_WIDTHS.update(valid('frozenStoreProof', FROZEN_WIDTHS))
INPUT_WIDTHS.update(fields('vmState', VM_WIDTHS))
INPUT_WIDTHS.update({'pmpCfg.' + str(n): 8 for n in range(16)})
INPUT_WIDTHS.update({'pmpAddr.' + str(n): 54 for n in range(16)})

OUTPUT_WIDTHS = dict.fromkeys([
    'virtual.request.ready', 'virtual.response.valid', 'physical.request.valid',
    'physical.response.ready', 'physicalCollectionRead', 'posted.contextChanging',
    'translation.response.ready', 'loadPrecheck.stable', 'idle', 'physicalRequest',
    'pageFault', 'checkedRead', 'checkedFault'] + ROUTES, 1)
OUTPUT_WIDTHS.update(fields('virtual.response.bits', RESPONSE_WIDTHS))
OUTPUT_WIDTHS.update(fields('physical.request.bits', REQUEST_WIDTHS))
OUTPUT_WIDTHS.update(valid('posted.requestProof', PROOF_WIDTHS))
OUTPUT_WIDTHS['posted.contextEpoch'] = 32
OUTPUT_WIDTHS.update(valid('translation.request', TRANSLATION_REQUEST_WIDTHS))
OUTPUT_WIDTHS.update(valid('loadPrecheck.response', dict(physicalAddress=64, pbmt=2, epoch=32)))
OUTPUT_WIDTHS['loadPrecheck.epoch'] = 32
OUTPUT_WIDTHS.update(valid('translationPeek.request', TRANSLATION_REQUEST_WIDTHS))
OUTPUT_WIDTHS.update(valid('canonicalStoreCertificate', CERTIFICATE_WIDTHS))
INPUTS = list(INPUT_WIDTHS)
OUTPUTS = list(OUTPUT_WIDTHS)


def method(prefix, name):
    return prefix + ('reset' if name == 'reset' else 'io$$' + name.replace('.', '$$'))
