from pathlib import Path
import tkinter
t=tkinter.Tcl()
s=(Path(__file__).resolve().parents[1]/'fpga/common/recovery_map_constraints.tcl').read_text()
t.eval(s[s.index('namespace eval board_prep'):s.index('puts "PREPARATION_TOOL')])
t.eval('''
namespace eval common_cdc {}
namespace eval valence_fifo_payload {}
proc get_property {property objects} {return $objects}
foreach ns {::common_cdc ::valence_fifo_payload} {
 proc ${ns}::one {kind name} {error uncached}
 proc ${ns}::objects {kind names} {error uncached}
}
proc ::common_cdc::bank {prefix width} {error uncached}
proc ::common_cdc::inactive {fifo} {foreach c [get_cells -quiet -hier -filter {IS_PRIMITIVE == TRUE}] {}}
proc ::common_cdc::collect {{root u_soc/crossing}} {foreach c [get_cells -quiet -hier] {}}
foreach p {gray payload level mailbox} {proc ::common_cdc::$p {args} {}}
proc ::board_prep::cache {} {
 variable cells; variable pins;variable banks
 set cells [dict create foo foo];set pins [dict create foo/C foo/C]
 set banks [dict create foo {{foo[0]} {foo[1]}}]
}
proc ::board_prep::lane_evidence {} {}
::board_prep::install_cache_helpers
''')
assert t.call('common_cdc::one','get_pins','foo/C')=='foo/C'
t.eval('proc get_pins {args} {if {$args ne {-quiet -of_objects foo -filter {REF_PIN_NAME == D}}} {error "not exact-owner lookup"}; return foo/D}')
assert t.call('common_cdc::one','get_pins','foo/D')=='foo/D'
try:
    t.call('common_cdc::one','get_pins','absent/D')
    raise AssertionError('missing owner accepted')
except tkinter.TclError:
    pass
assert len(t.splitlist(t.call('common_cdc::bank','foo',2)))==2
assert t.call('info','default','::common_cdc::collect','root','default')==1
assert t.getvar('default')=='u_soc/crossing'
assert not t.call('info','commands','::board_prep::common_cdc::*')
print('PASS: absolute helper namespaces, exact cached pins, complete bank shape and default arguments retained')
