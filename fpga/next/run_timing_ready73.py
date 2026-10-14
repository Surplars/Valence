#!/usr/bin/env python3
"""Launch the reviewed fresh ready73 Tcl flow and preserve all failure codes."""
import argparse
import importlib.util
from pathlib import Path
import subprocess

def validate_export(export):
    path=Path(__file__).with_name('board_timing_ready73.py')
    spec=importlib.util.spec_from_file_location('ready73_entry',path)
    entry=importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
    entry.validate_native_output(Path(export)/'rtl')

def launch(vivado, binding, output, export):
    export=Path(export).resolve()
    validate_export(export)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh output directory required')
    command = [str(vivado), '-mode', 'batch', '-source', str(Path(__file__).with_suffix('.tcl')),
               '-tclargs', str(Path(binding).resolve()), str(output), str(export)]
    result = subprocess.run(command, check=False)
    if result.returncode:
        return result.returncode if result.returncode > 0 else 128-result.returncode
    marker = output / 'evaluation-complete.txt'
    if not marker.is_file() or marker.read_text().splitlines()[0] != 'COMPLETED_SYNTH_OPT_PLACE_NOT_TIMING_SIGNOFF':
        return 1
    return 0

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vivado', required=True)
    p.add_argument('--export', required=True, type=Path)
    p.add_argument('--binding', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    raise SystemExit(launch(args.vivado, args.binding, args.output, args.export))
