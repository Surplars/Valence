// Correctness-only adapter over the exact receipt-bound board service host.
// No model mutation, injected requests, architectural resynchronization, or score.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#define HOT_BYTES 64
#include "board_nemu_observer.h"

static void seedDut(Test &test,const Bytes &image) {
    // External RAM input, specified independently of all DUT observations.
    for(size_t offset=0;offset<image.size();offset+=8) {
        uint64_t value=0;
        for(unsigned b=0;b<8&&offset+b<image.size();++b)value|=uint64_t(image[offset+b])<<(8*b);
        test.ddr.memory[uint32_t(offset)]=value;
    }
    for(unsigned i=0;i<8;++i) {
        test.ddr.memory[0x200000+8*i]=0x10203040ULL+i;
        test.ddr.memory[0x202000+8*i]=~(0x10203040ULL+i);
    }
    for(unsigned i=0;i<4;++i)test.ddr.memory[0x400000+8*i]=0xdeadbeef;
}

int main(int argc,char **argv) {try {
    check(argc==5||argc==6,"usage: current_board_nemu guest.bin nemu.so done_pc hot|compressed [--inject-nemu-pc|gpr|memory]");
    const auto image=readFile(argv[1]);
    const std::string kind=argv[4], injection=argc==6?argv[5]:"";
    check(kind=="hot"||kind=="compressed","unknown correctness input");
    check(injection.empty()||injection=="--inject-nemu-pc"||injection=="--inject-nemu-gpr"||
        injection=="--inject-nemu-memory","unknown NEMU mutation");
    board_nemu::Observer observer;
    observer.initialize(image,argv[2],injection,std::stoull(argv[3],nullptr,0),kind=="compressed");
    Bytes rom;
    // Preserve the independently specified old boot GPR effects without UART
    // MMIO: the current board's original fabric service must remain idle.
    for(uint32_t instruction:{0x00200297U,0x10000337U,0x00700393U,0x00000013U,0x000280e7U,0x0000006fU})word(rom,instruction);
    Test test(rom,[](SBoardSocGsim &d,void *context){static_cast<board_nemu::Observer*>(context)->sample(d);},&observer);
    seedDut(test,image);
    const auto deadline=test.cycles+30000;
    while(!observer.finalized&&test.cycles<deadline) {
        test.tick();check(test.received.empty(),"unexpected correctness input UART output");
    }
    check(observer.finalized,"bounded correctness input did not retire its done marker");
    observer.verifyMemory(test);
    check(observer.branchesRetired>0&&observer.controlTransfers>0,"branch/control-flow coverage missing");
    if(kind=="compressed") {
        check(observer.compressedRetired>=6&&observer.takenBranches>=2,"compressed call/return/taken-branch coverage missing");
        check(test.ddr.memory.at(0x400000)==9,"independent compressed signature mismatch");
    } else {
        check(observer.compressedRetired==0,"fixed-width hot input changed");
        for(unsigned i=0;i<8;++i)check(test.ddr.memory.at(0x202000+8*i)==0x10203040ULL+i,"independent hot copy mismatch");
        const std::array<uint64_t,4> signature{0,64,2,1};
        for(unsigned i=0;i<4;++i)check(test.ddr.memory.at(0x400000+8*i)==signature[i],"independent hot signature mismatch");
    }
    test.fabric.finish();
    observer.report();
    std::cout<<"CURRENT_BOARD_NEMU_PASS kind="<<kind<<" correctness_only=1 dma_idle=1 cycles="<<test.cycles<<"\n";
    return 0;
} catch(const std::exception &error) {std::cerr<<"CURRENT_BOARD_NEMU_FAIL "<<error.what()<<"\n";return 1;}}
