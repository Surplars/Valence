"""Exact source-only derivative: preserve programs/service/ISA oracles, change declared route contract.

Only candidate consumes new test-only taps. Baseline original hosts remain sealed.
This is not a DUT-predicate adaptation: direct requires same-cycle upstream and
checked captures, eligible prechecked owner, exact epoch and non-flow physical.
"""
from pathlib import Path
import hashlib
import buffered_return_flow_cpu as prior
HERE = Path(__file__).resolve().parent

def derive_vm(source):
    def edit(old, new):
        nonlocal source
        assert source.count(old) == 1, ('certified CPU unique anchor', old)
        source = source.replace(old, new)
    edit('uint64_t flowRequests = 0, flowReplies = 0, precheckedPasses = 0, rawPasses = 0;',
         'uint64_t flowRequests = 0, flowReplies = 0, precheckedPasses = 0, rawPasses = 0, certifiedIngressPasses = 0;')
    edit('        precheckedPasses += dut.get_flow$$precheckedPass(); rawPasses += dut.get_flow$$rawPass();', '''        precheckedPasses += dut.get_flow$$precheckedPass(); rawPasses += dut.get_flow$$rawPass();
        certifiedIngressPasses += dut.get_certified$$pass();
        require(!dut.get_certified$$pass() || (dut.get_certified$$upstreamFire() &&
            dut.get_certified$$checkedPush() && !dut.get_certified$$fpEpoch() &&
            !dut.get_certified$$checkedFault() && dut.get_certified$$ingressCount() == 0),
            "certified ingress lacks exact empty registered source and checked sink");''')
    edit('            if (dut.get_flow$$rawPass()) require(!o.prechecked, "raw pass substituted prechecked owner");', '''            if (dut.get_flow$$rawPass()) require(!o.prechecked, "raw pass substituted prechecked owner");
            if (dut.get_certified$$pass()) require(o.prechecked && !o.write && cycle == o.upstream &&
                dut.get_certified$$upstream$$translationEpoch() == o.epoch &&
                dut.get_certified$$checkedRequest$$translationEpoch() == o.epoch,
                "direct checked full-token/epoch association mismatch");
            else require(cycle > o.upstream, "fallback lost ingress register");
            std::cout << "CERTIFIED_INGRESS_ROUTE guest=" << program.name << " index=" << o.token.first
                << " tag=" << o.token.second << " direct=" << unsigned(dut.get_certified$$pass())
                << " epoch=" << o.epoch << " upstream=" << o.upstream << " checked=" << cycle << '\\n';''')
    edit('precheckedPasses + registeredCertifiedSpills == precheckedLoads',
         'precheckedPasses + registeredCertifiedSpills + certifiedIngressPasses == precheckedLoads')
    begin = source.index('        if (!registered) {\n            require(!registeredCertifiedSpills')
    end = source.index('        std::cout << "NEW_REGISTERED_FLOW_METRIC', begin)
    source = source[:begin] + '''        require(!registered && !registeredCertifiedSpills &&
            precheckedPasses + certifiedIngressPasses == precheckedLoads &&
            rawStoreLatency == std::map<uint64_t,uint64_t>{{2,48}} &&
            rawLoadLatency == std::map<uint64_t,uint64_t>{{2,2}} &&
            coldStoreLatency == std::map<uint64_t,uint64_t>{{24,1}},
            "unchanged raw and exact certified route conservation");
        uint64_t samples = 0;
        for (const auto &[latency,count] : precheckedLatency) {
            require(latency >= 1, "certified request bypassed non-flow checked register"); samples += count;
        }
        require(samples == precheckedLoads, "certified latency samples lost an owner");
        std::cout << "CERTIFIED_INGRESS_COUNTS guest=" << program.name << " direct=" << certifiedIngressPasses
            << " fallback=" << precheckedPasses << " samples=" << samples << '\\n';
''' + source[end:]
    return source


def derive_load(source):
    anchor='  if(dut.get_io$$checked$$valid()){const Token t=pop(ingressQ,"checked without ordered ingress");auto&o=owner(t);o.checked=cycle;'
    assert source.count(anchor)==1
    addition='''
  require(!dut.get_certified$$pass() || (dut.get_certified$$upstreamFire() && dut.get_certified$$checkedPush() && !dut.get_certified$$fpEpoch()), "load direct source/sink/FP mismatch");
  if(dut.get_certified$$pass())require(dut.get_certified$$ingressCount()==0 && !dut.get_certified$$checkedFault(), "load direct occupied ingress or permission fault");
'''
    source=source.replace(anchor,addition+anchor+'''require(o.upstream && (dut.get_certified$$pass() ? cycle==*o.upstream && o.prechecked : cycle>*o.upstream),"load direct/fallback owner residence");
  std::cout<<"CERTIFIED_LOAD_ROUTE guest="<<program.name<<" index="<<t.first<<" tag="<<t.second<<" direct="<<unsigned(dut.get_certified$$pass())<<" epoch="<<o.epoch<<" start="<<o.start<<" upstream="<<*o.upstream<<" checked="<<cycle<<'\\n';''')
    anchor2='  if(trace)for(const auto&[t,o]:loads)std::cout<<"LOAD_OWNER '
    assert source.count(anchor2)==1
    source=source.replace(anchor2, r'''  if(trace)for(const auto&[t,o]:loads)std::cout<<"CERTIFIED_LOAD_OWNER guest="<<program.name<<" index="<<t.first<<" tag="<<t.second<<" pa="<<o.pa<<" epoch="<<o.epoch<<" prechecked="<<o.prechecked<<" start="<<o.start<<" upstream="<<o.upstream.value_or(0)<<" checked="<<o.checked.value_or(0)<<" physical="<<o.physical.value_or(0)<<" reply="<<o.reply.value_or(0)<<" complete="<<o.complete.value_or(0)<<" retire="<<o.retire.value_or(0)<<" retired="<<o.retired<<" cancelled="<<o.cancelled<<'\n';
'''+anchor2)
    return source


def adapters(model):
    records=prior.host_adapters(model)
    for kind, derive in [('vm',derive_vm),('load',derive_load)]:
        original=Path(records[kind]['adapter']); before=original.read_text()
        target=model/('certified_ingress_'+kind+'.cpp'); target.write_text(derive(before))
        records[kind].update(adapter=str(target),adapter_sha256=prior.sha(target),
            intermediate_sha256=prior.sha(original),declared_route_contract='same-cycle direct or strict registered fallback')
    return records
