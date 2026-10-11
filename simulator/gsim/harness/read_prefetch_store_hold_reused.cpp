// The same newly generated ON64bit model runs three affected saved protection
// schedules. No historical PASS is imported; oracle/transport are unchanged.
#define main original_adoption_main
#include "prefetch_demand_adoption.cpp"
#undef main
int main(int argc,char**argv) {
    try {
        using namespace adoption;
        for(int i=1;i<argc;++i){std::string a=argv[i];if(a.rfind("--images=",0)==0)imageDirectory=a.substr(9);else throw std::runtime_error("unknown argument");}
        errors(1);errors(2);probe_and_flush();
        std::cout<<"READ_PREFETCH_STORE_HOLD_REUSED_PASS cases="<<completedCases
            <<" denied_and_corrupt=1 probe_and_flush=1 current_on64_model=1 qualification_inherited=0\n";return 0;
    }catch(const std::exception&e){std::cerr<<"READ_PREFETCH_STORE_HOLD_REUSED_FAIL "<<e.what()<<'\n';return 1;}
}
