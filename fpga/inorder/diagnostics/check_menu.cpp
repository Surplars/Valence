// Firmware-only regression on the unchanged batch44 CPU/Sv39/cache/TL/AXI model.
#define FIVE_STAGE_SOC_MEMORY_ONLY
#include "five_stage_soc.cpp"
#include "five_stage_coherent_readback.h"

struct UartReceiver {
    bool previous=true, busy=false;
    double sample=0;
    unsigned bit=0, value=0;
    std::string text;
    void tick(uint64_t cycle, bool line) {
        constexpr double period=300000000.0/460800.0;
        if(!busy && previous && !line) { busy=true; sample=cycle+period*.5; bit=0; value=0; }
        if(busy && double(cycle)>=sample) {
            if(bit==0) need(!line,"independent UART start bit");
            else if(bit<=8) value|=unsigned(line)<<(bit-1);
            else { need(line,"independent UART stop bit"); text+=char(value); busy=false; }
            ++bit; sample+=period;
        }
        previous=line;
    }
};

int main(int argc,char **argv) { try {
    need(argc>=3,"binary and receipt address required; optional --uart / --wrong-result");
    const bool uart=argc>3 && std::string(argv[3])=="--uart";
    const bool wrong=argc>3 && std::string(argv[3])=="--wrong-result";
    std::ifstream input(argv[1],std::ios::binary); need(bool(input),"missing firmware");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(input)),{});
    const uint64_t ledger=std::stoull(argv[2],nullptr,0);
    SFiveStageSoc d; AxiMemory memory(d,image,false,false);
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(1); d.set_io$$ddrReady(1); d.set_io$$jtagLinkUp(0);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(1);
    i1CoherentHostIdle(d);
    memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    UartReceiver receiver;
    const std::string banner="\r\nValence I1 Diagnostics V0.1 / CPU300 / UART460800\r\n";
    uint64_t instructions=0, cycle=0, lastPc=0, ecalls=0, pageFaults=0;
    bool finished=false;
    for(;cycle<3000000;++cycle) {
        memory.inputs(cycle); d.step(); memory.outputs(cycle);
        if(uart) {
            receiver.tick(cycle,d.get_io$$uartTx());
            need(receiver.text.size()<=banner.size() && receiver.text==banner.substr(0,receiver.text.size()),
                 "independent menu UART banner mismatch");
            if(receiver.text==banner) { finished=true; break; }
        }
        if(!d.get_io$$retire$$valid()) continue;
        ++instructions;
        uint64_t pc=d.get_io$$retire$$bits$$pc(); lastPc=pc;
        if(d.get_io$$retire$$bits$$trap()) {
            const auto cause=d.get_io$$retire$$bits$$cause();
            if(cause==9) ++ecalls;
            else if(cause==13) ++pageFaults;
            else if(cause==3 && !uart) { finished=true; break; }
            else throw std::runtime_error("unexpected diagnostic firmware trap: "+std::to_string(cause));
        } else {
            need(pc>=0x80200000ULL && pc+4<=0x80200000ULL+image.size(),"retire outside immutable firmware text");
            uint32_t expected=0;
            for(unsigned n=0;n<4;++n) expected|=uint32_t(image[pc-0x80200000ULL+n])<<(8*n);
            need(expected==d.get_io$$retire$$bits$$instruction(),"independent retired instruction bytes");
        }
    }
    if(!finished) {
        std::cerr<<"STALL cycle="<<cycle<<" retired="<<instructions<<" pc=0x"<<std::hex<<lastPc<<std::dec<<'\n';
        throw std::runtime_error("bounded menu firmware completion");
    }
    if(uart) {
        std::cout<<receiver.text<<"I1_MENU_UART_PASS cycles="<<cycle<<" bytes="<<receiver.text.size()
            <<" baud=460800 single_clock_model_not_physical_CDC=1\n";
        return 0;
    }
    need(ecalls==2 && pageFaults==1,"two real S-mode returns and one precise unmapped-page fault required");
    for(uint64_t row=ledger&~63ULL;row<ledger+32*8;row+=64)
        coherentRead(d,memory,cycle,row-0x80200000ULL);
    auto value=[&](unsigned n) { return memory.load(ledger-0x80200000ULL+n*8); };
    need(value(0)==0x4931444941473031ULL && value(1)==1 && value(2)==0,"firmware short-check completion ledger");
    const uint64_t sum=32ULL*0x123400000000ULL+32*31/2;
    need(value(3)==(wrong?sum^1:sum) && value(4)==sum,"independent Bare/Sv39 checksum oracle");
    need(value(5)==13 && value(6)==0x45000000ULL,"independent nonidentity Sv39 fault ledger");
    for(unsigned i=8;i<16;++i) need(value(i)>0,"real bandwidth timing missing");
    const uint64_t crc[]={0xe9f5,0xe714,0x1fd7,0x8e3a,0xe714};
    for(unsigned i=0;i<5;++i) need(value(16+i)==crc[i],"independent official CoreMark one-iteration CRC oracle");
    need(value(21)>value(22) && value(22)>100000 && value(23)>0 && value(24)==1,"real CoreMark counter/iteration ledger");
    for(uint64_t base:{0x81000000ULL,0x83000040ULL}) {
        for(unsigned offset=0;offset<256;offset+=64) coherentRead(d,memory,cycle,base-0x80200000ULL+offset);
        for(unsigned word=0;word<32;++word)
            need(memory.load(base-0x80200000ULL+word*8)==0x123400000000ULL+word,
                 "independent final DDR byte/pattern oracle");
    }
    std::cout<<"I1_MENU_SHORT_PASS cycles="<<cycle<<" retired="<<instructions<<" S_ecalls="<<ecalls
        <<" page_faults="<<pageFaults<<" CoreMark_ROI_cycles="<<value(21)<<" CoreMark_ROI_instructions="<<value(22)
        <<" bare_sv39_four_streams_full_data_and_CRC=PASS formal_score=0\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
