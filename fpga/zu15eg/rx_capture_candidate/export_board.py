"""Source-only RX buffer/pair variant; OFF preserves original board bytes."""
import argparse,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def replace_once(data,old,new):
    if data.count(old)!=1:raise ValueError('Expected unique source marker: '+old.decode())
    return data.replace(old,new)
def export(out,enable=False):
    original=ROOT/'fpga/next/soc_top_fpga_next_ddr.sv';data=original.read_bytes()
    sources=[original]
    if enable:
        data=replace_once(data,b'BUFG rx_clock_buffer(.I(rx_pad), .O(clk_rx));',b'''(* DONT_TOUCH="TRUE" *) BUFG rx_clock_buffer(.I(rx_pad), .O(clk_rx));
    wire clk_rx_capture;
    (* DONT_TOUCH="TRUE" *) BUFG rx_capture_clock_buffer(.I(rx_pad), .O(clk_rx_capture));''')
        data=replace_once(data,b'always @(posedge clk_rx or posedge rx_reset_request)',b'always @(posedge clk_rx_capture or posedge rx_reset_request)')
        marker=b'wire [4:0] rgmii_rx_rise, rgmii_rx_fall, rgmii_tx_rise, rgmii_tx_fall;'
        data=replace_once(data,marker,marker+b'''
    wire [4:0] capture_rx_rise, capture_rx_fall;
    native_rx_falling_pair #(.ENABLE_FALLING_PAIR(1)) rx_capture_pair (
        .capture_clock(clk_rx_capture), .capture_reset(rx_reset_pipe[2]),
        .input_rise(capture_rx_rise), .input_fall(capture_rx_fall),
        .output_rise(rgmii_rx_rise), .output_fall(rgmii_rx_fall));''')
        data=replace_once(data,b'.rx_clock(clk_rx)',b'.rx_clock(clk_rx_capture)')
        data=replace_once(data,b'.rx_rise(rgmii_rx_rise), .rx_fall(rgmii_rx_fall)',b'.rx_rise(capture_rx_rise), .rx_fall(capture_rx_fall)')
        sources.append(HERE/'native_rx_falling_pair.sv')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    (out/original.name).write_bytes(data)
    if enable:(out/sources[-1].name).write_bytes(sources[-1].read_bytes())
    record=dict(schema='rx-capture-sibling-source-candidate-v1',enabled=enable,defaultOff=True,
      sourceSha256={x.relative_to(ROOT).as_posix():sha(x) for x in sources},
      outputSha256={x.name:sha(x) for x in out.iterdir()},
      physicalQualification=False,completeNativeExport=False,requiresRelatedClockTiming=enable,
      inputTimingAndPhyConfigurationUnchanged=True,extraPairBits=10 if enable else 0)
    (out/'source-candidate.json').write_text(json.dumps(record,indent=2)+'\n');return record
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    p.add_argument('--enable-rx-capture-sibling',action='store_true');a=p.parse_args()
    print(json.dumps(export(a.output,a.enable_rx_capture_sibling),indent=2))
