#define main guest_instruction_base_suite_main
#include "guest_instruction_assembler.cpp"
#undef main
int main(){try{
    Bench b;
    for(bool guest:{false,true})for(uint32_t word:{uint32_t(0x0001),uint32_t(0x05aa0093)}){
        auto t=instruction(word);t.c.name=guest?"guest Bare assembly provenance":"host Bare assembly provenance";
        t.c.q.guest=guest;t.c.q.vsatp=0;t.c.q.hgatp=guest?0:MODE|0x200;t.c.q.epoch=guest?203:107;
        t.code.clear();t.firstPa=t.c.q.va;t.secondPa=t.firstPa+2;t.code[t.firstPa]=word&65535;
        if(t.bytes==4)t.code[t.secondPa]=word>>16;b.run(t);
    }
    std::cout<<"GUEST_INSTRUCTION_HOST_PROVENANCE_PASS instructions="<<b.instructions<<" parcels="<<b.parcels<<" physical_reads="<<b.physicalReads<<" pte_reads="<<b.pteReads<<" cycles="<<b.cycles<<"\n";
    return 0;
}catch(const std::exception& e){std::cerr<<"GUEST_INSTRUCTION_HOST_PROVENANCE_FAIL "<<e.what()<<"\n";return 1;}}
