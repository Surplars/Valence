#pragma once
// Fixed host-generated architectural gold, independent of DUT.
constexpr uint64_t ncVa=0x40000000ULL, ncPa=ramBase+0x10000, ncRoot=ramBase+0x100000;
constexpr uint64_t ncWord=0x1122334455667788ULL, ncHandler=romBase+0x800;
struct SmokeExpected { uint64_t pc; uint32_t instruction; bool writes; unsigned rd; uint64_t value; };
struct SmokeProgram {
    Program image{"second_pmp_fault", "rom", {}, {}};
    std::vector<SmokeExpected> expected;
    std::string name;
    uint64_t badVa=ncPa,faultPc=0,warmPc=0,warmVa=ncPa,warmPa=ncPa;
    uint64_t cause=5,warmResult=ncWord;
    unsigned expectedPteReads=0,expectedDataReads=0;
    size_t beforeFault=0;
    bool vm=false,fp=false,storeFault=false,requireDtaFault=false,requirePtwFault=false;
    void emit(uint32_t ins,bool writes=false,unsigned rd=0,uint64_t value=0) {
        expected.push_back({romBase+4*image.code.size(),ins,writes,rd,value});image.code.push_back(ins);
    }
    void constant(unsigned rd,uint64_t value) {
        uint64_t current=value>>55;emit(imm(rd,0,int(current)),true,rd,current);
        for(int shift=44;shift>=0;shift-=11){current<<=11;emit(imm(rd,rd,11,1),true,rd,current);
            const unsigned part=(value>>shift)&2047;current+=part;emit(imm(rd,rd,int(part)),true,rd,current);}
        require(current==value,"SECOND_FAULT_CONSTANT_ORACLE");
    }
    void writeCsr(unsigned csr,uint64_t value){constant(10,value);emit(csr<<20|10u<<15|1u<<12|0x73);}
    uint32_t load(unsigned size=3) const{return 1u<<15|size<<12|2u<<7|3;}
    explicit SmokeProgram(const std::string &which):name(which) {
        writeCsr(0x305,ncHandler);
        vm=name=="vm-data-na4-low"||name=="vm-data-na4-high"||name=="vm-ptw-na4";
        fp=name=="fp-na4";
        storeFault=name=="locked-na4-store"||name=="mprv-tor-revoke-store";
        require(vm||fp||storeFault||name=="mprv-tor-revoke-load","SECOND_FAULT_FIXED_CASE_NAME");
        cause=storeFault?7:5;
        if(name.rfind("mprv-tor-revoke",0)==0) {
            writeCsr(0x3b0,0x40000000);writeCsr(0x3a0,0x0f);
            writeCsr(0x300,0x20800); // MPRV, MPP=S, Bare data.
            constant(1,ncPa);warmPc=romBase+4*image.code.size();
            emit(load(),true,2,ncWord);expectedDataReads=1;
            emit(0x0330000f);writeCsr(0x3a0,0x08); // Real CSR revoke, legal TOR with no permissions.
        } else {
            const uint64_t narrow=name=="vm-ptw-na4"?ncRoot+8:
                name=="vm-data-na4-high"?ncPa+4:ncPa;
            writeCsr(0x3b0,narrow>>2);writeCsr(0x3b1,(uint64_t(1)<<54)-1);
            // Later full56 NAPOT cannot rescue an earlier partial overlap.
            // Locked read-only NA4 has R=1,W=0; no unreachable W-only CSR state.
            writeCsr(0x3a0,0x1f00|(name=="locked-na4-store"?0x91:0x11));
            if(vm) {
                writeCsr(0x180,(8ULL<<60)|(ncRoot>>12));emit(0x12000073);
                writeCsr(0x300,0x20800);badVa=ncVa;
                if(name!="vm-ptw-na4") {
                    // Neighbor is outside NA4 but in the same page, warming
                    // translation without authorizing the denied eight bytes.
                    warmVa=ncVa+8;warmPa=ncPa+8;constant(1,warmVa);
                    warmPc=romBase+4*image.code.size();emit(load(),true,2,ncWord);
                    expectedPteReads=3;expectedDataReads=1;emit(0x0330000f);
                    requireDtaFault=true;
                } else requirePtwFault=true;
            } else if(fp) writeCsr(0x300,0x2000); // FS=Initial; Bare M.
            else {
                constant(1,ncPa);warmPc=romBase+4*image.code.size();warmResult=0x55667788;
                emit(load(2),true,2,warmResult);expectedDataReads=1;emit(0x0330000f);
            }
        }
        constant(1,badVa);
        if(storeFault) {
            constant(3,0x1122);
            // Fixed causal window: a high-dividend DIVU immediately precedes
            // the independent faulting store. Both store operands are ready
            // before DIVU becomes head; the iterative divider lets head+1
            // numerical preparation finish without service-law changes/padding.
            constexpr uint64_t dividend=0xfedcba9876543210ULL;
            constant(6,dividend);constant(7,3);
            emit((1u<<25)|(7u<<20)|(6u<<15)|(5u<<12)|(5u<<7)|0x33,
                true,5,dividend/3);
        }
        faultPc=romBase+4*image.code.size();beforeFault=expected.size();
        const uint32_t faultInst=fp?(1u<<15|3u<<12|1u<<7|7):storeFault?
            (3u<<20|1u<<15|(name=="locked-na4-store"?2u:3u)<<12|0x23):
            (1u<<15|3u<<12|4u<<7|3);
        image.code.push_back(faultInst); // Faulting instruction never retires.
        image.code.push_back(ebreak); // Wrong-path sentinel must not complete.
        while(romBase+4*image.code.size()<ncHandler)image.code.push_back(nop);
        require(romBase+4*image.code.size()==ncHandler,"SECOND_FAULT_HANDLER_APERTURE");
        emit(0x34202073u|21u<<7,true,21,cause);
        emit(0x34302073u|22u<<7,true,22,badVa);
        emit(0x34102073u|23u<<7,true,23,faultPc);
        image.code.push_back(ebreak);
    }
    uint64_t pte(uint64_t address) const {
        require(vm && !requirePtwFault,"SECOND_FAULT_FORBIDDEN_PTE_REQUEST");
        if(address==ncRoot+8)return ((ncRoot+4096)>>12)<<10|1;
        if(address==ncRoot+4096)return ((ncRoot+8192)>>12)<<10|1;
        if(address==ncRoot+8192)return (ncPa>>12)<<10|0xc7;
        throw std::runtime_error("SECOND_FAULT_PTE_OUTSIDE_FIXED_TABLE");
    }
    uint64_t physical()const{return ncPa;}
};
