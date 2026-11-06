// The independent CoreMark/ISA and prediction oracles stay byte-identical.
// This H/S/U fixture has one additional external supervisor IRQ input.
#include "I1PerformanceCachedCore.h"
class HypervisorCoreMarkModel : public SI1PerformanceCachedCore {
public:
    HypervisorCoreMarkModel() { set_io$$supervisorExternalIrq(0); }
};
#define SI1PerformanceCachedCore HypervisorCoreMarkModel
#include "five_stage_coremark.cpp"
