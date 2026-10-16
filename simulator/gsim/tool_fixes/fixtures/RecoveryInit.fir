FIRRTL version 3.3.0
circuit RecoveryInit :
  module RecoveryInit :
    input clock : Clock
    input narrow : UInt<8>
    input stateBegin : UInt<3>
    input stateEnd : UInt<3>
    input stateBytes : UInt<3>
    input wide : UInt<129>
    output low : UInt<3>
    output a : UInt<3>
    output b : UInt<3>
    output c : UInt<3>
    output saved : UInt<129>
    reg hold : UInt<129>, clock
    connect hold, wide
    connect saved, hold
    connect low, bits(narrow, 2, 0)
    connect a, stateBegin
    connect b, stateEnd
    connect c, stateBytes
