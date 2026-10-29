FIRRTL version 3.3.0
circuit ResetValueFeedback :
  module ResetValueFeedback :
    input clock : Clock
    input reset : AsyncReset
    output value : UInt<8>
    regreset q : UInt<8>, clock, reset, bits(add(q, UInt<8>(1)), 7, 0)
    connect q, q
    connect value, q
