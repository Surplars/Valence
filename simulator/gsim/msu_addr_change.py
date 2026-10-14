#!/usr/bin/env python3
"""Actual MSU selected-pmpaddr identity and CSR/consumer-boundary GSIM gate."""
import argparse, hashlib, json, re
from pathlib import Path
import run as common

def main():
    p=argparse.ArgumentParser();p.add_argument('--tag',required=True);p.add_argument('--build-run',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.tag):p.error('unsafe tag')
    if not a.build_run:print('MSU_ADDR_CHANGE_GATE_READY entries=16 registered=true boundary=both');return
    gsim,cxx=common.setup(False)
    out=common.test(gsim,cxx,a.tag,'ooo.MsuAddrChangeGsimMain','MsuAddrChangeGsim','msu_addr_change.cpp',parameters=('registered','entries=16','boundary=both'),defines={'PMP_ENTRIES':16,'PMP_BOUNDARY':3},timeout=180)
    text=(out/'test.log').read_text()
    for anchor in ['PMP boundary PASS mode=3','PMP CSR publication PASS entries=16','commands=810']:
        if anchor not in text:raise RuntimeError('missing '+anchor)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (out/'msu-receipt.json').write_text(json.dumps({'status':'PASS_ACTUAL_MSU_COMPONENT','log_sha256':sha(out/'test.log'),'full_cpu':False,'physical_result':'UNMEASURED'},indent=2)+'\n')
if __name__=='__main__':main()
