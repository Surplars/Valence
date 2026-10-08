#!/usr/bin/env python3
"""Bounded independent home protocol checks; no board or CPU run."""
import json,os,subprocess
from run import BUILD,setup,test

def main():
    gsim,cxx=setup(False)
    report={'status':'running','scope':'home protocol fixture only','cases':{}}
    for entries in (1,2,4):
        out=test(gsim,cxx,f'home-mshr-{entries}','ooo.HomeMshrGsimMain','HomeMshrGsim','home_mshr.cpp',
                 parameters=(str(entries),),defines={'HOME_ENTRIES':entries})
        for flag,anchor in [('--inject-data','independent Grant data mismatch'),
                            ('--bad-sink','GrantAck has no live sink' if entries>1 else 'line home GrantAck sink mismatch')]:
            p=subprocess.run([out/'run',flag],capture_output=True,text=True,timeout=60,
                             env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            (out/(flag[2:]+'.log')).write_text(p.stdout+p.stderr)
            if p.returncode==0 or anchor not in p.stdout+p.stderr:raise RuntimeError('negative did not reject '+flag)
        report['cases'][str(entries)]=(out/'test.log').read_text()
    report['status']='passed'
    (BUILD/'home-mshr.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
