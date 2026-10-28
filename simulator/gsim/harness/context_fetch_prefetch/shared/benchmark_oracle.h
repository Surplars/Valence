#pragma once
#include "benchmark_image.h"
#include <iostream>
#include <iomanip>
namespace benchmark_oracle {
using Memory=std::vector<uint8_t>;
constexpr uint64_t dataBase=matched::RamBase;
#include "isa_model.h"
struct Event {uint64_t pc,nextPc,data;uint32_t instruction;unsigned rd;bool writes;};
struct Store {uint64_t address,data;unsigned size;};
class Oracle {
public:
    matched::Memory memory;
    std::array<uint64_t,32> regs{};
    uint64_t pc=matched::RomBase,retired=0,beginCount=0,endCount=0,hash=1469598103934665603ULL;
    std::vector<Store> stores;
    explicit Oracle(const matched::Image&i):memory(i.memory){}
    void mix(uint64_t v){for(unsigned i=0;i<8;++i){hash^=uint8_t(v>>(8*i));hash*=1099511628211ULL;}}
    Event step(){
        const uint32_t inst=uint32_t(memory.read(pc,4));matched::require(inst!=0x00100073,"oracle reached EBREAK before retire event");
        Event out{pc,pc+4,0,inst,0,false};
        if((inst&0x707f)==0xf){ /* RV64 FENCE: single hart, no external writers. */ }
        else if((inst&0x707f)==0x1073){
            const unsigned csr=inst>>20,rd=(inst>>7)&31;
            matched::require(rd==0&&(csr==0x3a0||csr==0x3b0||(csr==0x304&&((inst>>15)&31)==0)),"oracle unsupported CSR operation");
        }else{
            const auto*e=decode(inst);matched::require(e!=nullptr,"oracle unsupported instruction at "+std::to_string(pc));
            matched::require(e->alu<=9 || e->mulDiv,"oracle common ISA excludes non-IM operations");
            const auto result=interpret(*e,inst,pc,regs,memory.ram);matched::require(!result.fault,"oracle guest fault");
            out.nextPc=result.nextPc;out.rd=result.rd;out.writes=result.rd!=0;out.data=result.result;
            if(e->memory==2){
                const unsigned bytes=1u<<((inst>>12)&3);const uint64_t value=regs[(inst>>20)&31];
                stores.push_back({result.target,value,bytes});
                for(unsigned b=0;b<bytes;++b)memory.ram.at(result.target-dataBase+b)=uint8_t(value>>(8*b));
            }
            if(out.writes)regs[out.rd]=out.data;
        }
        regs[0]=0;pc=out.nextPc;++retired;mix(out.pc);mix(out.instruction);mix(out.writes?out.data:0);return out;
    }
    void run(const matched::Image&i,uint64_t bound=10000000){
        while(pc!=i.symbols.at("benchmark_terminal")&&retired<bound){if(pc==i.symbols.at("roi_begin")){matched::require(!beginCount,"duplicate ROI begin");beginCount=retired;}if(pc==i.symbols.at("roi_end")){matched::require(beginCount&&!endCount,"unmatched ROI end");endCount=retired;}step();}
        matched::require(pc==i.symbols.at("benchmark_terminal")&&memory.read(pc,4)==0x00100073,"oracle terminal not reached");
        matched::require(beginCount&&endCount>beginCount,"oracle ROI markers missing");
        matched::require(regs[10]==0&&regs[12]==1&&regs[14]==63&&regs[15]==0x434d41524bULL,"canonical CRC/completion signature failed in independent ISA oracle");
    }
};
}
