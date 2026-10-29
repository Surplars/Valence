FIRRTL version 3.3.0
circuit ResetPhases :
  module ResetPhases :
    input clock : Clock
    input root : AsyncReset
    input nextControl : UInt<1>
    input enable : UInt<1>
    input data : UInt<8>
    output control : UInt<1>
    output synchronous : UInt<8>
    output asynchronous : UInt<8>
    output syncLogic : UInt<8>
    output asyncLogic : UInt<8>
    regreset sampled : UInt<1>, clock, root, UInt<1>(0)
    regreset sync : UInt<8>, clock, sampled, UInt<8>(202)
    regreset async : UInt<8>, clock, asAsyncReset(sampled), UInt<8>(101)
    connect sampled, nextControl
    connect sync, mux(enable, data, sync)
    connect async, mux(enable, data, async)
    connect control, sampled
    connect synchronous, sync
    connect asynchronous, async
    connect syncLogic, xor(sync, UInt<8>(90))
    connect asyncLogic, xor(async, UInt<8>(90))
