"""Synthetic model/host-only contract tests. No Vivado, mapped-netlist or RTL pass."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac_netlist_review as review
import media_integration as media
import export as exporter

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
INVENTORY = json.loads((HERE / 'mac-boundary-cdc-inventory.json').read_text())
CONTRACT = review.contract(INVENTORY)
BANK = CONTRACT['root']


class SyntheticMapping:
    """Explicit FDCE/FDPE/LUT2/RAM toy graph, never an observed FPGA mapping."""
    def __init__(self, rate=1000):
        self.m = {}
        # Independent PHY RXC frequencies; do not derive these by copying the
        # collector's rate formula/table. RGMII low rates repeat nibble clocks.
        rxc_hz = {1000:125_000_000, 100:25_000_000, 10:2_500_000}[rate]
        for clk, period in [('cpu_clk', 10.0), ('raw_clk', 8.0), ('rx_clk', 1_000_000_000/rxc_hz)]:
            self.m[clk] = dict(KIND='clock', NAME=clk, PERIOD=period)
        self.clocks = {'cpu': 'cpu_clk', 'raw_tx': 'raw_clk', 'raw_rx': 'rx_clk', 'tx': 'raw_clk', 'rx': 'raw_clk'}
        self.net('gnd', TYPE='GROUND'); self.net('vcc', TYPE='POWER');self.net('cold')
        self.cell('board/cold_driver','LUT1');self.pin('board/cold_driver/O','cold','OUT')
        self.cell(BANK, 'TriSpeedManagedGmac')
        self.pin(BANK+'/commonReset', 'cold', 'IN', False)
        for domain, pin in CONTRACT['clock_pins'].items():
            self.pin(BANK+'/'+pin, 'clk_'+domain, 'OUT' if domain in ('tx', 'rx') else 'IN', False, CLOCK=self.clocks[domain])
        for domain in ('tx', 'rx'):
            gate=BANK+'/'+domain+'Managed_gate/buffer'
            self.cell(gate, 'BUFGCE'); self.pin(gate+'/I', 'clk_raw_tx', 'IN')
        for rel, dom in [('cpuRelease','cpu'),('txRelease','tx'),('rxRelease','rx'),('rawTxRelease','raw_tx'),('rawRxRelease','raw_rx')]:
            self.release(BANK+'/'+rel, dom, 'cold')
        for chain, launch, src, dst, sr, tr in CONTRACT['level_rules']:
            self.ff(BANK+'/'+launch, src, 0, BANK+'/'+sr+'_released')
            self.level(BANK+'/'+chain, BANK+'/'+launch, dst, BANK+'/'+tr+'_released')
        self.ff(BANK+'/media/ingressResetSource_reg', 'cpu', 1, BANK+'/cpuRelease_released')
        self.cell(BANK+'/epoch_or', 'LUT2', INIT="4'hE")
        self.pin(BANK+'/epoch_or/I0', BANK+'/media/ingressResetSource_reg_q', 'IN')
        self.pin(BANK+'/epoch_or/I1', 'cold', 'IN')
        self.pin(BANK+'/epoch_or/O', 'epoch', 'OUT')
        self.pin(BANK+'/physicalIngress/commonReset', 'epoch', 'IN', False)
        for path, dom in [('sourceRelease','raw_rx'),('destinationRelease','raw_tx'),
                          ('crossing/fifo/sourceRelease','raw_rx'),('crossing/fifo/destinationRelease','raw_tx')]:
            self.release(BANK+'/physicalIngress/'+path, dom, 'epoch')
        for path in ['txFifo','rxFifo','txStats','rxStats','rxDiagnostics','rawDiagnostics','txConfig','rxConfig','rxStop']:
            self.pin(BANK+'/'+path+'/commonReset', 'cold', 'IN', False)
        directions=[('cpu','raw_tx'),('cpu','raw_rx'),('cpu','tx'),('cpu','rx'),('tx','cpu'),('rx','cpu'),('rx','cpu'),('raw_rx','cpu'),('cpu','rx')]
        for (path, width), (src, dst) in zip(CONTRACT['mailbox_widths'].items(), directions):
            self.mailbox(BANK+'/'+path, width, src, dst)
        for (path, width), (src, dst) in zip(CONTRACT['fifo_pointer_widths'].items(), [('cpu','tx'),('rx','cpu'),('raw_rx','raw_tx')]):
            self.fifo(BANK+'/'+path,width,src,dst,'epoch' if path.startswith('physicalIngress/') else 'cold')
        self.ff(BANK+'/tx/busy_reg', 'tx', 0, BANK+'/txRelease_released')
        self.ff(BANK+'/encode/byteStep_reg', 'raw_tx', 0, BANK+'/rawTxRelease_released')
        self.ff(BANK+'/ingress/payload_reg', 'raw_tx', 0, BANK+'/rawTxRelease_released')
        self.ff(BANK+'/rx/active_reg', 'rx', 0, BANK+'/rxRelease_released')
        self.m[BANK+'/txWireDrainedSource_reg/D']['STARTPOINTS']=[BANK+'/tx/busy_reg/Q']

    def net(self, name, **props):
        self.m.setdefault(name, dict(KIND='net', NAME=name, TYPE='SIGNAL'))
        self.m[name].update(props)

    def cell(self, name, ref, **props):
        self.m[name]=dict(KIND='cell',NAME=name,REF_NAME=ref,IS_SEQUENTIAL=ref.startswith('FD'), IS_PRIMITIVE=ref.startswith(('FD','RAM')), **props)

    def pin(self, name, net, direction, leaf=True, **props):
        self.net(net)
        cell, ref=name.rsplit('/',1)
        self.m[name]=dict(KIND='pin',NAME=name,CELL=cell,REF_PIN_NAME=ref,NET=net,DIRECTION=direction,LEAF=leaf,IS_LEAF=leaf,**props)

    def ff(self, name, domain, reset=0, net='cold', async_reg=False):
        if name in self.m: return
        rp='PRE' if reset else 'CLR'
        self.cell(name, 'FDPE' if reset else 'FDCE', ASYNC_REG='TRUE' if async_reg else 'FALSE', INIT=f"1'h{reset}", IS_C_INVERTED=0, **{'IS_'+rp+'_INVERTED':0})
        self.pin(name+'/C', 'clock_'+domain, 'IN', CLOCK=self.clocks[domain])
        self.pin(name+'/'+rp,net,'IN');self.pin(name+'/Q',name+'_q','OUT');self.pin(name+'/D',name+'_d','IN')
        self.pin(name+'/CE','vcc' if async_reg else name+'_ce','IN',STARTPOINTS=[])

    def release(self, path, domain, reset):
        self.cell(path,'CdcResetRelease')
        for i in range(3):
            cell=f'{path}/release_0_reg[{i}]';self.ff(cell,domain,1,reset,True)
            self.m[cell+'/D']['NET']='gnd' if i==0 else f'{path}/release_0_reg[{i-1}]_q'
        self.m[path+'/release_0_reg[2]/Q']['NET']=path+'_released';self.net(path+'_released')

    def level(self,path,launch,domain,reset):
        self.cell(path,'CdcLevel')
        for i in range(2):
            cell=f'{path}/stages_reg[{i}]';self.ff(cell,domain,0,reset,True)
            self.m[cell+'/D']['NET']=launch+'_q' if i==0 else f'{path}/stages_reg[0]_q'

    def mailbox(self,h,width,src,dst):
        self.cell(h,'CdcMailbox');self.pin(h+'/sourceClock','clock_'+src,'IN',False,CLOCK=self.clocks[src])
        self.pin(h+'/destinationClock','clock_'+dst,'IN',False,CLOCK=self.clocks[dst]);self.pin(h+'/commonReset','cold','IN',False)
        self.release(h+'/sourceRelease',src,'cold');self.release(h+'/destinationRelease',dst,'cold')
        for reg, dom, rel in [('requestToggle',src,'sourceRelease'),('ackToggle',dst,'destinationRelease'),('valid',dst,'destinationRelease'),('token',dst,'destinationRelease')]:
            self.ff(h+'/'+reg+'_reg',dom,0,h+'/'+rel+'_released')
        self.level(h+'/requestSync',h+'/requestToggle_reg',dst,h+'/destinationRelease_released')
        self.level(h+'/ackSync',h+'/ackToggle_reg',src,h+'/sourceRelease_released')
        for i in range(width):
            suffix='' if width==1 else f'[{i}]'
            a=h+'/held_reg'+suffix;b=h+'/captured_reg'+suffix
            self.ff(a,src);self.ff(b,dst);self.m[b+'/D']['NET']=a+'_q'

    def fifo(self,h,width,src,dst,reset):
        self.cell(h,'CdcDataFifo');self.pin(h+'/sourceClock','clock_'+src,'IN',False,CLOCK=self.clocks[src])
        self.pin(h+'/destinationClock','clock_'+dst,'IN',False,CLOCK=self.clocks[dst]);self.pin(h+'/commonReset',reset,'IN',False)
        self.release(h+'/sourceRelease',src,reset);self.release(h+'/destinationRelease',dst,reset)
        for prefix, fr, to, source_rel, target_rel in [('readGray',dst,src,'destinationRelease','sourceRelease'),('writeGray',src,dst,'sourceRelease','destinationRelease')]:
            for i in range(width):
                launch=f'{h}/{prefix}_reg[{i}]';a=f'{h}/{prefix}Sync_stage0_reg[{i}]';b=f'{h}/{prefix}Sync_reg[{i}]'
                self.ff(launch,fr,0,h+'/'+source_rel+'_released');self.ff(a,to,0,h+'/'+target_rel+'_released',True);self.ff(b,to,0,h+'/'+target_rel+'_released',True)
                self.m[a+'/D']['NET']=launch+'_q';self.m[b+'/D']['NET']=a+'_q'
        for i in range(38): self.ff(f'{h}/output_0_reg[{i}]',dst)
        # Deliberately expose a composite WCLK and two legal expanded leaves.
        # Endpoint fanin/path evidence names only the leaves; a name wildcard
        # sees all three and is an invalid collector for this toy mapping.
        self.cell(h+'/storage_ext/ram','RAM32M16')
        self.pin(h+'/storage_ext/ram/WCLK','clock_'+src,'IN',False,CLOCK=self.clocks[src])
        for ram in ('a','b'):
            self.cell(h+'/storage_ext/ram/'+ram,'RAMD32')
            self.pin(h+'/storage_ext/ram/'+ram+'/CLK','clock_'+src,'IN',CLOCK=self.clocks[src])
        self.ff(h+'/storage_ext/readAddress_reg[0]',dst)
        for i in range(38):
            end=f'{h}/output_0_reg[{i}]/D'
            launches=[h+'/storage_ext/ram/a/CLK']
            if i % 2: launches.append(h+'/storage_ext/ram/b/CLK')
            self.m[end]['STARTPOINTS']=launches+[f'{h}/readGray_reg[0]/C', f'{h}/storage_ext/readAddress_reg[0]/C']
            self.m[end]['TIMING_STARTPOINTS']=launches



class CollectorTclTests(unittest.TestCase):
    def run_model(self, mutation='', expected=None, rate=1000, contract=None):
        with tempfile.TemporaryDirectory() as tmp:
            body='set MODEL '+review.tcl(SyntheticMapping(rate).m)+'\n'
            body+='source '+review.tcl(HERE/'tests/mac_netlist_mock.tcl')+'\n'
            body+='source '+review.tcl(HERE/'audit_mac_netlist.tcl')+'\n'
            body+='set contract '+review.tcl(contract or CONTRACT)+'\n'
            body+='set bank '+review.tcl(BANK)+'\n'+mutation+'\nmock_reindex\n'
            body+='valence_mac::collect $contract [dict create status SOURCE_BOUND_PREPARED_NOT_NETLIST_QUALIFIED] '+review.tcl(Path(tmp)/'reports')+' '+str(rate)+'\n'
            body+='if {[llength $BOUND_CALLS]} {error {read-only collector changed constraints}}\n'
            body+='puts "MOCK_FACTS_COMPLETE_NOT_VIVADO timing=[llength $TIMING_CALLS] reports=[llength $REPORT_CALLS]"\n'
            command='if {[catch {\n'+body+'\n} why opts]} {puts stderr $why; puts stderr [dict get $opts -errorinfo]; exit 1}\n'
            r=subprocess.run(['tclsh'],input=command,text=True,capture_output=True,timeout=90)
            if expected:
                self.assertNotEqual(r.returncode,0,r.stdout);self.assertIn(expected,r.stderr)
            else:
                self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('MOCK_FACTS_COMPLETE_NOT_VIVADO',r.stdout)
                facts=(Path(tmp)/'reports/facts.tcllist').read_text()
                self.assertIn('FACTS_COLLECTED_REVIEW_REQUIRED_NOT_NETLIST_QUALIFIED',facts)
                self.assertEqual(sum(line.startswith('FIFO ') for line in facts.splitlines()),3)
                self.assertEqual(sum(line.startswith('SCOPE ') and '/payload ' in line for line in facts.splitlines()),12)
            return r

    def test_all_three_rate_models(self):
        for rate in (10,100,1000):
            with self.subTest(rate=rate): self.run_model(rate=rate)

    def test_old_root(self):
        c={**CONTRACT,'root':'u_soc/nativeBank/gmac'}
        self.run_model(expected='legacy or wildcard root',contract=c)

    def test_wrong_slow_rate_double_periods_rejected(self):
        for rate, wrong in [(100,80.0),(10,800.0)]:
            with self.subTest(rate=rate):
                self.run_model(f'dict set MODEL rx_clk PERIOD {wrong}', 'clock period mismatch: raw_rx', rate=rate)

    def test_narrow_level_constraints_validate_all_before_mutation(self):
        for broken in (False, True):
            body='set MODEL '+review.tcl(SyntheticMapping().m)+'\n'
            body+='source '+review.tcl(HERE/'tests/mac_netlist_mock.tcl')+'\n'
            body+='source '+review.tcl(HERE/'mac_registered_level_constraints.tcl')+'\n'
            body+='set contract '+review.tcl(CONTRACT)+'\nset bounds {}\n'
            body+='proc set_max_delay {args} {global bounds; lappend bounds $args}\n'
            if broken:
                body+='dict set MODEL '+review.tcl(BANK+'/txWireDrained_sync/stages_reg[0]/D')+' NET cold\n'
            body+='mock_reindex\nset rc [catch {valence_mac_registered_level_constraints $contract} why]\n'
            if broken:
                body+='if {!$rc || [llength $bounds]!=0} {error {partial bounds applied on bad final chain}}\n'
            else:
                body+='if {$rc || [llength $bounds]!=5} {error "wrong five bounds: $why"}\n'
                expected=[]
                for chain,launch,*_ in CONTRACT['level_rules']:
                    expected.append(['-datapath_only','8.0','-from',BANK+'/'+launch+'/C','-to',BANK+'/'+chain+'/stages_reg[0]/D'])
                body+='set expected '+review.tcl(expected)+'\n'
                body+='foreach a $bounds b $expected {set n [list {*}[lrange $a 0 2] [lindex [lindex $a 3] 0] [lindex $a 4] [lindex [lindex $a 5] 0]]; if {$n ne $b} {error {broadened/wrong level bound}}}\n'
            script='if {[catch {\n'+body+'\n} why]} {puts stderr $why;exit 1}\nputs NARROW_SCOPE_MOCK_PASS\n'
            r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('NARROW_SCOPE_MOCK_PASS',r.stdout)

    def test_negative_structure_and_scopes(self):
        mutations=[
            ('dict unset MODEL $bank/txRate','census mismatch'),
            ('dict unset MODEL $bank/physicalIngress/crossing/fifo','census mismatch'),
            ('dict set MODEL $bank/rogue [dict create KIND cell NAME $bank/rogue REF_NAME CdcMailbox IS_SEQUENTIAL 0]','census mismatch'),
            ('dict set MODEL [format {%s/txLink_sync/stages_reg[0]} $bank] ASYNC_REG FALSE','missing ASYNC_REG'),
            ('dict set MODEL [format {%s/txLink_sync/stages_reg[0]/C} $bank] CLOCK cpu_clk','wrong register clock'),
            ('dict set MODEL [format {%s/txLink_sync/stages_reg[1]/D} $bank] NET gnd','indirect stage'),
            ('dict set MODEL $bank/tx/busy_reg/D NET [format {%s/txLink_sync/stages_reg[0]_q} $bank]','first-stage functional fanout'),
            ('dict set MODEL [format {%s/txLink_sync/stages_reg[0]/D} $bank] NET cold','one expected Q bit'),
            ('dict set MODEL $bank/mediaOpen_reg REF_NAME LUT1','reset primitive'),
            ('dict set MODEL $bank/mediaOpen_reg IS_CLR_INVERTED 1','inverted asynchronous reset'),
            ('dict set MODEL $bank/mediaOpen_reg INIT 1','INIT/reset value mismatch'),
            ('dict set MODEL $bank/mediaOpen_reg IS_C_INVERTED 1','inverted register clock'),
            ('dict set MODEL [format {%s/txLink_sync/stages_reg[0]/CE} $bank] NET gnd','CE must be always enabled'),
            ('dict set MODEL $bank/epoch_or/O NET cold','does not have one leaf driver'),
            ('dict set MODEL $bank/epoch_or/O NET $bank/mediaOpen_reg_q','one expected Q bit'),
            ('dict set MODEL $bank/tx/busy_reg/D NET $bank/mediaOpen_reg_q','exactly three destination chains'),
            ('dict set MODEL $bank/epoch_or INIT 4\'h8','two-input OR mapping'),
            ('dict set MODEL $bank/epoch_or/I0 NET $bank/ingressEmptySource_reg_q','registered epoch Q OR direct cold reset'),
            ('dict set MODEL $bank/epoch_or/I1 NET gnd','nets differ'),
            ('dict set MODEL $bank/tx/busy_reg/CLR NET epoch','unexpected/omits physical reset endpoints'),
            ('dict set MODEL $bank/txStats/commonReset NET epoch','nets differ'),
            ('dict set MODEL $bank/rxRate/destinationClock CLOCK cpu_clk','mailbox source/destination clock role changed'),
            ('dict set MODEL $bank/physicalIngress/crossing/fifo/sourceClock CLOCK cpu_clk','FIFO source/destination clock role changed'),
            ('dict unset MODEL [format {%s/txConfig/mailbox/captured_reg[0]} $bank]','bank shape changed'),
            ('dict set MODEL [format {%s/txConfig/mailbox/captured_reg[0]/D} $bank] NET [format {%s/txConfig/mailbox/held_reg[1]_q} $bank]','wrong-bit source'),
            ('dict set MODEL [format {%s/txFifo/fifo/readGraySync_stage0_reg[0]/D} $bank] NET [format {%s/txFifo/fifo/readGray_reg[1]_q} $bank]','Gray launch bit/source mismatch'),
            ('dict set MODEL [format {%s/txFifo/fifo/output_0_reg[0]/D} $bank] STARTPOINTS {}','uncovered payload bit'),
            ('dict set MODEL [format {%s/txFifo/fifo/output_0_reg[37]/D} $bank] EXCEPTION {}','missing/ignored/relaxed max-delay bound'),
            ('dict set MODEL [format {%s/txFifo/fifo/output_0_reg[37]/D} $bank] TIMING_STARTPOINTS [list $bank/txFifo/fifo/storage_ext/ram/a/CLK]','missing/false-pathed RAM path'),
            ('dict set MODEL [format {%s/txRate/captured_reg[0]/D} $bank] CUT 1','missing/false-pathed'),
            ('dict set MODEL [format {%s/txRate/captured_reg[0]/D} $bank] REQUIREMENT 40','relaxed timing requirement'),
            ('dict set MODEL [format {%s/txRate/captured_reg[0]/D} $bank] REQUIREMENT Inf','relaxed timing requirement'),
            ('dict set MODEL [format {%s/txRate/captured_reg[0]/D} $bank] BAD_ENDPOINT other/D','timing endpoint mismatch'),
            ('dict set MODEL [format {%s/txRate/captured_reg[0]/D} $bank] SLACK -0.1','timing violation'),
            ('dict set MODEL $bank/txWireDrainedSource_reg/D CUT 1','missing/false-pathed'),
            ('dict set MODEL $bank/rx/active_reg/D CUT 1','cut/missing related functional'),
            ('dict set MODEL $bank/txManaged_gate/buffer/O CLOCK cpu_clk','clock period mismatch'),
            ('dict set MODEL unrelated [dict create KIND clock NAME unrelated PERIOD 8.0];dict set MODEL $bank/txManaged_gate/buffer/O CLOCK unrelated','not the same propagated raw125'),
        ]
        for mutation, expected in mutations:
            with self.subTest(expected=expected,mutation=mutation): self.run_model(mutation,expected)


class FifoPayloadTclTests(unittest.TestCase):
    """Leaf discovery and per-reachable-leaf coverage; no physical proof."""
    def run_payload(self, mutation='', expected=None, bounds=0):
        h = BANK+'/txFifo/fifo'
        model = SyntheticMapping().m
        model = {k:v for k,v in model.items() if k.startswith(h+'/') or v['KIND']=='clock'}
        body='set MODEL '+review.tcl(model)+'\n'
        body+='source '+review.tcl(HERE/'tests/mac_netlist_mock.tcl')+'\n'
        body+='source '+review.tcl(ROOT/'fpga/zu15eg/native-gmac-cdc-constraints.tcl')+'\n'
        body+='set h '+review.tcl(h)+'\n'+mutation+'\nmock_reindex\n'
        body+='set rc [catch {valence_fifo_payload_constraints $h 8.0} why]\n'
        if expected:
            body+='if {!$rc || [string first '+review.tcl(expected)+' $why]<0} {error "wrong failure: $rc $why"}\n'
            body+='if {[llength $BOUND_CALLS]!='+str(bounds)+'} {error {partial/unexpected constraint application}}\n'
        else:
            body+=r'''
if {$rc} {error $why}
if {[llength $BOUND_CALLS]!=2} {error {expected exact max-delay and skew bounds}}
set expected [list $h/storage_ext/ram/a/CLK $h/storage_ext/ram/b/CLK]
foreach call $BOUND_CALLS {
    set args [lindex $call 1]
    if {[opt $args -from] ne $expected || [llength [opt $args -to]]!=38} {error {composite/FF/wrong scope bounded}}
}
# 57 reachable leaf/bit pairs queried once before and once after application.
if {[llength $TIMING_CALLS]!=114} {error {missing per-leaf per-bit query}}
set scope [valence_fifo_payload::collect $h]
dict for {end ordinary} [dict get $scope ordinary_by_end] {
    if {[llength $ordinary]!=2} {error {ordinary destination-domain launches were dropped}}
}
'''
        body+='puts FIFO_MOCK_PASS_NOT_VIVADO\n'
        script='if {[catch {\n'+body+'\n} why opts]} {puts stderr $why; puts stderr [dict get $opts -errorinfo]; exit 1}\n'
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('FIFO_MOCK_PASS_NOT_VIVADO',r.stdout)

    def test_composite_present_but_only_reachable_leaf_clocks_bounded(self):
        self.run_payload()

    def test_bad_leaf_shapes_rejected_before_constraints(self):
        for mutation, expected in [
            ('dict set MODEL [format {%s/output_0_reg[0]/D} $h] STARTPOINTS [list $h/storage_ext/ram/WCLK]', 'not a reviewed leaf clock'),
            ('dict set MODEL $h/storage_ext/ram/a REF_NAME RAM32M16', 'not a reviewed leaf clock'),
            ('dict set MODEL $h/storage_ext/ram/a/CLK IS_LEAF 0', 'not a reviewed leaf clock'),
            ('dict set MODEL $h/storage_ext/ram/a IS_PRIMITIVE 0', 'not a reviewed leaf clock'),
            ('dict set MODEL $h/storage_ext/ram/a/CLK CLOCK raw_clk', 'write clock mismatch'),
            ('dict set MODEL $h/storage_ext/ram/a/CLK CLOCK {cpu_clk raw_clk}', 'ambiguous clock'),
        ]:
            with self.subTest(mutation=mutation): self.run_payload(mutation,expected)

    def test_missing_ambiguous_or_wrong_capture_shape(self):
        for mutation, expected in [
            ('dict unset MODEL [format {%s/output_0_reg[0]} $h]', 'capture bank shape changed'),
            ('dict set MODEL [format {%s/output_0_reg[0]} $h] REF_NAME LUT1', 'not a reviewed FF'),
            ('dict unset MODEL [format {%s/output_0_reg[0]/D} $h]', 'capture pin/clock shape changed'),
            ('dict set MODEL [format {%s/output_0_reg[0]/C} $h] CLOCK cpu_clk', 'capture pin/clock shape changed'),
            (r'''rename get_cells mock_get_cells
proc get_cells {args} {
    set result [mock_get_cells {*}$args]
    if {[llength $result]==1 && [string match {*output_0_reg*} [lindex $result 0]]} {return [concat $result $result]}
    return $result
}''', 'exact object missing/ambiguous'),
        ]:
            with self.subTest(mutation=mutation): self.run_payload(mutation,expected)

    def test_uncovered_bit_or_missing_one_of_several_ram_paths(self):
        for mutation, expected in [
            ('dict set MODEL [format {%s/output_0_reg[37]/D} $h] STARTPOINTS {}', 'uncovered payload bit'),
            ('dict set MODEL [format {%s/output_0_reg[37]/D} $h] STARTPOINTS [list [format {%s/readGray_reg[0]/Q} $h]]', 'not a reviewed leaf FF clock'),
            ('dict set MODEL [format {%s/output_0_reg[37]/D} $h] TIMING_STARTPOINTS [list $h/storage_ext/ram/a/CLK]', 'missing/false-pathed RAM path'),
            ('dict set MODEL [format {%s/output_0_reg[37]/D} $h] CUT 1', 'missing/false-pathed RAM path'),
            ('dict set MODEL [format {%s/output_0_reg[37]/D} $h] BAD_ENDPOINT [format {%s/output_0_reg[36]/D} $h]', 'startpoint/endpoint mismatch'),
            ('dict set MODEL [format {%s/output_0_reg[37]/D} $h] BAD_STARTPOINT $h/storage_ext/ram/WCLK', 'startpoint/endpoint mismatch'),
        ]:
            with self.subTest(mutation=mutation): self.run_payload(mutation,expected)

    def test_ignored_bound_with_ordinary_eight_ns_path_is_not_accepted(self):
        self.run_payload(r'''
set IGNORE_BOUNDS 1
for {set i 0} {$i<38} {incr i} {
    dict set MODEL [format {%s/output_0_reg[%d]/D} $h $i] EXCEPTION {}
    dict set MODEL [format {%s/output_0_reg[%d]/D} $h $i] REQUIREMENT 8.0
}''', 'missing/ignored/relaxed max-delay bound', bounds=2)

    def test_non_ram_launches_are_validated_with_ram_paths_still_present(self):
        # Each negative keeps both legal RAM launches for bit 37. Coverage of
        # the memory alone cannot make a foreign/unknown bypass acceptable.
        add=r'''set end [format {%s/output_0_reg[37]/D} $h]
set fanin [dict get $MODEL $end STARTPOINTS]
'''
        for mutation, expected in [
            (r'''lappend fanin [format {%s/writeGray_reg[0]/C} $h]
dict set MODEL $end STARTPOINTS $fanin''', 'foreign-domain ordinary launch'),
            (r'''dict set MODEL [format {%s/storage_ext/readAddress_reg[0]/C} $h] CLOCK cpu_clk''', 'foreign-domain ordinary launch'),
            (r'''lappend fanin [format {%s/readGray_reg[0]/Q} $h]
dict set MODEL $end STARTPOINTS $fanin''', 'not a reviewed leaf FF clock'),
            (r'''dict set MODEL external_input [dict create KIND port NAME external_input]
lappend fanin external_input
dict set MODEL $end STARTPOINTS $fanin''', 'unknown timing startpoint owner'),
            (r'''dict set MODEL outside_lut [dict create KIND cell NAME outside_lut REF_NAME LUT1 IS_SEQUENTIAL 0 IS_PRIMITIVE 1]
dict set MODEL outside_lut/O [dict create KIND pin NAME outside_lut/O CELL outside_lut REF_PIN_NAME O NET outside_net DIRECTION OUT LEAF 1 IS_LEAF 1 CLOCK raw_clk]
lappend fanin outside_lut/O
dict set MODEL $end STARTPOINTS $fanin''', 'not a reviewed leaf clock'),
            (r'''dict set MODEL [format {%s/readGray_reg[0]/C} $h] IS_LEAF 0''', 'not a reviewed leaf FF clock'),
        ]:
            with self.subTest(mutation=mutation): self.run_payload(add+mutation,expected)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.export=self.base/'export';(self.export/'board').mkdir(parents=True)
        (self.export/'board/soc_top_fpga_next_ddr.sv').write_text('// synthetic mock board\n')
        (self.export/'rtl').mkdir();(self.export/'rtl/top.sv').write_text('// synthetic not emitted\n')
        (self.export/'synthesis-files.f').write_text('rtl/top.sv\n')
        staged=media.stage(ROOT,self.export)
        self.receipt={'status':'PASS_RTL_EXPORT_ONLY','source_sha256':exporter.sources(),
            'tri_speed_native_integration':staged,'rtl_sha256':{'rtl/top.sv':review.sha(self.export/'rtl/top.sv')},
            'synthesis_filelist_sha256':review.sha(self.export/'synthesis-files.f')}
        review.dump(self.export/'receipt.json',self.receipt)

    def test_source_closure_and_stage(self):
        self.assertTrue(set(review.INPUTS).issubset(exporter.sources()))
        r,b=review.verified_export(self.export)
        self.assertEqual(b['status'],review.STATUS)
        self.assertEqual(r,self.receipt)

    def test_contract_rejects_legacy_census(self):
        for key in ('mailboxes','fifos'):
            bad=copy.deepcopy(INVENTORY);bad[key].pop()
            with self.assertRaisesRegex(RuntimeError,'exact 9/3'):review.contract(bad)

    def test_every_bound_artifact_drift_rejected(self):
        for name in ('audit_mac_netlist.tcl','mac-netlist-binding.tcl','mac-netlist-binding.json','mac_netlist_review.py','mac-boundary-cdc-inventory.json'):
            path=self.export/'board'/name;original=path.read_bytes();path.write_bytes(original+b'\n')
            with self.assertRaisesRegex(RuntimeError,'hash mismatch'):review.verified_export(self.export)
            path.write_bytes(original)
        path=self.export/'rtl/top.sv';path.write_text('changed\n')
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):review.verified_export(self.export)

    def test_source_mismatch_rejected(self):
        self.receipt['source_sha256'][review.INPUTS[-1]]='0'*64;review.dump(self.export/'receipt.json',self.receipt)
        with self.assertRaisesRegex(RuntimeError,'differs from emitted'):review.verified_export(self.export)

    def proof(self):
        checkpoint=self.base/'toy.dcp';checkpoint.write_bytes(b'SYNTHETIC_NOT_DCP')
        log=self.base/'mock.log';log.write_text('SYNTHETIC_NO_IMPLEMENTATION\n')
        constraint_files={}
        for name in ('trispeed_board_constraints.tcl','native-gmac-cdc-constraints.tcl','cdc_constraints.tcl','mac_registered_level_constraints.tcl'):
            target=self.base/name;shutil.copy2(self.export/'board'/name,target);constraint_files[name]=review.sha(target)
        data={'schema':'valence-mac-checkpoint-provenance-v1','export_receipt_sha256':review.sha(self.export/'receipt.json'),
            'checkpoint_sha256':review.sha(checkpoint),'rate_mbps':1000,'source_sha256':self.receipt['source_sha256'],
            'rtl_sha256':self.receipt['rtl_sha256'],'implementation_log_sha256':{'mock.log':review.sha(log)},
            'constraint_files_sha256':constraint_files}
        proof=self.base/'mock-provenance.json';review.dump(proof,data)
        return checkpoint,proof,data

    def test_prepare_only_and_checkpoint_drift(self):
        checkpoint,proof,_=self.proof();job=self.base/'job'
        data=review.prepare_job(self.export,checkpoint,proof,job,1000)
        self.assertFalse(data['vivado_run']);self.assertFalse(data['netlist_qualified'])
        self.assertIn('VERIFIED_NOT_NETLIST_QUALIFIED',review.verify_job(job/'job.json'))
        self.assertFalse((job/'reports').exists())
        checkpoint.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'byte identity changed'):review.verify_job(job/'job.json')

    def test_wrong_provenance_and_rate_rejected(self):
        checkpoint,proof,data=self.proof()
        for key in ('checkpoint_sha256','export_receipt_sha256','rate_mbps','source_sha256','rtl_sha256'):
            bad={**data,key:'wrong'};review.dump(proof,bad)
            with self.assertRaisesRegex(RuntimeError,'provenance does not bind'):review.prepare_job(self.export,checkpoint,proof,self.base/'job',1000)

    def test_constraint_and_implementation_evidence_required(self):
        checkpoint,proof,data=self.proof()
        missing=copy.deepcopy(data);missing['constraint_files_sha256'].pop('mac_registered_level_constraints.tcl')
        review.dump(proof,missing)
        with self.assertRaisesRegex(RuntimeError,'omits current packet'):review.prepare_job(self.export,checkpoint,proof,self.base/'job',1000)
        review.dump(proof,data);(self.base/'mock.log').write_text('changed\n')
        with self.assertRaisesRegex(RuntimeError,'provenance artifact drift'):review.prepare_job(self.export,checkpoint,proof,self.base/'job',1000)

    def test_tcl_values_do_not_execute(self):
        dangerous='a[error INJECTED]$x"\\{}\n;error bad'
        script='set x '+review.tcl(dangerous)+'\nputs [string length $x]\n'
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
        self.assertEqual(r.returncode,0);self.assertEqual(r.stderr,'');self.assertEqual(int(r.stdout),len(dangerous))


if __name__=='__main__':unittest.main()
