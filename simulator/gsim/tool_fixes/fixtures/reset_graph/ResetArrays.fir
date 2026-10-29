FIRRTL version 3.3.0
circuit ResetArrays :
  module ResetArrays :
    input clock : Clock
    input reset : AsyncReset
    input enable : UInt<1>
    input index : UInt<2>
    input data : UInt<8>
    output value : UInt<8>
    wire initial : UInt<8>[3]
    connect initial[0], UInt<8>(17)
    connect initial[1], UInt<8>(34)
    connect initial[2], UInt<8>(51)
    regreset cells : UInt<8>[3], clock, reset, initial
    when enable :
      connect cells[index], data
    connect value, cells[index]
