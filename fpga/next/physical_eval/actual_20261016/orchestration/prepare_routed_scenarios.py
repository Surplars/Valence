from pathlib import Path
import difflib, hashlib, json, sys

root = Path(sys.argv[1])
final_mode = len(sys.argv)>2 and sys.argv[2]=='final'
source = root / ('run-postroute-physopt-r1/timing-only.xdc' if final_mode else 'run-route-r1/timing-only.xdc')
original = source.read_text()
for command in ('set_input_delay','set_output_delay','set_max_delay','set_bus_skew'):
    if command not in original:
        raise RuntimeError('Timing export omitted required command: '+command)
if 'CLOCK_ROOT' in original or 'USER_CLOCK_ROOT' in original:
    raise RuntimeError('Timing export unexpectedly contains physical clock roots')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
dcp = root / ('run-postroute-physopt-r1/postroute-final.dcp' if final_mode else 'run-route-r1/routed.dcp')
if final_mode and sha(dcp)!='23a4edd50f0c4852f89ffb549f5ba9d2c51dc2019f546479b1dbe538ce102743':raise RuntimeError('Frozen final DCP mismatch')
for rate, period, half, launch_half, edges in ((100,40,20,22,'2 12 22'),(10,400,200,202,'2 102 202')):
    edits = {
        'create_clock -period 8.000 -name phy_rx -waveform {0.000 4.000}':f'create_clock -period {period:.3f} -name phy_rx -waveform {{0.000 {half:.3f}}}',
        'create_clock -period 8.000 -name phy_rx_launch -waveform {2.000 6.000}':f'create_clock -period {period:.3f} -name phy_rx_launch -waveform {{2.000 {launch_half:.3f}}}',
        '-name phy_tx_capture -source [get_pins -quiet u_rgmii/tx_clock_ddr/CLK] -edges {2 4 6}':f'-name phy_tx_capture -source [get_pins -quiet u_rgmii/tx_clock_ddr/CLK] -edges {{{edges}}}',
    }
    changed = original
    for old, new in edits.items():
        if changed.count(old) != 1:
            raise RuntimeError(('Clock identity anchor count',old,changed.count(old)))
        changed = changed.replace(old,new)
    out = root / (f'run-final-sta-{rate}-r1' if final_mode else f'run-route-sta-{rate}-r1')
    out.mkdir(exist_ok=False)
    (out/'scenario.xdc').write_text(changed)
    (out/'scenario.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),fromfile='routed1000/timing-only.xdc',tofile=f'routed{rate}/scenario.xdc')))
    (out/'input-manifest.json').write_text(json.dumps({'rateMbps':rate,'routedDcp':str(dcp),'routedDcpSha256':sha(dcp),'sourceTimingXdcSha256':sha(source),'scenarioTimingXdcSha256':sha(out/'scenario.xdc'),'changedClockCommands':3,'allOtherTimingCommandsPreserved':True,'physicalPropertiesRetainedFromDcp':True,'routeRepeated':False,'bitGenerated':False},indent=2)+'\n')
    print(str(out))
