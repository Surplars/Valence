#define FIVE_STAGE_SOC_MEMORY_ONLY
#include "five_stage_soc.cpp"
#include "five_stage_rom_host.h"
#include <cmath>

struct UartReceive {
    bool previous=true, busy=false;
    double sample=0;
    unsigned bit=0, value=0;
    std::string text;
    void tick(uint64_t cycle, bool line) {
        constexpr double period=100000000.0/460800.0;
        if(!busy && previous && !line) { busy=true; sample=cycle+period*0.5; bit=0; value=0; }
        if(busy && double(cycle)>=sample) {
            if(bit==0) need(!line,"actual UART start-bit oracle");
            else if(bit<=8) value|=unsigned(line)<<(bit-1);
            else {
                need(line,"actual UART stop-bit oracle"); text+=char(value);
                std::cout<<char(value)<<std::flush; busy=false;
            }
            ++bit; sample+=period;
        }
        previous=line;
    }
};

int main(int argc,char **argv) { try {
    need(argc>=5,"stock OpenSBI shim/firmware/S-payload/DTB paths required");
    bool mutate=argc>5 && std::string(argv[5])=="--wrong-handoff";
    SFiveStageSoc d; AxiMemory memory(d,{},false,false);
    const uint64_t addresses[]={0x80200000,0x80280000,0x80400000,0x80500000};
    for(unsigned s=0;s<4;++s) {
        std::ifstream file(argv[s+1],std::ios::binary); need(bool(file),"missing stock firmware segment");
        std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)),{});
        for(size_t j=0;j<data.size();++j) memory.bytes[addresses[s]-0x80200000+j]=data[j];
    }
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(1); d.set_io$$ddrReady(1); d.set_io$$jtagLinkUp(0);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(0);
    i1InitializeRom(d,memory,"src/main/resources/inorder/bootrom.hex");
    memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    uint64_t retired=0,ecalls=0,sTimer=0,mrets=0,sRetired=0,lastPc=0,traps=0;
    UartReceive uart;
    std::deque<std::array<uint64_t,3>> recent;
    std::array<uint64_t,32> registers{};
    for(uint64_t cycle=0;cycle<48000000;++cycle) {
        memory.inputs(cycle); d.step(); memory.outputs(cycle); uart.tick(cycle,d.get_io$$uartTx());
        if(d.get_io$$trapTaken()) {
            ++traps; auto cause=d.get_io$$trapCause();
            ecalls+=cause==9; sTimer+=cause==0x8000000000000005ULL;
            if(traps<32) std::cerr<<"TRAP cause=0x"<<std::hex<<cause<<" last_pc=0x"<<lastPc<<std::dec<<'\n';
        }
        if(d.get_io$$retire$$valid()) {
            ++retired; lastPc=d.get_io$$retire$$bits$$pc(); auto ins=d.get_io$$retire$$bits$$instruction();
            recent.push_back({lastPc,ins,d.get_io$$retire$$bits$$data()}); if(recent.size()>64) recent.pop_front();
            if(d.get_io$$retire$$bits$$writesRd() && d.get_io$$retire$$bits$$rd()!=0)
                registers[d.get_io$$retire$$bits$$rd()]=d.get_io$$retire$$bits$$data();
            // Pinned stock ELF's intentional fatal loop: stop once, preserve its real call chain.
            if(lastPc==0x80285640) {
                for(auto r:recent) std::cerr<<"PRE_HANG "<<std::hex<<r[0]<<' '<<r[1]<<' '<<r[2]<<std::dec<<'\n';
                for(unsigned n=0;n<32;++n) std::cerr<<"REG "<<n<<" 0x"<<std::hex<<registers[n]<<std::dec<<'\n';
                throw std::runtime_error("stock OpenSBI intentionally entered sbi_hart_hang");
            }
            if(!d.get_io$$retire$$bits$$trap()) {
                sRetired+=lastPc>=0x80400000 && lastPc<0x80401000; mrets+=ins==0x30200073;
                // Compare the retired raw 16/32-bit encoding with externally owned physical RAM.
                if(lastPc>=0x80200000 && lastPc<0x100200000ULL) {
                    uint32_t expected=0; unsigned length=(ins&3)==3?4:2;
                    for(unsigned j=0;j<length;++j) expected|=uint32_t(memory.bytes[lastPc-0x80200000+j])<<(8*j);
                    need(ins==expected,"independent OpenSBI retired byte oracle");
                } else need(lastPc>=0x10000 && lastPc<0x11000,"OpenSBI retired outside executable map");
            }
        }
        if(cycle%1000!=0) continue;
        if(cycle && cycle%4000000==0)
            std::cerr<<"BOOT_PROGRESS cycles="<<cycle<<" retired="<<retired<<" pc=0x"<<std::hex<<lastPc
                <<" ra=0x"<<registers[1]<<std::dec<<" UART_bytes="<<uart.text.size()<<" S_retired="<<sRetired<<'\n';
        auto marker=memory.load(0x210030);
        if(marker==0xbad) {
            for(auto r:recent) std::cerr<<"RECENT "<<std::hex<<r[0]<<' '<<r[1]<<' '<<r[2]<<std::dec<<'\n';
            throw std::runtime_error("actual OpenSBI S-mode payload fail path");
        }
        if(marker==0x534d4f4445504153ULL && !uart.busy) {
            need(memory.load(0x210000)==0 && memory.load(0x210008)==0x80500000 &&
                (memory.load(0x210010)>>24)==3 && memory.load(0x210018)!=0 &&
                memory.load(0x210020)==12 && memory.load(0x210028)==1 &&
                marker==(mutate?0ULL:0x534d4f4445504153ULL),"independent stock OpenSBI handoff ledger oracle");
            need(ecalls>=35 && sTimer>0 && mrets>0 && sRetired>50,"actual privilege/ECALL/timer coverage");
            need(uart.text.find("OpenSBI v1.9")!=std::string::npos &&
                uart.text.find("ORBITAL_I1_OPENSBI_S_MODE_PASS")!=std::string::npos,"actual UART firmware banners missing");
            std::cout<<"\nFIVE_STAGE_STOCK_OPENSBI_S_PASS cycles="<<cycle<<" retired="<<retired
                <<" SBI_S_ecalls="<<ecalls<<" S_timer_irqs="<<sTimer<<" MRET="<<mrets
                <<" S_retired="<<sRetired<<" UART_bytes="<<uart.text.size()
                <<" stock_unmodified_SBIv3_TIME_DBCN_S_ATOMICS=PASS\n"; return 0;
        }
    }
    std::cerr<<"OPENSBI_STALL pc=0x"<<std::hex<<lastPc<<" marker=0x"<<memory.load(0x210030)<<std::dec
        <<" retired="<<retired<<" traps="<<traps<<" axi_reads="<<memory.readCount<<" axi_writes="<<memory.writeCount<<'\n';
    for(auto r:recent) std::cerr<<"RECENT "<<std::hex<<r[0]<<' '<<r[1]<<' '<<r[2]<<std::dec<<'\n';
    throw std::runtime_error("stock OpenSBI bounded boot/handoff failed");
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
