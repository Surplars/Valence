#include "order_oracle.h"
#include <fstream>
#include <iostream>
#include <iterator>
using namespace order_oracle;
int main(int argc,char **argv){try{
    require(argc==3,"usage: host guest.bin symbols.txt");std::ifstream bin(argv[1],std::ios::binary);
    require(bool(bin),"missing image");std::vector<uint8_t> bytes(std::istreambuf_iterator<char>(bin),{});
    std::ifstream syms(argv[2]);std::map<std::string,uint64_t> symbols;std::string name;uint64_t v;
    while(syms>>name>>std::hex>>v)symbols[name]=v;
    Architecture a(bytes);while(a.pc!=symbols.at("replay_done"))a.retire(a.pc);a.retire(a.pc);
    require(a.loads==7&&a.stores==1&&a.gpr[10]==value(overlap)&&a.gpr[11]==value(overlap)&&a.gpr[12]==0x2aaaaaaa&&a.gpr[17]==0,"independent expected guest outcome mismatch");
    for(unsigned i=0;i<4;++i)require(a.gpr[13+i]==value(cold+64*i),"survivor value mismatch");
    a.compare(a.gpr);unsigned rejected=0;
    auto negative=[&](auto fn){bool caught=false;try{fn();}catch(const std::exception &){caught=true;}require(caught,"host negative escaped");++rejected;};
    negative([&]{Architecture q(bytes);q.retire(rom+4);});
    negative([&]{auto bad=a.gpr;bad[10]^=1;a.compare(bad);});
    negative([&]{value(cold+8);});
    Token t{0xfedcba9876543210ULL,15};Replay r;r.select(t,t,10);r.observePending(t,11);r.accept(t);r.verify();
    negative([&]{Replay q;q.observePending(t,11);});
    negative([&]{Replay q;q.select(t,t,10);q.accept(t);});
    negative([&]{Replay q;q.select(t,t,10);q.observePending(t,11);q.verify();});
    negative([&]{Replay q;q.select(t,{t.tag^(1ULL<<63),t.index},10);});
    negative([&]{Replay q;q.select(t,t,10);q.observePending({t.tag^1,t.index},11);});
    negative([&]{Replay q;q.select(t,t,10);q.observePending(t,12);});
    std::cout<<"PASS_HOST_ONLY instructions="<<a.retired<<" negatives="<<rejected<<" rtl_execution=0\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
