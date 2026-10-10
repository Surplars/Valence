#include "copy_eviction.hpp"
#include <iostream>
int main(){using namespace pfcopy;const uint64_t a=0x80000000,b=0x80020000;Ledger l(a,b,0x20000);
 Event allocation;allocation.cycle=1;allocation.allocate=true;allocation.active=true;allocation.allocAddress=b+64;allocation.allocIndex=7;l.accept(allocation);
 Event i;i.cycle=10;i.active=true;i.install=true;i.installAddress=b+64;i.installIndex=7;l.accept(i);
 Event e;e.cycle=20;e.active=true;e.evict=true;e.victimAddress=b+64;e.victimIndex=7;e.evictForDemand=true;e.demandAddress=a+64;l.accept(e);
 Event s;s.cycle=30;s.active=true;s.cpu=true;s.cpuWrite=true;s.cpuAddress=b+64;l.accept(s);l.accept(s);
 require(l.allocations==1&&l.installs==1&&l.evictions==1&&l.paired==1&&l.followingMiss==1,"ledger positive chain");
 for(unsigned mode=0;mode<5;mode++){Ledger q(a,b,0x20000);q.accept(allocation);q.accept(i);auto bad=e;if(mode==0)bad.demandAddress+=64;if(mode==1)bad.demandWrite=true;if(mode==2)bad.evictForDemand=false;if(mode==3)bad.victimAddress+=64;if(mode==4)bad.active=false;q.accept(bad);q.accept(s);require(q.paired==0,"ledger unproven chain counted");}
 bool caught=false;try{auto bad=i;bad.installAddress++;l.accept(bad);}catch(const std::runtime_error&){caught=true;}require(caught,"unaligned install accepted");
 caught=false;try{auto bad=i;bad.installIndex=512;l.accept(bad);}catch(const std::runtime_error&){caught=true;}require(caught,"slot overflow accepted");
 caught=false;try{Ledger q(a,b,0x20000);q.accept(allocation);q.accept(i);auto bad=e;bad.cycle=9;q.accept(bad);}catch(const std::runtime_error&){caught=true;}require(caught,"reversed chronology accepted");
 for(unsigned n=0;n<3;n++){caught=false;try{Ledger q(a,b,0x20000);if(n!=0)q.accept(allocation);if(n==1)q.accept(allocation);auto bad=i;if(n==2)++bad.installIndex;q.accept(bad);}catch(const std::runtime_error&){caught=true;}require(caught,"PF allocation lineage corruption accepted");}
 Ledger q(a,b,0x20000);q.accept(allocation);auto err=i;err.install=false;err.error=true;q.accept(err);auto pr=e;pr.evict=false;pr.probe=true;q.accept(pr);require(q.errors==1&&q.probes==1&&q.installs==0&&q.evictions==0&&!q.owners[0].live,"PF error/probe conflated with installation or eviction");
 // Actual ABA counterexample: PF install, hit probe, normal demand refill of
 // the same PA/slot, A demand eviction, later B store must not resurrect PF.
 for(unsigned refill=0;refill<2;refill++){Ledger x(a,b,0x20000);x.accept(allocation);x.accept(i);Event hit;hit.cycle=11;hit.active=true;hit.probe=true;hit.probeHit=true;hit.probeIndex=7;hit.probeAddress=b+64;if(!refill)x.accept(hit);Event ordinary;ordinary.cycle=12;ordinary.successfulRefill=true;ordinary.installIndex=7;ordinary.installAddress=b+64;x.accept(ordinary);x.accept(e);x.accept(s);require(x.paired==0&&x.evictions==0&&x.followingMiss==0,"probe/non-PF refill ABA resurrected old PF");}
 // A probe miss or hit in another empty slot preserves the real PF generation.
 for(unsigned mode=0;mode<2;mode++){Ledger x(a,b,0x20000);x.accept(allocation);x.accept(i);Event probe;probe.cycle=11;probe.active=true;probe.probe=true;probe.probeHit=mode;probe.probeIndex=8;probe.probeAddress=b+128;x.accept(probe);x.accept(e);x.accept(s);require(x.paired==1&&x.followingMiss==1&&x.probes==1,"unrelated/missed probe destroyed PF witness");}
 std::cout<<"COPY_PF_LEDGER_HOST_PASS chain=1 rejected_claims=5 hostile=6 error_probe=1 probe_refill_ABA_rejected=2 unrelated_probe_preserved=2\n";
}
