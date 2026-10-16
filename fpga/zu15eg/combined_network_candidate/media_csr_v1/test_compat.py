from pathlib import Path
import subprocess,unittest
H=Path(__file__).resolve().parent
BASE=r'''
namespace eval valence_mac {}
set r u_soc/board/nativeBank/gmac
set expected {};foreach chain {txLink_sync rxLink_sync rawRxOpen_sync} {lappend expected [format {%s/%s/stages_reg[0]/D} $r $chain]}
set actual [lsort [concat $expected [list $r/csr_i_3/I0]]]
proc valence_mac::loads {p} {return $::actual}
proc valence_mac::collect {contract binding output mbps} {
        if {[loads $root/mediaOpen_reg/Q] ne [lsort $media_loads]} {error "MAC mediaOpen is not exactly three destination chains"}
}
proc valence_mac::one {cmd p} {return $p}
proc valence_mac::names {obj} {return [lsort -unique $obj]}
proc valence_mac::same_net {a b} {if {$::badnet} {error badnet}}
proc valence_mac::clock {p} {if {$::badclock && [string match *pending* $p]} {return wrong};return clk_out1_clk_wiz_ddr}
proc valence_native_mac_verify_export {} {return $::identity}
proc get_clocks {p} {return $p}
proc all_fanout {args} {return $::ends}
proc get_property {prop obj} {
 switch $prop {
 REF_NAME {if {[string match *csr_i_3 $obj]} {return $::lutref};return $::ffref}
 INIT {return $::init}
 PERIOD {return $::period}
 IS_INVERTED {return $::inverted}
 default {error "unknown property $prop"}
 }
}
'''
class CompatTests(unittest.TestCase):
 def run_case(self,extra='',accept=False):
  defaults="set identity a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615;set badnet 0;set badclock 0;set lutref LUT2;set ffref FDCE;set init 4'h6;set period 10;set inverted 0\n"
  s=defaults+BASE+'\nset ends [list [format {%s/csr/pending_reg[5]/D} $r]]\n'+extra+f'\nsource {{{H}/install_media_csr_compat.tcl}}\n'
  s+='if {[catch {valence_mac::media_csr_merge_check_v1 $r/mediaOpen_reg/Q $actual} result]} {puts REJECT} else {if {$result ne $actual} {error wrongresult};puts ACCEPT}\n'
  p=subprocess.run(['tclsh'],input=s,text=True,capture_output=True)
  self.assertEqual(p.stderr,'');self.assertEqual(p.stdout.strip().splitlines()[-1],'ACCEPT' if accept else 'REJECT')
 def test_exact_merge_and_legacy(self):
  self.run_case(accept=True);self.run_case('set actual [lsort $expected]',True)
 def test_extra_missing_wrong_source(self):
  for x in ('lappend actual unknown/D','set actual [lrange $actual 0 end-1]','set identity bad'):
   self.run_case(x)
 def test_cone_clock_negatives(self):
  for x in ('set lutref LUT3',"set init 4'h8",'set badnet 1','set ends bad/D','lappend ends other/D','set ffref FDRE','set badclock 1','set period 8','set inverted 1'):
   self.run_case(x)
if __name__=='__main__':unittest.main()
