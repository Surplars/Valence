FIRRTL version 3.3.0
circuit RecoveryVec :
  module RecoveryVec :
    input index : UInt<2>
    input values : UInt<8>[3]
    input matrix : UInt<8>[3][3]
    output selected : UInt<8>
    output selectedMatrix : UInt<8>
    output copied : UInt<8>[3]
    output copiedMatrix : UInt<8>[3][3]
    output constants : UInt<8>[3][3]
    connect selected, values[index]
    connect selectedMatrix, matrix[index][index]
    connect copied, values
    connect copiedMatrix, matrix
    connect constants[0][0], UInt<8>(42)
    connect constants[0][1], UInt<8>(42)
    connect constants[0][2], UInt<8>(42)
    connect constants[1][0], UInt<8>(42)
    connect constants[1][1], UInt<8>(42)
    connect constants[1][2], UInt<8>(42)
    connect constants[2][0], UInt<8>(42)
    connect constants[2][1], UInt<8>(42)
    connect constants[2][2], UInt<8>(42)
