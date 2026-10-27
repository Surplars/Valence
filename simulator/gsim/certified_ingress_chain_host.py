"""Pinned additive derivative. Historical host/oracle remains immutable."""
from pathlib import Path
import hashlib
HERE = Path(__file__).resolve().parent
BASE_SHA = '242ab701cf22cb80136a9d24c81c3f14f208268fdd78d16b0f034dc7eeeeff1c'

def derive():
    p=HERE/'harness/ordered_owner_chain.cpp'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==BASE_SHA, 'sealed chain oracle changed'
    s=p.read_text().replace('OrderedOwnerChainGsim','CertifiedIngressChainGsim')
    edits=[
      ('Test((injection=="phase"||injection=="completion")?"":injection).run(',
       'Test((injection=="phase"||injection=="completion"||injection=="source")?"":injection).run('),
      ('        d.set_io$$start$$valid(0); drive(Op{0,3,0,0});',
       '        d.set_io$$useCertificate(0);\n        d.set_io$$start$$valid(0); drive(Op{0,3,0,0});'),
      ('        // Canonical little-endian u64 records;', '''        if(d.get_io$$finalRequest()) {
            need(bool(d.get_io$$ingressPush()) != bool(d.get_io$$certifiedPass()),
                 "one final acceptance must have exactly one sink");
            if(d.get_io$$certifiedPass()) {
                need(d.get_io$$checkedPush()&&!d.get_io$$checkedFault()&&d.get_io$$certifiedNominal(),
                     "certified route requires nonfault checked capture");
                need(d.get_io$$finalPayload$$address()==d.get_io$$checkedPayload$$address()&&
                     d.get_io$$finalPayload$$size()==d.get_io$$checkedPayload$$size()&&
                     d.get_io$$finalPayload$$translationEpoch()==d.get_io$$checkedPayload$$translationEpoch(),
                     "certified final-source PA size epoch association");
                need(d.get_io$$selectedSource()==0&&!d.get_io$$finalOrigin()&&
                     d.get_io$$finalPayload$$precheckedLoad()&&!d.get_io$$finalPayload$$write(),
                     "noninteger/store source acquired certified authority");
            }
            if(d.get_io$$selectedSource()!=0)
                need(!d.get_io$$certifiedNominal()&&!d.get_io$$certifiedPass(),
                     "fast drain local or FP source used certified ingress");
        }
        // Canonical little-endian u64 records;'''),
      ('    void coordinatedReset() {', (HERE/'harness/certified_ingress_chain_cases.inc').read_text()+'\n    void coordinatedReset() {'),
      ('    std::cout<<"ORDERED_OWNER_CHAIN_PASS actual_modules=1 full_cpu=0\\n";return 0;',
       '''    Test(injection=="source"?injection:"").mixedFinalSources();
    Test().certifiedSuperpage(CERTIFIED_INGRESS_ENABLED);
    std::cout<<"CERTIFIED_INGRESS_CHAIN_PASS actual_modules=1 full_cpu=0\\n";return 0;''')]
    for old,new in edits:
        assert s.count(old)==1,('nonunique pinned derivative anchor',old)
        s=s.replace(old,new,1)
    return '#ifndef CERTIFIED_INGRESS_ENABLED\n#define CERTIFIED_INGRESS_ENABLED 1\n#endif\n'+s
