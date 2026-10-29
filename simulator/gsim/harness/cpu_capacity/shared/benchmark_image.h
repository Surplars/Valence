#pragma once
#include "matched_memory.h"
#include <elf.h>
#include <fstream>
#include <cstring>
#include <sstream>
namespace matched {
struct Image {
    Memory memory;
    std::map<std::string,uint64_t> symbols;
    uint64_t entry=0;
    Image(const std::string&elf,const std::string&sym) {
        std::ifstream f(elf,std::ios::binary); require(bool(f),"cannot open ELF");
        std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(f)),{});
        require(bytes.size()>=sizeof(Elf64_Ehdr),"short ELF"); Elf64_Ehdr h;std::memcpy(&h,bytes.data(),sizeof h);
        require(!std::memcmp(h.e_ident,ELFMAG,SELFMAG)&&h.e_ident[EI_CLASS]==ELFCLASS64&&h.e_ident[EI_DATA]==ELFDATA2LSB&&h.e_machine==EM_RISCV&&h.e_type==ET_EXEC,"ELF must be little-endian RV64 executable");
        require(h.e_phentsize==sizeof(Elf64_Phdr)&&h.e_phoff<=bytes.size()&&uint64_t(h.e_phnum)*h.e_phentsize<=bytes.size()-h.e_phoff,"invalid ELF program headers");
        for(unsigned i=0;i<h.e_phnum;++i){Elf64_Phdr p;std::memcpy(&p,bytes.data()+h.e_phoff+i*sizeof p,sizeof p);if(p.p_type!=PT_LOAD)continue;
            require(p.p_paddr==p.p_vaddr&&p.p_filesz<=p.p_memsz&&memory.inRam(p.p_paddr,p.p_memsz)&&p.p_offset<=bytes.size()&&p.p_filesz<=bytes.size()-p.p_offset,"ELF load segment outside RAM or truncated");
            std::copy(bytes.begin()+p.p_offset,bytes.begin()+p.p_offset+p.p_filesz,memory.ram.begin()+p.p_paddr-RamBase);
        }
        entry=h.e_entry;require(entry==RamBase,"ELF entry must match common ROM trampoline");
        std::ifstream sf(sym);require(bool(sf),"cannot open symbols");std::string line;
        while(std::getline(sf,line)){std::istringstream s(line);uint64_t a;char kind;std::string name;if(s>>std::hex>>a>>kind>>name)symbols[name]=a;}
        for(const char*n:{"roi_begin","roi_end","benchmark_complete","benchmark_terminal"})require(symbols.count(n),std::string("missing symbol ")+n);
    }
};
}
