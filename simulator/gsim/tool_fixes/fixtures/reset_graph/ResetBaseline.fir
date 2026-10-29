FIRRTL version 3.3.0
circuit ResetBaseline :
  module ResetBaseline :
    input clock : Clock
    input reset : UInt<1>
    input enable : UInt<1>
    input data : UInt<8>
    output synchronous : UInt<8>
    output unreset : UInt<8>
    regreset sync : UInt<8>, clock, reset, UInt<8>(90)
    reg plain : UInt<8>, clock
    connect sync, mux(enable, data, sync)
    connect plain, mux(enable, data, plain)
    connect synchronous, sync
    connect unreset, plain
