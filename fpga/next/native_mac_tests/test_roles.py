import subprocess
import os
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parent
AUDIT=Path(os.environ.get('MAC_BRIDGE_SOURCE', HERE.parents[2])).resolve()/'fpga/next/native_mac_roles.tcl'
class RoleTests(unittest.TestCase):
    def run_tcl(self, text):
        script=f'source {{{HERE/"typed_mock.tcl"}}}\nsource {{{AUDIT}}}\n'+text
        proc=subprocess.run(['tclsh'],input='if {[catch {\n'+script+'\n} err opts]} {puts stderr $err; puts stderr [dict get $opts -errorinfo]; exit 1}\n',capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr)
        return proc.stdout
    def test_four_modes(self):
        for t1 in (0,1):
            for selected in (0,1):
                with self.subTest(t1=t1,selected=selected):
                    out=self.run_tcl(f'fixture {t1} {selected}\nputs [valence_mac_roles::audit u_rgmii {t1} {selected}]')
                    self.assertIn('PASS_MAC_ROLE_SEMANTICS',out)
    def test_merged_control_and_retired_fall_require_source_lemma(self):
        for dead in ('connected','ground','disconnected'):
            for t1 in (0,1):
                for selected in (0,1):
                    with self.subTest(dead=dead,t1=t1,selected=selected):
                        text=f'fixture {t1} {selected} 1 {dead}\nnamespace eval valence_native_mac_mode {{variable control_lemma 1}}\nputs [valence_mac_roles::audit u_rgmii {t1} {selected}]'
                        self.assertIn('source_control_lemma 1',self.run_tcl(text))
                        if dead!='connected':
                            self.run_tcl(f'fixture {t1} {selected} 1 {dead}\nnamespace eval valence_native_mac_mode {{variable control_lemma 0}}\nif {{![catch {{valence_mac_roles::audit u_rgmii {t1} {selected}}}]}} {{error {{dead fall accepted without source proof}}}}')
    def test_exact_dead_fall_role_and_scoped_consumers(self):
        pin='{u_rgmii/tx_fall[4]}'
        mutations=[
            'dict unset db pin '+pin,
            'dict set pinOverrides '+pin+' [list '+pin+' '+pin+']',
            'dict set db pin '+pin+' DIRECTION OUT',
            'dict set db pin '+pin+' IS_LEAF 1',
            'dict set netOverrides direct '+pin+' {}',
            'dict set netOverrides segments '+pin+' {}',
            'dict set netOverrides direct '+pin+' {deadGround ground}',
            'add_cell u_rgmii/rogue LUT1;add_pin u_rgmii/rogue I0 deadGround',
            'dict set db net innerGround [dict create NAME innerGround TYPE GROUND];dict set netOverrides segments '+pin+' {deadGround innerGround};add_cell u_rgmii/nested/rogue LUT1;add_pin u_rgmii/nested/rogue I0 innerGround',
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.run_tcl('fixture 1 1 1 ground\nnamespace eval valence_native_mac_mode {variable control_lemma 1}\n'+mutation+'\nif {![catch {valence_mac_roles::audit u_rgmii 1 1}]} {error {malformed retired fall accepted}}')
        self.run_tcl('fixture 1 1 1 ground\nnamespace eval valence_native_mac_mode {variable control_lemma 1}\nadd_cell outside/consumer LUT1;add_pin outside/consumer I0 deadGround\nadd_cell u_rgmiievil/consumer LUT1;add_pin u_rgmiievil/consumer I0 deadGround\nputs [valence_mac_roles::audit u_rgmii 1 1]')
        self.run_tcl('fixture 1 1 1 ground\nnamespace eval valence_native_mac_mode {variable control_lemma 1}\ndict set db net outsideGround [dict create NAME outsideGround TYPE GROUND]\ndict set netOverrides segments {u_rgmii/tx_fall[4]} {deadGround outsideGround}\nadd_cell outside/consumer LUT1;add_pin outside/consumer I0 outsideGround\nputs [valence_mac_roles::audit u_rgmii 1 1]')
        # Any empty collection query would become an unsafe global query. None
        # is permitted for the exact retained, entirely disconnected role.
        self.run_tcl('fixture 1 1 1 disconnected\nnamespace eval valence_native_mac_mode {variable control_lemma 1}\nrename get_pins original_get_pins\nproc get_pins {args} {set at [lsearch -exact $args -of_objects];if {$at>=0 && ![llength [lindex $args [expr {$at+1}]]]} {error {empty collection broadened}};return [original_get_pins {*}$args]}\nputs [valence_mac_roles::audit u_rgmii 1 1]')

    def test_mutations(self):
        mutations=[
          'dict set conn {u_rgmii/oddr4/D[4]} high4',
          'dict set conn u_rgmii/low0/CE phaseNot',
          'dict set conn u_rgmii/high0/CE power',
          'dict set conn u_rgmii/previous/D high5',
          'dict set conn u_rgmii/high0/CLR rawReset',
          'dict set db cell u_rgmii/low0 INIT 1',
          'dict set db pin u_rgmii/low0/C IS_INVERTED 0',
          'dict set db cell u_rgmii/select0 INIT 8\'h35',
          'dict set conn u_rgmii/high4/D rise4',
          'dict set conn u_rgmii/release/CE ground',
          'dict set conn rawDivider/CLR unrelated',
          'dict set db clock padclock PERIOD 8',
          'lut u_rgmii/buffer {low0} buffer0 2\'h2\ndict set conn {u_rgmii/oddr0/D[0]} buffer0\ndict set conn {u_rgmii/oddr0/D[4]} buffer0',
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.run_tcl('fixture 1 1\n'+mutation+'\nif {![catch {valence_mac_roles::audit u_rgmii 1 1}]} {error {mutation escaped}}')
        self.run_tcl('fixture 1 0\nif {![catch {valence_mac_roles::audit u_rgmii 1 1}]} {error {OFF accepted as ON}}')
if __name__=='__main__': unittest.main()
