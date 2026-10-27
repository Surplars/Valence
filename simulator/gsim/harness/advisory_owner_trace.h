#pragma once
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

// Passive trace only. Never writes a DUT field or changes the service law.
namespace advisory_owner_trace {
inline void require(bool condition, const char *why) {
    if (!condition) throw std::runtime_error(why);
}
class Observer {
    std::ofstream trace;
    std::string guest;
    uint64_t cycles = 0, fields = 0;
    bool initialized = false, closed = false;
public:
    void initialize(const std::string &name) {
        require(!initialized, "OWNER_TRACE_DOUBLE_INITIALIZE");
        require(!name.empty() && name.find_first_not_of(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") == std::string::npos,
            "OWNER_TRACE_UNSAFE_GUEST");
        const char *prefix = std::getenv("A1_OWNER_TRACE_PREFIX");
        require(prefix && *prefix, "OWNER_TRACE_PREFIX_REQUIRED");
        guest = name;
        const std::string path = std::string(prefix) + "-" + name + ".bin";
        require(!std::ifstream(path).good(), "OWNER_TRACE_REFUSE_OVERWRITE");
        trace.open(path, std::ios::binary | std::ios::out);
        require(bool(trace), "OWNER_TRACE_OPEN_FAILED");
        initialized = true;
    }
    void record(uint64_t value) {
        require(initialized && !closed, "OWNER_TRACE_NOT_OPEN");
        for (unsigned byte = 0; byte < 8; ++byte) trace.put(char((value >> (8 * byte)) & 255));
        require(bool(trace), "OWNER_TRACE_WRITE_FAILED");
        ++fields;
    }
    template<class D> void observe(D &d);
    void report(std::ostream &out) {
        require(initialized && !closed && cycles && fields, "OWNER_TRACE_EMPTY_OR_DOUBLE_REPORT");
        trace.close();
        require(bool(trace), "OWNER_TRACE_CLOSE_FAILED");
        closed = true;
        out << "ADVISORY_OWNER_TRACE guest=" << guest << " cycles=" << cycles << " fields=" << fields << '\n';
    }
};
}
