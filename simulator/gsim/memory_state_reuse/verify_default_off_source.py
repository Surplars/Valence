#!/usr/bin/env python3
"""Erase only documented compile-time additions; require exact baseline bytes.

This source gate does not establish actual emitted-RTL equivalence.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASELINE_SHA256 = 'ac2cc04c34bef71c0e8b00ca7362dff6ab428b3611fe8b6b64625eed58ecdbbb'


def replace_span(source, start, end, replacement=''):
    if source.count(start) != 1:
        raise ValueError('source contract boundary drift: ' + start.strip())
    a = source.index(start)
    b = source.index(end, a)
    return source[:a] + replacement + source[b:]


def verify():
    source = (ROOT / 'src/main/scala/core/ooo/integration/IntegerBackend.scala').read_text()
    result = replace_span(source, '    // A row has one immutable operation class', '    val orderCheckValid',
                          '    val loadBeat      = Reg(Vec(p.robEntries, UInt(61.W)))\n'
                          '    val loadLanes     = Reg(Vec(p.robEntries, UInt(8.W)))\n')
    result = replace_span(result, '        if (p.sharedMemoryAddressState) {', '        orderCheckIndex :=',
                          '        loadBeat(actualMemoryIndex) := actualCanonicalAddress(63, 3)\n'
                          '        loadLanes(actualMemoryIndex) := actualLanes\n')
    for line in ('                sharedAddressStoreWrites.foreach(_(dispatchChoice.index)(lane) := true.B)\n',
                 '                sharedAddressStoreWrites.foreach(_(slot)(rank) := true.B)\n'):
        if result.count(line) != 1:
            raise ValueError('source contract witness drift')
        result = result.replace(line, '')
    result = replace_span(result, '    sharedAddressStoreWrites.foreach { writers =>',
                          '    if (p.registeredBranchRedirect) {')
    result = replace_span(result, '    // Allocation is the only queue writer', '    // In the RAM profile')
    result = replace_span(result, '            if (p.reconstructIssueTokenIndex) {',
                          '            queue(renamed.bits.token.index).request :=')
    result = result.replace('issueEntries', 'queue')
    observed = hashlib.sha256(result.encode()).hexdigest()
    if observed != BASELINE_SHA256:
        raise ValueError('OFF-erased backend bytes differ from published-equivalent baseline: ' + observed)
    return dict(schema='memory-state-reuse-default-off-source-v1',
                baseline_commit='0da2a2258a202f911a1f2ad7a1dd6ed18098a5af',
                baseline_backend_sha256=BASELINE_SHA256,
                candidate_backend_sha256=hashlib.sha256(source.encode()).hexdigest(),
                explicit_compile_time_erasure_restores_exact_source=True,
                native_equality_verified=False, DUT_execution=False)


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
