# Pure next-state evaluator for a specific held-data mailbox review.
# No Vivado commands or timing exceptions here. The resolver must reject
# unknown sequential leaves; it may never assign them a convenient value.
proc native_mbox_eval {pin values memo_name resolver} {
    upvar 1 $memo_name memo
    if {[dict exists $values $pin]} {return [dict get $values $pin]}
    if {[dict exists $memo $pin]} {
        set cached [dict get $memo $pin]
        if {$cached eq "VISITING"} {error "Mailbox combinational cycle at $pin"}
        return $cached
    }
    dict set memo $pin VISITING
    set gate [{*}$resolver $pin]
    set type [dict get $gate type]
    switch -- $type {
        CONST {set result [dict get $gate value]}
        LUT {
            set width [dict get $gate width]
            set inputs [dict get $gate inputs]
            set init [dict get $gate init]
            if {$width < 1 || $width > 6 || [llength $inputs] != $width || $init < 0 || $init >> (1 << $width)} {
                error "Invalid mailbox LUT description at $pin"
            }
            set index 0
            for {set n 0} {$n < $width} {incr n} {
                set bit [native_mbox_eval [lindex $inputs $n] $values memo $resolver]
                set index [expr {$index | ($bit << $n)}]
            }
            set result [expr {($init >> $index) & 1}]
        }
        INV {
            set inputs [dict get $gate inputs]
            if {[llength $inputs] != 1} {error "Invalid mailbox inverter at $pin"}
            set result [expr {1 ^ [native_mbox_eval [lindex $inputs 0] $values memo $resolver]}]
        }
        MUX {
            set inputs [dict get $gate inputs]
            if {[llength $inputs] != 3} {error "Invalid mailbox MUX at $pin"}
            set select [native_mbox_eval [lindex $inputs 2] $values memo $resolver]
            set result [native_mbox_eval [lindex $inputs $select] $values memo $resolver]
        }
        default {error "Unsupported mailbox gate $type at $pin"}
    }
    if {$result ni {0 1}} {error "Non-binary mailbox value at $pin"}
    dict set memo $pin $result
    return $result
}
proc native_mbox_check_next {d ce roles resolver {fixed_values {}}} {
    if {[lsort [dict keys $roles]] ne {ack captured held request valid}} {error "Incomplete mailbox roles"}
    if {[llength [lsort -unique [dict values $roles]]] != 5} {error "Aliased mailbox roles"}
    foreach pin [dict values $roles] {
        if {[dict exists $fixed_values $pin]} {error "Mailbox role overwritten by fixed value"}
    }
    for {set row 0} {$row < 32} {incr row} {
        lassign [list [expr {($row>>0)&1}] [expr {($row>>1)&1}] [expr {($row>>2)&1}] \
            [expr {($row>>3)&1}] [expr {($row>>4)&1}]] held captured valid request ack
        set values $fixed_values
        foreach name {held captured valid request ack} {dict set values [dict get $roles $name] [set $name]}
        set memo {}
        set enable [native_mbox_eval $ce $values memo $resolver]
        set data [native_mbox_eval $d $values memo $resolver]
        set actual [expr {$enable ? $data : $captured}]
        # Independent protocol recurrence, not copied from the netlist INIT.
        set expected [expr {!$valid && ($request != $ack) ? $held : $captured}]
        if {$actual != $expected} {error "Mailbox next-state mismatch row=$row D=$data CE=$enable actual=$actual expected=$expected"}
    }
    return 32
}
