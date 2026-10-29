FIRRTL version 3.3.0
circuit AsyncResetGroups :
  module AsyncResetGroups :
    input clock : Clock
    input arst : AsyncReset
    input brst : AsyncReset
    input srst : UInt<1>
    input aEnable : UInt<1>
    input bEnable : UInt<1>
    input plainEnable : UInt<1>
    input localHold : UInt<1>
    input data : UInt<8>
    output directA : UInt<8>
    output directB : UInt<8>
    output sharedSync : UInt<8>
    output syncOnly : UInt<8>
    output plain : UInt<8>
    output derivedA : UInt<8>
    output derivedB : UInt<8>
    output registerReset : UInt<8>
    output releaseBits : UInt<3>
    output resetConsumer0 : UInt<1>
    output resetConsumer1 : UInt<1>
    node aUInt = asUInt(arst)
    regreset a : UInt<8>, clock, arst, UInt<8>(17)
    regreset b : UInt<8>, clock, brst, UInt<8>(34)
    regreset shared : UInt<8>, clock, aUInt, UInt<8>(51)
    regreset sync : UInt<8>, clock, srst, UInt<8>(68)
    reg unreset : UInt<8>, clock
    regreset release : UInt<3>, clock, arst, UInt<3>(7)
    regreset local : UInt<1>, clock, arst, UInt<1>(1)
    node derived = asAsyncReset(bits(release, 2, 2))
    node registerDerived = asAsyncReset(local)
    regreset da : UInt<8>, clock, derived, UInt<8>(85)
    regreset db : UInt<8>, clock, derived, UInt<8>(102)
    regreset dr : UInt<8>, clock, registerDerived, UInt<8>(119)
    connect a, mux(aEnable, data, a)
    connect b, mux(bEnable, data, b)
    connect shared, mux(aEnable, data, shared)
    connect sync, mux(aEnable, data, sync)
    connect unreset, mux(plainEnable, data, unreset)
    connect release, cat(bits(release, 1, 0), UInt<1>(0))
    connect local, localHold
    connect da, mux(aEnable, data, da)
    connect db, mux(aEnable, data, db)
    connect dr, mux(aEnable, data, dr)
    connect directA, a
    connect directB, b
    connect sharedSync, shared
    connect syncOnly, sync
    connect plain, unreset
    connect derivedA, da
    connect derivedB, db
    connect registerReset, dr
    connect releaseBits, release
    connect resetConsumer0, xor(asUInt(derived), aEnable)
    connect resetConsumer1, and(asUInt(derived), bEnable)
