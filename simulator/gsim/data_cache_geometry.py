"""Checks actual emitted cache RAM/tag/home-directory geometry and passive taps."""
import re

def module(fir, name):
    m=re.search(r'^  (?:public )?module '+re.escape(name)+r'\s*:.*?(?=^  (?:public )?(?:module|extmodule) |\Z)',fir,re.M|re.S)
    if not m: raise RuntimeError('missing module '+name)
    return m[0]

def verify(fir, lines, home=True, probes=False):
    cache=module(fir,'CoherentLineCache');sets=lines//2;tag_bits=58-(sets.bit_length()-1)
    facts=[f'reg tags : UInt<{tag_bits}>[{lines}]',f'regreset replacement : UInt<1>[{sets}]']
    facts += [f'smem data_{bank} : UInt<8>[8][{lines}]' for bank in range(8)]
    assert all(fact in cache for fact in facts), 'emitted cache SRAM/tag/set geometry mismatch'
    assert len(re.findall(r'smem data_\d+ :',cache))==8
    if home:
        directory=module(fir,'CoherentLineHome')
        assert f'regreset owned : UInt<1>[{lines}]' in directory
        assert f'reg ownedTags : UInt<58>[{lines}]' in directory
    if probes:
        anchors=['node cpuFire = and(io.upstream.request.ready, io.upstream.request.valid)',
                 'node probeRead = and(io.tl.b.ready, io.tl.b.valid)',
                 'node _T_23 = and(io.tl.c.ready, io.tl.c.valid)',
                 'node _T_24 = eq(state, UInt<4>(0h2))', 'node _T_25 = and(_T_23, _T_24)',
                 'node _T_263 = and(io.tl.c.ready, io.tl.c.valid)',
                 'node _T_264 = eq(state, UInt<4>(0ha))', 'node _T_265 = and(_T_263, _T_264)']
        assert all(a in cache for a in anchors), 'passive scalar definition changed'
    return {'lines':lines,'ways':2,'sets':sets,'line_bytes':64,'bytes':lines*64,
            'tag_bits':tag_bits,'data_banks':8,'bank_width_bits':64,'bank_depth':lines,
            'directory_entries':lines if home else None,'facts':facts}
