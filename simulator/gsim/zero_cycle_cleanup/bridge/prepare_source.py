#!/usr/bin/env python3
"""Freeze current source/assets for a new bounded bridge run, with no tool execution."""
import argparse,hashlib,json,subprocess
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();source=a.source.resolve();root=Path(__file__).resolve().parent
    if a.output.exists():raise RuntimeError('Preserve prior freeze; use a new path')
    names=subprocess.check_output(['git','-C',str(source),'ls-files','--cached','--others','--exclude-standard','-z']).split(b'\0')
    names=sorted({n.decode() for n in names if n and (source/n.decode()).is_file()})
    files={n:sha(source/n) for n in names if not {'.git','out','build','__pycache__'} & set(Path(n).parts)}
    required={'src/test/scala/ooo/BridgePayloadEnablePairGsim.scala','src/test/scala/ooo/LocalPayloadWriteEnableConfigSpec.scala','simulator/gsim/harness/bridge_payload_enable.cpp','simulator/gsim/harness/bridge_payload_memory.h'}
    if not required.issubset(files):raise RuntimeError('Missing bridge fixture/oracle sources')
    assets=[*root.glob('*.py'),*(root/'fixture').glob('*')]
    value={'status':'SOURCE_FROZEN_NO_EXECUTION_CLAIM','files':files,'verification_inputs':{p.relative_to(root).as_posix():sha(p) for p in sorted(assets) if p.is_file()},'scope':'Fresh current-source fixture freeze, not the historical component-r7 qualification.'}
    a.output.write_text(json.dumps(value,indent=2)+'\n');print(value['status'])
if __name__=='__main__':main()
