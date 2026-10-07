// Reuse the independent ISA/NEMU retirement driver, select ONLY RV64M cases.
// The ordinary core harness and frozen performance baseline remain unchanged.
#define main fullCoreRegressionMain
#include "core.cpp"
#undef main
int main(int argc,char** argv) {
    try {
        check(argc==2,"usage: rv64m-core NEMU.so");
        Reference ref(argv[1]);
        Stats stats;
        mulDivTests(ref,stats);
        std::cout<<"GSIM short RV64M CPU + NEMU: PASS programs="<<stats.programs
                 <<" commits="<<stats.commits<<" redirects="<<stats.redirects<<'\n';
    } catch(const std::exception& error) {
        std::cerr<<"GSIM short RV64M CPU: FAIL "<<error.what()<<'\n';
        return 1;
    }
}
