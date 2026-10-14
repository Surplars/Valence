# PREPARED_NOT_NETLIST_QUALIFIED. Read-only queries/report files only.
# Source a hash-bound mac-netlist-binding.tcl first, then call the collector on
# an explicitly opened matching checkpoint. No timing exceptions or waivers are
# created here. Changed/optimized mapping fails closed for a reviewed update.
# Same read-only leaf/path queries as the active payload constraint recipe.
# Staged exports put these files together; source checkouts keep them in zu15eg.
set valence_mac_cdc_file [file join [file dirname [info script]] native-gmac-cdc-constraints.tcl]
if {![file exists $valence_mac_cdc_file]} {
    set valence_mac_cdc_file [file join [file dirname [info script]] .. zu15eg native-gmac-cdc-constraints.tcl]
}
source $valence_mac_cdc_file
unset valence_mac_cdc_file
namespace eval valence_mac {variable facts; variable out; variable clocks; variable root}

proc valence_mac::validate_contract {contract} {
    if {[dict get $contract version]!=1 || [dict get $contract root] ne "u_soc/board/nativeBank/gmac"} {error "MAC legacy or wildcard root/version rejected"}
    foreach {key expected} {
        mailbox_widths {txRate 2 rxRate 2 txConfig/mailbox 52 rxConfig/mailbox 52 txStats/mailbox 160 rxStats/mailbox 160 rxDiagnostics/mailbox 256 rawDiagnostics/mailbox 96 rxStop/command 1}
        fifo_pointer_widths {txFifo/fifo 5 rxFifo/fifo 5 physicalIngress/crossing/fifo 7}
        clock_pins {cpu sourceClock raw_tx rawTxClock raw_rx rawRxClock tx txManaged_gate/buffer/O rx rxManaged_gate/buffer/O}
        mailbox_clock_domains {txRate {cpu raw_tx} rxRate {cpu raw_rx} txConfig/mailbox {cpu tx} rxConfig/mailbox {cpu rx} txStats/mailbox {tx cpu} rxStats/mailbox {rx cpu} rxDiagnostics/mailbox {rx cpu} rawDiagnostics/mailbox {raw_rx cpu} rxStop/command {cpu rx}}
        fifo_clock_domains {txFifo/fifo {cpu tx} rxFifo/fifo {rx cpu} physicalIngress/crossing/fifo {raw_rx raw_tx}}
    } {
        if {[dict size [dict get $contract $key]]!=[dict size $expected]} {error "MAC exact current contract scope required: $key"}
        dict for {name value} $expected {
            if {![dict exists $contract $key $name] || [join [dict get $contract $key $name] /] ne [join $value /]} {error "MAC exact current contract shape required: $key/$name"}
        }
    }
    set expected {
        {txLink_sync mediaOpen_reg cpu tx cpuRelease txRelease}
        {rxLink_sync mediaOpen_reg cpu rx cpuRelease rxRelease}
        {rawRxOpen_sync mediaOpen_reg cpu raw_rx cpuRelease rawRxRelease}
        {ingressEmpty_sync ingressEmptySource_reg raw_tx cpu rawTxRelease cpuRelease}
        {txWireDrained_sync txWireDrainedSource_reg raw_tx cpu rawTxRelease cpuRelease}
    }
    if {[llength [dict get $contract level_rules]]!=5 || [dict get $contract fifo_payload_width]!=38} {error "MAC exact five-level/38-bit payload contract required"}
    foreach actual [dict get $contract level_rules] wanted $expected {
        if {[llength $actual]!=6 || [join $actual /] ne [join $wanted /]} {error "MAC exact registered launch/clock/reset rule required"}
    }
    if {[lsort [dict get $contract retired_chains]] ne [lsort {txAbort_sync rxAbort_sync rawRxAbort_sync physicalIngress_captureEnable_sync}]} {error "MAC retired independent chain inventory changed"}
}

proc valence_mac::one {command name} {
    # Literal indexed cell names are legal; verify returned NAME, never count
    # one wildcard match as proof of identity.
    set found [$command -quiet $name]
    if {[llength $found]!=1 || [get_property NAME $found] ne $name} {error "MAC exact object missing/ambiguous: $name"}
    return $found
}
proc valence_mac::names {objects} {
    set result {}; foreach obj $objects {lappend result [get_property NAME $obj]}
    return [lsort -unique $result]
}
proc valence_mac::quote {text} {return [regsub -all {[][{}().+*?^$\|\\]} $text {\\&}]}
proc valence_mac::cells {pattern} {return [get_cells -quiet -hierarchical -regexp $pattern]}
proc valence_mac::pins {objects ref} {return [get_pins -of_objects [valence_fifo_payload::objects get_cells $objects] -filter "REF_PIN_NAME == $ref"]}
proc valence_mac::drivers {pin} {
    return [names [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects [one get_pins $pin]] -filter {DIRECTION == OUT}]]
}
proc valence_mac::loads {pin} {
    return [names [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects [one get_pins $pin]] -filter {DIRECTION == IN}]]
}
proc valence_mac::same_net {a b} {
    set aa [get_nets -segments -of_objects [one get_pins $a]]
    set bb [get_nets -segments -of_objects [one get_pins $b]]
    foreach net $aa {if {[lsearch -exact $bb $net]>=0} {return}}
    error "MAC nets differ: $a / $b"
}
proc valence_mac::clock {pin} {
    set found [get_clocks -quiet -of_objects [one get_pins $pin]]
    if {[llength $found]!=1} {error "MAC missing/ambiguous clock: $pin"}
    return [get_property NAME $found]
}
proc valence_mac::ff {cell domain reset_value reset_net {async 0}} {
    variable clocks
    set obj [one get_cells $cell]
    if {[get_property IS_SEQUENTIAL $obj] ni {1 TRUE true 1'b1}} {error "MAC launch is not sequential: $cell"}
    set expected [expr {$reset_value ? "FDPE" : "FDCE"}]
    if {[get_property REF_NAME $obj] ne $expected} {error "MAC reset primitive/polarity requires review: $cell expected $expected"}
    set init [string tolower [get_property INIT $obj]]
    if {$init ni [expr {$reset_value ? {1 1'h1 1'b1} : {0 1'h0 1'b0}}]} {error "MAC INIT/reset value mismatch: $cell"}
    if {[clock $cell/C] ne [dict get $clocks $domain]} {error "MAC wrong register clock: $cell"}
    if {[get_property IS_INVERTED [one get_pins $cell/C]] ni {0 FALSE false 1'b0}} {error "MAC inverted register clock: $cell"}
    set rp [expr {$reset_value ? "PRE" : "CLR"}]
    if {[get_property IS_INVERTED [one get_pins $cell/$rp]] ni {0 FALSE false 1'b0}} {error "MAC inverted asynchronous reset: $cell"}
    same_net $cell/$rp $reset_net
    if {[llength [drivers $cell/$rp]]!=1} {error "MAC asynchronous reset does not have one leaf driver: $cell"}
    if {$async && [get_property ASYNC_REG $obj] ni {1 TRUE true 1'b1}} {error "MAC missing ASYNC_REG: $cell"}
    if {$async} {
        set ce [get_nets -of_objects [one get_pins $cell/CE]]
        if {[llength $ce]!=1 || [get_property TYPE $ce] ne "POWER"} {error "MAC synchronizer CE must be always enabled: $cell"}
    }
    return $obj
}
proc valence_mac::bank {prefix width} {
    set pattern "^[quote $prefix]"
    if {$width==1} {append pattern {$}} else {append pattern {\[[0-9]+\]$}}
    set found [names [cells $pattern]]
    set expected {}
    for {set i 0} {$i<$width} {incr i} {
        lappend expected [expr {$width==1 ? $prefix : [format {%s[%d]} $prefix $i]}]
    }
    if {$found ne [lsort $expected]} {error "MAC exact bank shape changed: $prefix width=$width actual=$found"}
    return $expected
}
proc valence_mac::release {path domain reset_net} {
    variable facts
    set cells [bank $path/release_0_reg 3]
    for {set i 0} {$i<3} {incr i} {
        set cell [lindex $cells $i]; ff $cell $domain 1 $reset_net 1
        if {$i==0} {
            set net [get_nets -of_objects [one get_pins $cell/D]]
            if {[llength $net]!=1 || [get_property TYPE $net] ne "GROUND"} {error "MAC reset release does not shift zero: $path"}
        } elseif {[drivers $cell/D] ne [list [lindex $cells [expr {$i-1}]]/Q]} {error "MAC indirect reset release: $path"}
        if {$i<2 && [loads $cell/Q] ne [list [lindex $cells [expr {$i+1}]]/D]} {error "MAC reset intermediate fanout: $cell"}
    }
    puts $facts [list RESET_RELEASE $path CLOCK=$domain RESET=$reset_net]
    return [lindex $cells 2]/Q
}
proc valence_mac::level {path launch source target source_reset target_reset} {
    variable facts
    ff $launch $source 0 $source_reset
    set stages [bank $path/stages_reg 2]
    foreach cell $stages {ff $cell $target 0 $target_reset 1}
    lassign $stages first second
    if {[drivers $first/D] ne [list $launch/Q]} {error "MAC first-stage launch is not the one expected Q bit: $path"}
    if {[drivers $second/D] ne [list $first/Q] || [loads $first/Q] ne [list $second/D]} {error "MAC indirect stage or first-stage functional fanout: $path"}
    puts $facts [list LEVEL $path LAUNCH=$launch/Q SOURCE=$source TARGET=$target]
    return [list $launch/C $first/D]
}
proc valence_mac::timed {label starts ends budget {skew 0} {hold 0}} {
    variable facts; variable out
    if {![llength $starts] || ![llength $ends]} {error "MAC empty timing scope: $label"}
    set starts [valence_fifo_payload::objects get_pins $starts]
    set ends [valence_fifo_payload::objects get_pins $ends]
    # One query per exact endpoint avoids the old count-only duplicate coverage
    # mistake. Check every returned endpoint identity and finite requirement.
    foreach end $ends {
        foreach type [expr {$hold ? {max min} : {max}}] {
            set paths [get_timing_paths -quiet -from $starts -to [one get_pins $end] -delay_type $type -max_paths 1 -nworst 1]
            if {[llength $paths]!=1} {error "MAC missing/false-pathed $type path: $label -> $end"}
            set p [lindex $paths 0]
            if {[get_property ENDPOINT_PIN $p] ne $end} {error "MAC timing endpoint mismatch: $label"}
            set req [get_property REQUIREMENT $p]; set slack [get_property SLACK $p]
            set numeric {^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$}
            if {![regexp $numeric $req] || ![regexp $numeric $slack] ||
                ($type eq "max" && ($req<=0 || $req>$budget+0.001))} {error "MAC missing/relaxed timing requirement: $label $req"}
            puts $facts [list TIMING $label $type TO=$end REQUIREMENT=$req SLACK=$slack]
            if {$slack<0} {error "MAC timing violation: $label -> $end slack=$slack"}
        }
    }
    set file [string map {/ _} $label]
    report_timing -from $starts -to $ends -delay_type max -max_paths [llength $ends] -nworst 1 -input_pins -file [file join $out ${file}_max.rpt]
    if {$hold} {report_timing -from $starts -to $ends -delay_type min -max_paths [llength $ends] -nworst 1 -input_pins -file [file join $out ${file}_min.rpt]}
    report_exceptions -from $starts -to $ends -coverage -file [file join $out ${file}_exceptions.rpt]
    # report_bus_skew is a report, not a get_* property API. Keep exact scopes
    # and require explicit downstream review; never infer active skew from a
    # successful command or fabricate a pass by parsing an unknown tool format.
    puts $facts [list SCOPE $label FROM=$starts TO=$ends BUDGET=$budget SKEW_REVIEW_REQUIRED=$skew]
}
proc valence_mac::census {ref expected} {
    variable root
    set found {}
    foreach cell [get_cells -quiet -hierarchical -filter "REF_NAME =~ $ref*"] {
        set name [get_property NAME $cell]
        if {[string first $root/ $name]==0} {lappend found [string range $name [expr {[string length $root]+1}] end]}
    }
    if {[lsort $found] ne [lsort $expected]} {error "MAC $ref census mismatch: $found expected $expected"}
}
proc valence_mac::collect {contract binding output mbps} {
    variable facts; variable out; variable root; variable clocks
    if {[dict get $contract version]!=1 || [dict get $binding status] ne "SOURCE_BOUND_PREPARED_NOT_NETLIST_QUALIFIED"} {error "MAC unsupported/unbound collector contract"}
    validate_contract $contract
    set root [dict get $contract root]
    if {$root ne "u_soc/board/nativeBank/gmac"} {error "MAC legacy or wildcard root rejected"}
    if {$mbps ni {10 100 1000}} {error "MAC explicit 10/100/1000 scenario required"}
    if {[file exists $output]} {error "MAC fresh report directory required"}
    one get_cells $root
    if {![string match TriSpeedManagedGmac* [get_property REF_NAME [get_cells $root]]]} {error "MAC root module changed"}
    census CdcMailbox [dict keys [dict get $contract mailbox_widths]]
    census CdcDataFifo [dict keys [dict get $contract fifo_pointer_widths]]
    set clocks [dict create]
    dict for {domain pin} [dict get $contract clock_pins] {dict set clocks $domain [clock $root/$pin]}
    set rx_period [dict get {1000 8.0 100 40.0 10 400.0} $mbps]
    foreach {domain expected} [list cpu 10.0 raw_tx 8.0 tx 8.0 rx 8.0 raw_rx $rx_period] {
        if {abs([get_property PERIOD [get_clocks [dict get $clocks $domain]]]-$expected)>0.001} {error "MAC clock period mismatch: $domain"}
    }
    foreach domain {tx rx} {
        # BUFGCE forwards the raw clock. An independently declared clock is not
        # accepted merely because it also says 125MHz.
        if {[dict get $clocks $domain] ne [dict get $clocks raw_tx]} {error "MAC managed clock is not the same propagated raw125 clock: $domain"}
        same_net $root/rawTxClock $root/${domain}Managed_gate/buffer/I
        if {[get_property REF_NAME [one get_cells $root/${domain}Managed_gate/buffer]] ne "BUFGCE"} {error "MAC managed gate mapping changed"}
    }
    file mkdir $output; set out $output
    set facts [open [file join $out facts.tcllist] w]
    try {
        puts $facts [list BINDING $binding]; puts $facts [list CLOCKS $clocks]
        set release_q [dict create]
        foreach {name domain} {cpuRelease cpu rawTxRelease raw_tx rawRxRelease raw_rx txRelease tx rxRelease rx} {
            dict set release_q $name [release $root/$name $domain $root/commonReset]
        }
        foreach row [dict get $contract level_rules] {
            lassign $row chain source from to sr tr
            set scope [level $root/$chain $root/$source $from $to [dict get $release_q $sr] [dict get $release_q $tr]]
            timed $chain [list [lindex $scope 0]] [list [lindex $scope 1]] 8.0
        }
        set media_loads {}; foreach chain {txLink_sync rxLink_sync rawRxOpen_sync} {lappend media_loads [format {%s/%s/stages_reg[0]/D} $root $chain]}
        if {[loads $root/mediaOpen_reg/Q] ne [lsort $media_loads]} {error "MAC mediaOpen is not exactly three destination chains"}
        foreach retired [dict get $contract retired_chains] {
            if {[llength [cells "^[quote $root/$retired](/|$)"]]} {error "MAC retired independent chain remains: $retired"}
        }
        epoch $release_q
        dict for {path width} [dict get $contract mailbox_widths] {mailbox $path $width {*}[dict get $contract mailbox_clock_domains $path]}
        dict for {path width} [dict get $contract fifo_pointer_widths] {fifo $path $width [dict get $contract fifo_payload_width] {*}[dict get $contract fifo_clock_domains $path]}
        # This new launch includes managed TX combinational state. Require each
        # real sequential fanin to retain a min AND max path into the raw125 FF.
        set end $root/txWireDrainedSource_reg/D
        set starts [all_fanin -flat -startpoints_only -to [one get_pins $end]]
        set tx_seen 0
        foreach start $starts {
            set c [get_cells -quiet -of_objects $start]
            if {[llength $c]!=1 || [get_property IS_SEQUENTIAL $c] ni {1 TRUE true 1'b1}} {error "MAC unreviewed idle-source fanin: $start"}
            if {[string first $root/tx/ [get_property NAME $c]]==0} {set tx_seen 1}
            set clkpin [one get_pins [get_property NAME $c]/C]
            if {[clock $clkpin] ne [dict get $clocks raw_tx]} {error "MAC idle-source fanin is not related raw/managed TX"}
            timed related_tx_idle_[get_property NAME $c] [list $clkpin] [list $end] 8.0 0 1
        }
        if {!$tx_seen} {error "MAC missing actual managed-TX to raw idle dependency"}
        related_pair encode tx
        related_pair ingress rx
        report_cdc -details -file [file join $out cdc.rpt]
        report_clock_interaction -file [file join $out clock_interaction.rpt]
        report_exceptions -coverage -file [file join $out exceptions_coverage.rpt]
        report_exceptions -ignored -file [file join $out exceptions_ignored.rpt]
        # UG835 report_bus_skew has no -from/-to switches. Save every current
        # constraint with per-bit detail, then reconcile with the SCOPE rows.
        report_bus_skew -cells [get_cells $root] -max_paths 1000 -nworst 1 -input_pins -warn_on_violation -file [file join $out bus_skew.rpt]
        report_timing_summary -report_unconstrained -file [file join $out timing_summary.rpt]
        puts $facts [list STATUS FACTS_COLLECTED_REVIEW_REQUIRED_NOT_NETLIST_QUALIFIED]
        puts $facts [list REQUIRED_REVIEW [dict get $contract required_review]]
    } finally {close $facts}
    return FACTS_COLLECTED_REVIEW_REQUIRED_NOT_NETLIST_QUALIFIED
}

proc valence_mac::related_pair {source target} {
    variable root; variable clocks
    set groups {}
    foreach prefix [list $source $target] {
        set regs {}
        foreach c [cells "^[quote $root/$prefix/].+"] {
            if {![string match FD* [get_property REF_NAME $c]]} {continue}
            if {[clock $c/C] ne [dict get $clocks raw_tx]} {error "MAC functional raw/managed register clock changed: $c"}
            lappend regs $c
        }
        if {![llength $regs]} {error "MAC missing related functional register scope: $prefix"}
        lappend groups $regs
    }
    lassign $groups launches captures
    set starts [pins $launches C]; set ends [pins $captures D]
    foreach type {max min} {
        set paths [get_timing_paths -quiet -from $starts -to $ends -delay_type $type -max_paths 1 -nworst 1]
        if {[llength $paths]!=1} {error "MAC cut/missing related functional $type scope: $source -> $target"}
        set end [get_property ENDPOINT_PIN [lindex $paths 0]]
        if {[lsearch -exact $ends $end]<0} {error "MAC related functional endpoint escaped scope"}
        timed related_${source}_to_${target}_$type $starts [list $end] 8.0 0 1
    }
    # Representative paths plus complete exception/clock-interaction review
    # are both required. One timed path is never proof that no other cut exists.
}

proc valence_mac::epoch {release_q} {
    variable root; variable facts
    set q $root/media/ingressResetSource_reg/Q
    ff $root/media/ingressResetSource_reg cpu 1 [dict get $release_q cpuRelease]
    set pin $root/physicalIngress/commonReset
    set driver [drivers [one get_pins $pin]]
    if {[llength $driver]!=1} {error "MAC epoch reset must have exactly one driver"}
    set lut [get_cells -of_objects [get_pins $driver]]
    if {[llength $lut]!=1 || [get_property REF_NAME $lut] ne "LUT2" ||
        [string tolower [get_property INIT $lut]] ni {4'he 0xe}} {error "MAC epoch reset requires reviewed two-input OR mapping"}
    set found 0
    foreach {a b} {I0 I1 I1 I0} {
        if {[drivers [get_pins $lut/$a]] eq [list $q]} {
            same_net $lut/$b $root/commonReset; set found 1
        }
    }
    if {!$found} {error "MAC epoch reset is not registered epoch Q OR direct cold reset"}
    set physical_pres {}
    foreach {path domain} {sourceRelease raw_rx destinationRelease raw_tx crossing/fifo/sourceRelease raw_rx crossing/fifo/destinationRelease raw_tx} {
        release $root/physicalIngress/$path $domain $pin
        foreach c [bank $root/physicalIngress/$path/release_0_reg 3] {lappend physical_pres $c/PRE}
    }
    set endpoints [names [all_fanout -flat -endpoints_only -from [get_pins $q]]]
    if {$endpoints ne [lsort $physical_pres]} {error "MAC epoch Q reaches unexpected/omits physical reset endpoints: $endpoints"}
    foreach path {txFifo/commonReset rxFifo/commonReset txStats/commonReset rxStats/commonReset rxDiagnostics/commonReset rawDiagnostics/commonReset txConfig/commonReset rxConfig/commonReset rxStop/commonReset} {
        same_net $root/commonReset $root/$path
    }
    puts $facts [list EPOCH_REGISTERED_OR_COLD $q ENDPOINTS=$endpoints]
}
proc valence_mac::mailbox {path width from to} {
    variable root; variable facts
    set h $root/$path
    set src [clock $h/sourceClock]; set dst [clock $h/destinationClock]
    variable clocks
    if {$src ne [dict get $clocks $from] || $dst ne [dict get $clocks $to]} {error "MAC mailbox source/destination clock role changed: $path"}
    same_net $root/commonReset $h/commonReset
    # Resolve clock domains from actual mailbox pins, not assumed direction.
    dict set clocks mailbox_source $src; dict set clocks mailbox_destination $dst
    set sr [release $h/sourceRelease mailbox_source $root/commonReset]
    set dr [release $h/destinationRelease mailbox_destination $root/commonReset]
    foreach {chain launch from to fr tr} [list requestSync requestToggle mailbox_source mailbox_destination $sr $dr ackSync ackToggle mailbox_destination mailbox_source $dr $sr] {
        set scope [level $h/$chain $h/${launch}_reg $from $to $fr $tr]
        timed $path/$chain [list [lindex $scope 0]] [list [lindex $scope 1]] 8.0
    }
    foreach reg {valid token} {ff $h/${reg}_reg mailbox_destination 0 $dr}
    set held [bank $h/held_reg $width]; set captured [bank $h/captured_reg $width]
    foreach reg [concat $held $captured] {
        if {[get_property IS_SEQUENTIAL [get_cells $reg]] ni {1 TRUE true 1'b1} || ![string match FD* [get_property REF_NAME [get_cells $reg]]]} {error "MAC held/captured bundle must be real FFs: $reg"}
    }
    foreach reg $held {if {[clock $reg/C] ne $src} {error "MAC held bundle source clock mismatch: $path"}}
    foreach reg $captured launch $held {
        if {[clock $reg/C] ne $dst} {error "MAC capture bundle destination clock mismatch: $path"}
        set input [drivers $reg/D]
        if {$input ne [list $launch/Q]} {error "MAC held bundle has unreviewed combinational/multiple/wrong-bit source: $reg"}
        puts $facts [list CAPTURE_ENABLE $reg [all_fanin -flat -startpoints_only -to [one get_pins $reg/CE]]]
    }
    timed $path/payload [pins $held C] [pins $captured D] 8.0 [expr {$width>1}]
}
proc valence_mac::fifo {path width payload_width from to} {
    variable root; variable clocks; variable facts
    set h $root/$path
    dict set clocks fifo_source [clock $h/sourceClock]; dict set clocks fifo_destination [clock $h/destinationClock]
    if {[dict get $clocks fifo_source] ne [dict get $clocks $from] || [dict get $clocks fifo_destination] ne [dict get $clocks $to]} {error "MAC FIFO source/destination clock role changed: $path"}
    set reset [expr {[string first physicalIngress/ $path]==0 ? "$root/physicalIngress/commonReset" : "$root/commonReset"}]
    same_net $h/commonReset $reset
    set sr [release $h/sourceRelease fifo_source $reset]; set dr [release $h/destinationRelease fifo_destination $reset]
    foreach {prefix from to fr tr} [list readGray fifo_destination fifo_source $dr $sr writeGray fifo_source fifo_destination $sr $dr] {
        set first [bank $h/${prefix}Sync_stage0_reg $width]; set second [bank $h/${prefix}Sync_reg $width]
        set starts {}; set sources {}
        foreach a $first b $second {
            ff $a $to 0 $tr 1; ff $b $to 0 $tr 1
            if {[drivers $b/D] ne [list $a/Q] || [loads $a/Q] ne [list $b/D]} {error "MAC Gray intermediate fanout: $a"}
            set driver [drivers $a/D]
            if {[llength $driver]!=1 || ![string match */Q [lindex $driver 0]]} {error "MAC Gray launch is not one Q: $a"}
            set c [get_property NAME [get_cells -of_objects [get_pins $driver]]]
            # Only the matching Gray bit, or equivalent binary MSB merging,
            # may launch a bit. Exact bit correspondence is mandatory.
            regexp {\[([0-9]+)\]$} $a ignored bit
            set allowed [list [format {%s/%s_reg[%d]} $h $prefix $bit]]
            if {$bit==$width-1} {lappend allowed [format {%s/%sBinary_reg[%d]} $h [string range $prefix 0 end-4] $bit]}
            if {[lsearch -exact $allowed $c]<0} {error "MAC Gray launch bit/source mismatch: $a <- $c"}
            ff $c $from 0 $fr; lappend starts $c/C; lappend sources $c
        }
        if {[llength [lsort -unique $sources]]!=$width} {error "MAC duplicate Gray source bits: $path/$prefix"}
        timed $path/$prefix $starts [pins $first D] 8.0 1
    }
    set payload [valence_fifo_payload::collect $h $payload_width]
    set path_count [valence_fifo_payload::check_paths $payload 8.0]
    set starts [dict get $payload starts]; set ends [dict get $payload ends]
    dict for {end launch} [dict get $payload by_end] {
        puts $facts [list FIFO_PAYLOAD_LEAVES $path TO=$end FROM=$launch]
    }
    dict for {end launch} [dict get $payload ordinary_by_end] {
        puts $facts [list FIFO_PAYLOAD_DESTINATION_FFS $path TO=$end FROM=$launch]
    }
    timed $path/payload $starts $ends 8.0 1
    puts $facts [list FIFO_PAYLOAD_PATHS $path CHECKED=$path_count EXCEPTION_AND_SKEW_REVIEW_REQUIRED=1]
    puts $facts [list FIFO $path POINTER_BITS=$width PAYLOAD_BITS=$payload_width]
}
