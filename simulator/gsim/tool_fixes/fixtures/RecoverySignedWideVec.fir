FIRRTL version 3.3.0
circuit RecoverySignedWideVec :
  module RecoverySignedWideVec :
    input index : UInt<2>
    input signedValues : SInt<9>[3]
    input wideValues : UInt<129>[3]
    output signedSelected : SInt<9>
    output wideSelected : UInt<129>
    output signedCopied : SInt<9>[3]
    output wideCopied : UInt<129>[3]
    output signedConstants : SInt<9>[3]
    connect signedSelected, signedValues[index]
    connect wideSelected, wideValues[index]
    connect signedCopied, signedValues
    connect wideCopied, wideValues
    connect signedConstants[0], SInt<9>(-3)
    connect signedConstants[1], SInt<9>(-3)
    connect signedConstants[2], SInt<9>(-3)
