#pragma once
#include <cstdint>
#include <stdexcept>
#ifndef ROB_ENTRIES
#error ROB_ENTRIES must be supplied from the validated actual full profile
#endif
#ifndef PHYSICAL_REGS
#error PHYSICAL_REGS must be supplied from the validated actual full profile
#endif
#ifndef LSU_ENTRIES
#error LSU_ENTRIES must be supplied from the validated actual full profile
#endif
namespace capacity {
constexpr unsigned robEntries=ROB_ENTRIES, physicalRegs=PHYSICAL_REGS, lsuEntries=LSU_ENTRIES;
static_assert(robEntries==16||robEntries==32||robEntries==64);
static_assert(physicalRegs==48||physicalRegs==64);
static_assert(lsuEntries==4);
constexpr unsigned robBits=robEntries==16?4:robEntries==32?5:6;
inline uint64_t mask(unsigned i){if(i>=robEntries)throw std::runtime_error("ROB index out of range");return uint64_t(1)<<i;}
inline unsigned age(unsigned i,unsigned head){if(i>=robEntries||head>=robEntries)throw std::runtime_error("ROB age index out of range");return (i+robEntries-head)%robEntries;}
inline unsigned advance(unsigned head,unsigned n){if(head>=robEntries||n>2)throw std::runtime_error("ROB head/retire range");return (head+n)%robEntries;}
}
