#define main retained_ready_main
#include "trace_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();b.latency=180;b.responseHold=UINT64_MAX;b.dualWorkload(1,false);
 for(unsigned n=0;n<300&&!b.entries.at(*b.youngLoad).killed;++n)b.tick();
 b.check(b.entries.at(*b.youngLoad).killed&&b.entries.at(*b.secondLoad).killed,"selective recovery absent");
 b.check(b.earlyStarts==2&&!b.entries.at(*b.youngLoad).response&&!b.entries.at(*b.secondLoad).response,"two held accepted reads absent");
 auto killedAt=b.cycle;
 for(unsigned n=0;n<300&&!b.entries.at(*b.oldStore).started;++n)b.tick();
 auto&s=b.entries.at(*b.oldStore);auto&l=b.entries.at(*b.youngLoad);auto&l2=b.entries.at(*b.secondLoad);
 std::cout<<"RECOVERY_HELD start="<<s.start<<" killed_at="<<killedAt<<" current="<<b.cycle<<" store_started="<<s.started<<" load_start="<<l.start<<" load2_start="<<l2.start<<" b2="<<b.b2IdleStarts<<"\n";
 b.check(!s.started&&!b.b2IdleStarts&&!l.response&&!l2.response,"post-cancel B2 prohibition changed");
 b.responseHold=0;b.drain();b.check(s.retired && b.entries.at(*b.secondStore).retired && !l.retired && !l2.retired,"post-cancel eventual architectural outcome mismatch");std::cout<<"RECOVERY_HELD_PASS\n";
}catch(const std::exception&e){std::cerr<<"RECOVERY_HELD_FAIL "<<e.what()<<'\n';return 1;}
