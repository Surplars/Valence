"""Host-only revision; model/source identity remains the immutable prepared namespace."""
import importlib.util
from pathlib import Path as _Path
_FROZEN=_Path(__file__).resolve().parent.parent/'posted-preparation-priority-cpu-prep-r1'
_spec=importlib.util.spec_from_file_location('_frontier_frozen_contract',_FROZEN/'contract.py')
_frozen=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_frozen)
for _name in dir(_frozen):
 if not _name.startswith('_'):globals()[_name]=getattr(_frozen,_name)
HERE=_Path(__file__).resolve().parent
def guest():
 pins=_frozen.guest()
 for name,digest in pins.items():require(sha(HERE/name)==digest,'host-revision guest changed '+name)
 require(sha(HERE/'worksets_symbols.h')==sha(_FROZEN/'worksets_symbols.h'),'host-revision guest symbols changed')
 return pins
