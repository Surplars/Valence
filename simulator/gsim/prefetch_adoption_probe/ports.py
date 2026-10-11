"""Existing raw TL ABI plus immutable PF/attachment observation outputs only."""
import importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('qualified_coexist_ports',Path(__file__).resolve().parent.parent/'posted_prefetch_coexist/ports.py')
_original=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_original)
for _name in ('INPUTS','OUTPUTS','REQUEST','PROOF','AB','C','D'):
    globals()[_name]=getattr(_original,_name)
EXTRA=['demandAttach','demandAttachReady','demandAttachSlot','demandAttachTicket','demandAttachAddress',
       'mshrDemandAttachedMask','acquireTagBits','acquireIssued','acquireIssuedSlot','acquireIssuedTagLo',
       'acquireIssuedTagHi','refillTagLo','refillTagHi','refillDemandAttached','refillTicket']
OUTPUTS += ['pfObservation.'+n for n in EXTRA]
def emit_driver(path):
    _original.emit_driver(path)
    path=Path(path);text=path.read_text();anchor=' SPostedPrefetchCoexistGsim d;'
    assert text.count(anchor)==1
    # The pinned simulator leaves unused storage unspecified. Initialize the
    # trivially-copyable host object before reset, then perform real reset edges.
    text=text.replace('#include <cstdint>','#include <cstdint>\n#include <cstring>\n#include <type_traits>')
    text=text.replace(anchor,anchor+'\n static_assert(std::is_trivially_copyable_v<SPostedPrefetchCoexistGsim>);'
        '\n std::memset(&d, 0, sizeof(d)); d.LOG_START = 1; d.activateAll();')
    path.write_text(text)
