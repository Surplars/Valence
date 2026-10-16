"""Explicit source-only opt-in. OFF copies original board bytes unchanged."""
import argparse,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def export(out, enable=False, serializer_profile=None):
    if enable and serializer_profile != "t1-selected":
        raise ValueError("ON requires explicit t1-selected serializer profile (1/1)")
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    original=ROOT/'fpga/next/soc_top_fpga_next_ddr.sv'; data=original.read_bytes()
    marker=b'native_gmac_quarter_clock network_clock ('
    assert data.count(marker)==1
    sources=[original]
    if enable:
        data=data.replace(marker,b'native_gmac_pad_reset_clock #(.ENABLE_PAD_DOMAIN_RESET(1)) network_clock (')
        for parameter in (b'NATIVE_MAC_LOCAL_PAD_RESET_RELEASE',b'NATIVE_MAC_REGISTER_SELECTED_HALF'):
            original_parameter=b'parameter '+parameter+b' = 0'
            assert data.count(original_parameter)==1
            data=data.replace(original_parameter,b'parameter '+parameter+b' = 1')
        guard=b'    initial if (NATIVE_MAC_LOCAL_PAD_RESET_RELEASE != 1 || NATIVE_MAC_REGISTER_SELECTED_HALF != 1) $fatal(1,"PAD candidate requires t1-selected serializer 1/1");\n'
        assert data.count(b'endmodule')==1
        data=data.replace(b'endmodule',guard+b'endmodule')
        source=HERE/'native_gmac_pad_reset_clock.sv';sources.append(source)
        (out/source.name).write_bytes(source.read_bytes())
    (out/original.name).write_bytes(data)
    record=dict(schema='pad-domain-reset-source-candidate-v1',enabled=enable,defaultOff=True,
                serializerProfile=serializer_profile if enable else 'original-defaults',
                originalBoardSha256=sha(original),sourceSha256={str(x.relative_to(ROOT)):sha(x) for x in sources},
                outputSha256={x.name:sha(x) for x in out.iterdir()},
                physicalQualification=False,completeNativeExport=False,
                requiresNewClockResetAudit=enable,rxSourceUnchanged=True)
    (out/'source-candidate.json').write_text(json.dumps(record,indent=2)+'\n');return record
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--enable-pad-domain-reset',action='store_true');p.add_argument('--serializer-profile',choices=['t1-selected']);a=p.parse_args()
    print(json.dumps(export(a.output,a.enable_pad_domain_reset,a.serializer_profile),indent=2))
