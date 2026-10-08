"""Fail-closed source-enum and generated-header schema validation; no RTL taps."""
import re
from pathlib import Path

def validate(root, header, entries, prefix):
    root=Path(root);header=Path(header).read_text() if isinstance(header,Path) else header
    source=root/'src/main/scala/core/ooo'
    if entries>1:
        text=(source/'NonBlockingCoherentLineCache.scala').read_text()
        assert re.search(r'free\s*::\s*evictWait\s*::\s*acquire\s*::\s*fill\s*::\s*result\s*::\s*Nil\s*=\s*Enum\(5\)',text),'unknown nonblocking phase enum'
        assert re.search(r'uint8_t '+re.escape(prefix)+r'phase\['+str(entries)+r'\]; // width = 3,',header),'unknown nonblocking generated phase layout'
    else:
        text=(source/'CoherentLineCache.scala').read_text()
        names='idle,evictCapture,evictSend,evictAck,acquire,fill,missResponse,bypassSend,bypassResponse,probeCapture,probeSend,flushScan'
        assert re.search(r'Seq\('+r'\s*,\s*'.join(names.split(','))+r'\)\s*=\s*Enum\(12\)',re.sub(r'\s+','',text)),'unknown legacy phase enum'
        for name,width in [('state',4),('probeResume',4),('flushActive',1),('pendingBypass',1)]:
            assert re.search(r'uint8_t '+re.escape(prefix+name)+r'; // width = '+str(width)+',',header),'unknown legacy generated layout '+name
    bad=header.replace(prefix+'phase[',prefix+'unexpected_phase[') if entries>1 else header.replace(prefix+'state;',prefix+'unexpected_state;')
    return bad
