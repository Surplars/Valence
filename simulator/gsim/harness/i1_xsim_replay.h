#pragma once
// Replay adapter only: CPU values below come from a completed Windows xsim trace.
// The existing independent Memory server checks every response/input handshake,
// and the existing ISA/CRC/final-RAM/prediction oracles remain unchanged.
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
class SI1PerformanceCachedCore {
    std::ifstream trace;
    uint64_t flags=0,nextCycle=0;
    bool reset=true;
    struct Inputs {bool ready=false,valid=false,error=false,last=false;uint64_t data=0;};
    std::array<Inputs,2> expected{};
    std::array<std::array<uint64_t,5>,2> requests{};
    std::array<uint64_t,2> response{};
    std::array<uint64_t,10> retirement{};
    std::array<uint64_t,3> prediction{};
    static void require(bool value,const std::string &message) {
        if(!value)throw std::runtime_error(message);
    }
    uint64_t bit(unsigned number) const {return (flags>>number)&1;}
public:
    SI1PerformanceCachedCore() {
        const char *file=std::getenv("VALENCE_XSIM_TRACE");
        require(file,"VALENCE_XSIM_TRACE is required");trace.open(file);require(bool(trace),"missing xsim trace");
    }
    void set_reset(bool value){reset=value;}
    void set_io$$time(uint64_t){}
    void set_io$$externalIrq(bool){}
    void set_io$$timerIrq(bool){}
    void set_io$$softwareIrq(bool){}
    void step(){
        if(reset)return;
        std::string line;require(bool(std::getline(trace,line)),"XSIM trace ended before CPU completion");
        std::istringstream first(line);char kind;uint64_t cycle;
        first>>kind>>cycle>>std::hex>>flags;
        require(bool(first)&&kind=='C'&&cycle==nextCycle,"XSIM trace cycle framing mismatch");
        retirement.fill(0);prediction.fill(0);response.fill(0);for(auto &q:requests)q.fill(0);
        std::array<bool,2> qSeen{},vSeen{};bool rSeen=false,pSeen=false,end=false,closed=false;
        while(std::getline(trace,line)){
            std::istringstream row(line);row>>kind;
            if(kind=='Z'){closed=true;break;}
            if(kind=='E'){end=true;continue;}
            row>>std::hex;
            if(kind=='Q'){
                unsigned port;row>>port;require(port<2&&!qSeen[port],"XSIM duplicate request trace");
                for(auto &v:requests[port])row>>v;qSeen[port]=true;
            }else if(kind=='V'){
                unsigned port;row>>port;require(port<2&&!vSeen[port],"XSIM duplicate response trace");
                row>>response[port];vSeen[port]=true;
            }else if(kind=='R'){
                require(!rSeen,"XSIM duplicate retirement");for(auto &v:retirement)row>>v;rSeen=true;
            }else if(kind=='P'){
                require(!pSeen,"XSIM duplicate prediction resolution");for(auto &v:prediction)row>>v;pSeen=true;
            }else require(false,"XSIM unknown trace record");
            require(bool(row),"XSIM trace contains an unknown or malformed value");
        }
        require(closed,"XSIM incomplete trace frame");
        require(rSeen==bool(bit(17))&&pSeen==bool(bit(6)),"XSIM missing observed owner record");
        for(unsigned port=0;port<2;++port){
            require(qSeen[port]==bool(bit(13+port)),"XSIM missing request payload");
            require(vSeen[port]==bool(bit(20+port)),"XSIM missing response payload");
            require(expected[port].ready==bool(bit(18+port)),"XSIM replay request READY mismatch");
            require(expected[port].valid==bool(bit(20+port)),"XSIM replay response VALID mismatch");
            if(expected[port].valid){
                require(expected[port].data==response[port]&&expected[port].error==bool(bit(22+port))&&
                    expected[port].last==bool(bit(24+port)),"XSIM replay independent memory response mismatch");
            }
        }
        if(bit(17)&&retirement[6])require(end,"XSIM CPU stop lacks a completed simulation marker");
        ++nextCycle;
    }
    uint64_t get_io$$branchMispredict() const {return this->bit(0);}
    uint64_t get_io$$stallFetch() const {return this->bit(1);}
    uint64_t get_io$$stallMemory() const {return this->bit(2);}
    uint64_t get_io$$stallLoadUse() const {return this->bit(3);}
    uint64_t get_io$$stallMulDiv() const {return this->bit(4);}
    uint64_t get_io$$dataRequestAccepted() const {return this->bit(5);}
    uint64_t get_observation$$resolveValid() const {return this->bit(6);}
    uint64_t get_io$$instructionHit() const {return this->bit(7);}
    uint64_t get_io$$instructionMiss() const {return this->bit(8);}
    uint64_t get_io$$dataHit() const {return this->bit(9);}
    uint64_t get_io$$dataMiss() const {return this->bit(10);}
    uint64_t get_io$$stallStoreAck() const {return this->bit(11);}
    uint64_t get_io$$dataRequestOffered() const {return this->bit(12);}
    uint64_t get_io$$retire$$valid() const {return this->bit(17);}
    uint64_t get_io$$trapTaken() const {return this->bit(26);}
    uint64_t get_io$$retire$$bits$$pc() const {return retirement[0];}
    uint64_t get_io$$retire$$bits$$instruction() const {return retirement[1];}
    uint64_t get_io$$retire$$bits$$rd() const {return retirement[2];}
    uint64_t get_io$$retire$$bits$$writesRd() const {return retirement[3];}
    uint64_t get_io$$retire$$bits$$data() const {return retirement[4];}
    uint64_t get_io$$retire$$bits$$nextPc() const {return retirement[5];}
    uint64_t get_io$$retire$$bits$$trap() const {return retirement[6];}
    uint64_t get_io$$retire$$bits$$cause() const {return retirement[7];}
    uint64_t get_io$$retire$$bits$$tval() const {return retirement[8];}
    uint64_t get_observation$$retiredPrediction() const {return retirement[9];}
    uint64_t get_observation$$resolvePc() const {return prediction[0];}
    uint64_t get_observation$$resolvePrediction() const {return prediction[1];}
    uint64_t get_observation$$resolveNextPc() const {return prediction[2];}
    uint64_t get_io$$instructionMemory$$request$$valid() const {return bit(13);}
    uint64_t get_io$$instructionMemory$$response$$ready() const {return bit(15);}
    uint64_t get_io$$instructionMemory$$request$$bits$$address() const {return requests[0][0];}
    uint64_t get_io$$instructionMemory$$request$$bits$$write() const {return requests[0][1];}
    uint64_t get_io$$instructionMemory$$request$$bits$$data() const {return requests[0][2];}
    uint64_t get_io$$instructionMemory$$request$$bits$$mask() const {return requests[0][3];}
    uint64_t get_io$$instructionMemory$$request$$bits$$beats() const {return requests[0][4];}
    void set_io$$instructionMemory$$request$$ready(bool v){expected[0].ready=v;}
    void set_io$$instructionMemory$$response$$valid(bool v){expected[0].valid=v;}
    void set_io$$instructionMemory$$response$$bits$$error(bool v){expected[0].error=v;}
    void set_io$$instructionMemory$$response$$bits$$last(bool v){expected[0].last=v;}
    void set_io$$instructionMemory$$response$$bits$$data(uint64_t v){expected[0].data=v;}
    uint64_t get_io$$dataMemory$$request$$valid() const {return bit(14);}
    uint64_t get_io$$dataMemory$$response$$ready() const {return bit(16);}
    uint64_t get_io$$dataMemory$$request$$bits$$address() const {return requests[1][0];}
    uint64_t get_io$$dataMemory$$request$$bits$$write() const {return requests[1][1];}
    uint64_t get_io$$dataMemory$$request$$bits$$data() const {return requests[1][2];}
    uint64_t get_io$$dataMemory$$request$$bits$$mask() const {return requests[1][3];}
    uint64_t get_io$$dataMemory$$request$$bits$$beats() const {return requests[1][4];}
    void set_io$$dataMemory$$request$$ready(bool v){expected[1].ready=v;}
    void set_io$$dataMemory$$response$$valid(bool v){expected[1].valid=v;}
    void set_io$$dataMemory$$response$$bits$$error(bool v){expected[1].error=v;}
    void set_io$$dataMemory$$response$$bits$$last(bool v){expected[1].last=v;}
    void set_io$$dataMemory$$response$$bits$$data(uint64_t v){expected[1].data=v;}
};
