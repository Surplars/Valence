#!/usr/bin/env python3
"""One explicit new-output-only compression step; never edits existing evidence."""
import argparse
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode=True

def load_helper(path):
    spec=importlib.util.spec_from_file_location('monitor_debug_compression_helper',Path(path).resolve())
    if spec is None or spec.loader is None:raise RuntimeError('cannot load bound compression helper')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);return helper

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('helper','before','after','receipt'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();helper=load_helper(a.helper)
    proof=helper.compress_new(a.before,a.after,a.receipt)
    if proof!=helper.validate_compression_receipt(a.before,a.after,a.receipt):raise RuntimeError('new compression proof did not revalidate')
    print('MONITOR_DEBUG_COMPRESSION_PASS')
if __name__=='__main__':main()
