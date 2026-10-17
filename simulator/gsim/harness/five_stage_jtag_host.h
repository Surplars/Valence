// Logical CPU-domain DMI test host, NOT a simulated FPGA TAP/CDC qualification.
#include <functional>

struct I1JtagHost {
    SFiveStageSoc &d;
    const std::vector<uint8_t> &image;
    enum Action { Arm, Generation, Configure, Entry, Length, Crc, Token, Address, Word, Busy, Commit,
                  Claimed, ProtectAddress, ProtectWrite, ProtectCheck, Done };
    Action action = Arm;
    unsigned op = 1, address = 0x41;
    uint32_t value = 0, generation = 0;
    size_t offset = 0;
    bool awaiting = false, accepted = false, responseReady = false, done = false, rejected = false;
    bool badCrc = false, retry = false, first = true;
    uint64_t acceptedRequests = 0;
    std::mt19937_64 random{0x444d49};
    I1JtagHost(SFiveStageSoc &model, const std::vector<uint8_t> &bytes, bool bad, bool again)
        : d(model), image(bytes), badCrc(bad || again), retry(again) {}
    uint32_t crc() {
        uint32_t result = ~0U;
        for (uint8_t byte : image) {
            result ^= byte;
            for (unsigned bit = 0; bit < 8; ++bit) result = (result >> 1) ^ (result & 1 ? 0xedb88320U : 0);
        }
        return ~result;
    }
    void request(Action next, unsigned kind, unsigned reg, uint32_t data = 0) {
        action = next; op = kind; address = reg; value = data;
    }
    void nextWord() {
        uint32_t word = 0;
        for (unsigned n = 0; n < 4 && offset + n < image.size(); ++n) word |= uint32_t(image[offset + n]) << (8 * n);
        // Retry uses different RAM contents, not just a bad metadata token: exercise D-cache invalidation.
        if (retry && first && offset + 4 >= image.size()) word ^= 0x01;
        request(Word, 2, 0x3c, word);
    }
    void inputs() {
        accepted = !done && !awaiting;
        responseReady = random() % 4 != 0;
        d.set_io$$jtagDmi$$request$$valid(accepted);
        d.set_io$$jtagDmi$$request$$bits$$op(op);
        d.set_io$$jtagDmi$$request$$bits$$address(address);
        d.set_io$$jtagDmi$$request$$bits$$data(value);
        d.set_io$$jtagDmi$$response$$ready(responseReady);
    }
    void outputs() {
        if (accepted && d.get_io$$jtagDmi$$request$$ready()) { awaiting = true; ++acceptedRequests; }
        if (!d.get_io$$jtagDmi$$response$$valid() || !responseReady) return;
        need(awaiting && d.get_io$$jtagDmi$$response$$bits$$status() == 0, "JTAG DMI failed/unowned reply");
        awaiting = false;
        uint32_t data = d.get_io$$jtagDmi$$response$$bits$$data();
        switch (action) {
        case Arm:
            if (data & 1) request(Generation, 1, 0x46);
            else request(Arm, 1, 0x41);
            break;
        case Generation:
            if (generation && data != generation) {
                rejected = true;
                if (!retry) { done = true; action = Done; break; }
                first = false;
            }
            generation = data; offset = 0;
            request(Configure, 2, 0x38, (2 << 17) | (1 << 16));
            break;
        case Configure: request(Entry, 2, 0x43, 0x80200000); break;
        case Entry: request(Length, 2, 0x44, image.size()); break;
        case Length: request(Crc, 2, 0x45, crc() ^ ((badCrc && first && !retry) ? 1 : 0)); break;
        case Crc: request(Token, 2, 0x49, generation); break;
        case Token: request(Address, 2, 0x39, 0x80200000); break;
        case Address: nextWord(); break;
        case Word: request(Busy, 1, 0x38); break;
        case Busy:
            need(!(data & ((1U << 22) | (7U << 12))), "JTAG SBA transfer error");
            if (data & (1U << 21)) request(Busy, 1, 0x38);
            else {
                offset += 4;
                if (offset < image.size()) nextWord();
                else request(Commit, 2, 0x42, 2);
            }
            break;
        case Commit: request(Claimed, 1, 0x41); break;
        case Claimed:
            if (data & 64) {
                need(!badCrc || !first, "ROM launched a bad-CRC image");
                request(ProtectAddress, 2, 0x39, 0x80200000);
            } else if (data & 1) request(Generation, 1, 0x46);
            else request(Claimed, 1, 0x41);
            break;
        case ProtectAddress: request(ProtectWrite, 2, 0x3c, 0xdeadbeef); break;
        case ProtectWrite: request(ProtectCheck, 1, 0x38); break;
        case ProtectCheck:
            need(((data >> 12) & 7) == 7 && !(data & (1U << 21)), "JTAG wrote after CPU claimed image");
            done = true; action = Done; break;
        default: throw std::runtime_error("unexpected JTAG host phase");
        }
    }
};
