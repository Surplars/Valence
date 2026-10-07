# xsim-only read-only eye observation; no passing receipt or hardware claims.
run 600 ns
set previous ""
for {set sample 0} {$sample<360} {incr sample} {
    set state {}
    foreach signal {rx_pad_clock rx_clock rxd dut/delayed_rx rx_data rx_valid} {
        lappend state [get_value -radix bin /native_rgmii_tb/$signal]
    }
    if {$state ne $previous} {puts "RX_EYE_TRACE [current_time] $state"; set previous $state}
    run 250 ps
}
quit
