"""Pinned independent actual-DTA driver; no simulator invocation on import/derive.

Legacy host and guarded derivation are immutable inputs. Route expectations are
computed from the software owner ledger, architectural request and full permission
oracle, never from a DUT route, qualifier or fault output.
"""
from pathlib import Path
import hashlib
import guarded_natural_dta_host as prior
HERE = Path(__file__).resolve().parent
PRIOR_SHA = '12b47bc73f5bc29b77a7c03c98f0e9670e4ff87a0284a574bd1bf8b894ed57d7'

def derive():
    assert hashlib.sha256((HERE/'guarded_natural_dta_host.py').read_bytes()).hexdigest() == PRIOR_SHA
    source = prior.derive()
    def edit(old, new):
        nonlocal source
        assert source.count(old) == 1, ('certified ingress anchor changed', old)
        source = source.replace(old, new)
    edit('RegisteredRawCertifiedFlowGsim.h', 'CertifiedIngressDtaGsim.h')
    edit('SRegisteredRawCertifiedFlowGsim d;', 'SCertifiedIngressDtaGsim d;')
    edit('#define GUARDED_NATURAL_DTA 0', '#define GUARDED_NATURAL_DTA 1')
    edit('using namespace canonical_store_test;', '#ifndef CERTIFIED_LOAD_INGRESS\n#define CERTIFIED_LOAD_INGRESS 1\n#endif\nusing namespace canonical_store_test;')
    edit('unsigned cfg = 0x1f, privilege', 'unsigned cfg1 = 0, cfg2 = 0; uint64_t pmpAddress1 = 0, pmpAddress2 = 0;\n    bool superpage = false; unsigned ingressDirect = 0, nominalReject = 0, fullCheckedDequeue = 0;\n    unsigned cfg = 0x1f, privilege')
    begin = source.index('        // One NAPOT entry')
    end = source.index('\n    Entry truth', begin)
    source = source[:begin] + '''        // Architectural first-overlapping-entry rule, independently decoded
        // with widened arithmetic. Partial matches deny, even unlocked M-mode.
        const unsigned configs[3] = {cfg, cfg1, cfg2};
        const uint64_t addresses[3] = {pmpAddress, pmpAddress1, pmpAddress2};
        using Wide = unsigned __int128;
        const Wide start = address, end = start + bytes;
        for (unsigned i = 0; i < 3; ++i) {
            const unsigned c = configs[i], mode = (c >> 3) & 3;
            if (!mode) continue;
            Wide lo = 0, hi = 0;
            if (mode == 1) { lo = i ? Wide(addresses[i-1]) * 4 : 0; hi = Wide(addresses[i]) * 4; }
            else if (mode == 2) { lo = Wide(addresses[i]) * 4; hi = lo + 4; }
            else {
                unsigned n = 0; while (n < 54 && ((addresses[i] >> n) & 1)) ++n;
                const Wide mask = (Wide(1) << n) - 1;
                lo = (Wide(addresses[i]) & ~mask) * 4; hi = lo + (Wide(1) << (n + 3));
            }
            if (lo >= hi || start >= hi || end <= lo) continue;
            if (start < lo || end > hi) return false;
            if (privilege == 3 && !(c & 0x80)) return true;
            return (!read || (c & 1)) && (!write || (c & 2));
        }
        return privilege == 3;
    }
''' + source[end:]
    edit('d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(pmpAddress); d.set_io$$flush(flush);', '''d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(pmpAddress);
        d.set_io$$pmpCfg1(cfg1); d.set_io$$pmpAddress1(pmpAddress1);
        d.set_io$$pmpCfg2(cfg2); d.set_io$$pmpAddress2(pmpAddress2); d.set_io$$flush(flush);''')
    edit('tables.pte(d.get_io$$pte$$request$$bits())', '''(superpage && d.get_io$$pte$$request$$bits() == virtual_load_test::root + 4096 ?
                ((ram >> 12) << 10) | 0xc7ULL : tables.pte(d.get_io$$pte$$request$$bits()))''')
    edit('        if (take) {\n            auto e = truth(*request);', '''        // All expectations use pre-edge ledger occupancy, before acceptance.
        check(d.get_io$$ingressCount() == ingress.size(), "ingress exact owner count mismatch");
        const bool nominal = CERTIFIED_LOAD_INGRESS && request && ingress.empty() && translated.empty() && !waiting &&
            request->prechecked && !request->virt && !request->write && !request->atomic && !request->uncached && !request->origin;
        const bool qualified = (context >> 60) == 8 && (privilege == 0 || privilege == 1) && !flush;
        const bool direct = nominal && qualified && !truth(*request).fault() && checked.size() < 2;
        check(bool(d.get_io$$certifiedIngressNominal()) == nominal, "independent nominal source mismatch");
        check(bool(d.get_io$$certifiedIngressPass()) == direct, "independent certified ingress grant mismatch");
        check(!direct || take, "direct capture without upstream acceptance");
        const std::optional<uint64_t> directId = direct ? std::optional<uint64_t>{accepted} : std::nullopt;
        nominalReject += nominal && !direct;
        if (take) {
            auto e = truth(*request);''')
    edit('records.emplace(e.id, e); ordered.push_back(e.id); ingress.push_back(e.id);', '''e.routed = direct;
            records.emplace(e.id, e); ordered.push_back(e.id);
            if (!direct) ingress.push_back(e.id); else ++ingressDirect;''')
    edit('        check(cp == checkedId.has_value(),', '''        if (directId) {
            check(!checkedId && !resultId && !tp && !tf && !tr && !tq,
                "certified ingress overtook or duplicated older result");
            checkedId = directId;
        }
        fullCheckedDequeue += checked.size() == 2 && cq;
        check(cp == checkedId.has_value(),''')
    edit('accepted == returned && accepted == incomingFires && accepted == checkedPushes', 'accepted == returned && accepted == incomingFires + ingressDirect && accepted == checkedPushes')
    edit('accepted == translatedPushes + hitPasses + precheckedPasses + identityPasses,', 'accepted == translatedPushes + hitPasses + precheckedPasses + identityPasses + ingressDirect,')
    edit('<< " incoming=" << incomingFires', '<< " ingress_direct=" << ingressDirect << " nominal_reject=" << nominalReject\n            << " full_checked_dequeue=" << fullCheckedDequeue << " incoming=" << incomingFires')
    # Keep historical scenarios untouched in their original host. This distinct
    # driver has its own explicit stage/route expectations, not adaptive latency.
    source = source[:source.index('int main(int argc, char **argv)')]
    source += (HERE/'harness/certified_ingress_dta_cases.inc').read_text()
    return source

if __name__ == '__main__':
    import sys
    Path(sys.argv[1]).write_text(derive())
