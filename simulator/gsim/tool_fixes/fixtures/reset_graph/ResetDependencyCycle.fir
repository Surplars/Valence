FIRRTL version 3.3.0
circuit ResetDependencyCycle :
  module ResetDependencyCycle :
    input clock : Clock
    output value : UInt<1>
    wire resetA : AsyncReset
    wire resetB : AsyncReset
    regreset a : UInt<1>, clock, resetA, UInt<1>(0)
    regreset b : UInt<1>, clock, resetB, UInt<1>(0)
    connect resetA, asAsyncReset(b)
    connect resetB, asAsyncReset(a)
    connect a, UInt<1>(1)
    connect b, UInt<1>(1)
    connect value, a
