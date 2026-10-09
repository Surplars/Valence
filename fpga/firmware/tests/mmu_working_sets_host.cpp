// Same production board and fixed AXI backing; no altered DUT timing or memory responses.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
struct Observed {
    Test* test=nullptr;
    unsigned traps=0,cases=0,first=0,last=24;bool terminal=false,poisonTrap=false;
    static void sample(SBoardSocGsim& d,void* cookie){
        auto& s=*static_cast<Observed*>(cookie);
        if(d.get_io$$trap$$valid()){
            uint64_t want=s.traps<3?(s.traps==0?13:s.traps==1?15:1):9;
            if(s.poisonTrap&&!s.traps)want=15;
            check(s.traps<3+s.last-s.first&&d.get_io$$trap$$bits$$cause()==want,"independent worksets trap order mismatch");++s.traps;
        }
        for(unsigned lane=0;lane<2;lane++)if(lane?d.get_io$$commit1():d.get_io$$commit0()){
            uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            if(pc==MMU_SMOKE_DONE_PC)s.terminal=true;
            if(pc==MMU_WORKSETS_CASE_PC){++s.cases;std::cout<<"WORKSET_PROGRESS cases="<<s.cases<<" index="<<(s.first+s.cases-1)<<" cycles="<<s.test->cycles<<std::endl;}
        }
    }
};
static uint64_t expectedWord(uint64_t n){return 0x729ad0513fe68bc4ULL^(0x0102040810204081ULL*n);}
static void oracle(const DdrModel& d,unsigned first,unsigned last,unsigned poison){
    auto at=[&](uint64_t pa){return d.memory.at(uint32_t(pa-ramBase));};
    check(at(MMU_SMOKE_SIGNATURE)==0x4d4d55574f524b53ULL&&at(MMU_SMOKE_SIGNATURE+8)==0&&
          at(MMU_SMOKE_SIGNATURE+16)==last-first&&at(MMU_SMOKE_SIGNATURE+48)==first&&at(MMU_SMOKE_SIGNATURE+56)==last,"worksets final complete signature");
    for(unsigned c=first;c<last;c++){
        unsigned mode=c<18?c/6:(c-18)/2,test=c<18?c%6:1,op=c<18?0:1+(c-18)%2;
        uint64_t pages=test<2?0:4ULL<<(test-2),count=pages?pages:test?16384:1024,passes=pages?128:test?1:8;
        uint64_t r[8];for(unsigned k=0;k<8;k++)r[k]=at(MMU_SMOKE_ENTRY+0x65000+c*64+k*8);
        if(poison==2&&c==first)r[3]^=1;
        check(r[0]==mode&&r[1]==test&&r[2]==op&&r[3]==count&&r[4]==passes&&r[5]>0,"independent workset coverage/count oracle");
        uint64_t sum=0;for(uint64_t n=0;n<count;n++)sum+=expectedWord(pages?n*520:n);
        if(poison==3&&c==first)r[7]^=1;
        check(r[7]==(op?0:sum*passes)&&(!op?r[6]==0:r[6]>0),"independent workset result/flush oracle");
    }
    const unsigned finalOp=last<=18?0:1+(last-19)%2;
    for(uint64_t n=0;n<16384;n++){
        uint64_t a=at(MMU_SMOKE_DATA_A+n*8),b=at(MMU_SMOKE_DATA_B+n*8);
        if(poison==1&&n==12031)b^=1;
        check(a==expectedWord(n)&&b==(finalOp==2?expectedWord(n):~expectedWord(n)),"independent full128KiB data oracle");
    }
}
int main(int argc,char** argv){try{
    check(argc==4||argc==5,"usage: worksets image.bin begin end [--inject-trap]");bool poison=argc==5&&std::string(argv[4])=="--inject-trap";
    size_t usedFirst=0,usedLast=0;
    auto rawFirst=std::stoull(argv[2],&usedFirst),rawLast=std::stoull(argv[3],&usedLast);
    check(usedFirst==std::string(argv[2]).size()&&usedLast==std::string(argv[3]).size()&&rawFirst<rawLast&&rawLast<=24,"worksets range input");
    unsigned first=unsigned(rawFirst),last=unsigned(rawLast);
    check(argc==4||poison,"unknown option");auto payload=readFile(argv[1]);check(!payload.empty()&&payload.size()<32768,"worksets guest size");
    Bytes rom;word(rom,uint32_t(MMU_SMOKE_ENTRY&0xfffff000ULL)|0x2b7);word(rom,0x02029293);word(rom,0x0202d293);word(rom,0x000280e7);word(rom,0x0000006f);
    Test t(rom);t.running=false;Observed s;s.test=&t;s.poisonTrap=poison;s.first=first;s.last=last;t.observer=Observed::sample;t.observerContext=&s;
    for(size_t off=0;off<payload.size();off+=8){uint64_t v=0;for(unsigned lane=0;lane<8&&off+lane<payload.size();lane++)v|=uint64_t(payload[off+lane])<<(lane*8);t.ddr.memory[uint32_t(MMU_SMOKE_ENTRY-ramBase+off)]=v;}
    t.ddr.memory[uint32_t(MMU_SMOKE_ENTRY+0x64000-ramBase)]=first;
    t.ddr.memory[uint32_t(MMU_SMOKE_ENTRY+0x64008-ramBase)]=last;
    bool done=false;while(t.cycles<24000000){t.tick();if(s.terminal&&t.ddr.pendingReads.empty()&&!t.ddr.heldRead&&!t.ddr.writing&&!t.ddr.responding&&!t.ddr.writeWaiting){done=true;break;}}
    check(done,"worksets bounded completion");
    std::cout<<"WORKSETS_SIGNATURE error="<<t.ddr.memory.at(uint32_t(MMU_SMOKE_SIGNATURE+8-ramBase))
             <<" cases="<<t.ddr.memory.at(uint32_t(MMU_SMOKE_SIGNATURE+16-ramBase))
             <<" cause="<<t.ddr.memory.at(uint32_t(MMU_SMOKE_SIGNATURE+24-ramBase))<<std::endl;
    check(s.traps==3+last-first&&s.cases==last-first,"worksets retirement/trap coverage");oracle(t.ddr,first,last,0);
    for(unsigned p=1;p<=3;p++){bool caught=false;try{oracle(t.ddr,first,last,p);}catch(const std::runtime_error&){caught=true;}check(caught,"worksets oracle poison escaped");}
    for(unsigned c=first;c<last;c++){std::cout<<"WORKSET_ROW index="<<c;for(unsigned k=0;k<8;k++)std::cout<<" "<<t.ddr.memory.at(uint32_t(MMU_SMOKE_ENTRY+0x65000+c*64+k*8-ramBase));std::cout<<"\n";}
    std::cout<<"BOOTROM_MMU_WORKSETS_PASS cycles="<<t.cycles<<" begin="<<first<<" end="<<last<<" faults=3 S_ecalls="<<(last-first)<<" full_buffers_verified_per_case=1 independent_final_words=32768 independent_row_oracles_per_segment=1 offline_oracle_poison_rejected=3 full54=0 FPGA=0\n";
}catch(const std::exception& e){std::cerr<<"BOOTROM_MMU_WORKSETS_FAIL "<<e.what()<<"\n";return 1;}}
