#define main retained_ready_main
#include "baseline_trace_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();b.latency=180;b.responseHold=UINT64_MAX;
 b.oldDataReady=b.proofCycle=b.firstEarlyPhysical=b.earlyReadDrain=0;b.boundProof.reset();
 auto owners=b.submit({divu(30,25,26),st(10,30),st(10,30,8),divu(31,30,26),beq(31),ld(20,11),ld(21,11,16)});
 b.oldStore=owners[1];b.secondStore=owners[2];b.youngLoad=owners[5];b.secondLoad=owners[6];
 for(unsigned n=0;n<300&&!b.entries.at(*b.oldStore).started;++n)b.tick();
 b.check(b.entries.at(*b.oldStore).started && b.b2IdleStarts && !b.entries.at(*b.youngLoad).killed,"phase-positive B2 launch must precede selective redirect");
 std::cout<<"PHASE_B2_BEFORE_KILL start="<<b.entries.at(*b.oldStore).start<<" cycle="<<b.cycle<<"\n";

 for(unsigned n=0;n<300&&!b.entries.at(*b.youngLoad).killed;++n)b.tick();
 b.check(b.entries.at(*b.youngLoad).killed&&b.entries.at(*b.secondLoad).killed,"selective recovery absent");
 b.check(b.earlyStarts==2&&!b.entries.at(*b.youngLoad).response&&!b.entries.at(*b.secondLoad).response,"two held accepted reads absent");
 auto killedAt=b.cycle;
 for(unsigned n=0;n<300&&!b.entries.at(*b.oldStore).started;++n)b.tick();
 auto&s=b.entries.at(*b.oldStore);auto&l=b.entries.at(*b.youngLoad);auto&l2=b.entries.at(*b.secondLoad);
 std::cout<<"RECOVERY_HELD start="<<s.start<<" killed_at="<<killedAt<<" current="<<b.cycle<<" store_started="<<s.started<<" load_start="<<l.start<<" load2_start="<<l2.start<<" b2="<<b.b2IdleStarts<<"\n";
 b.check(s.started&&b.b2IdleStarts&&!l.response&&!l2.response,"surviving B2 store failed preparation beside two response-held loads");
 b.responseHold=0;b.drain();b.dualWitness(false,false);std::cout<<"RECOVERY_HELD_PASS\n";
}catch(const std::exception&e){std::cerr<<"RECOVERY_HELD_FAIL "<<e.what()<<'\n';return 1;}
