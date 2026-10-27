FIRRTL version 3.3.0
circuit InitByteSpan :
  module InitByteSpan :
    input clock : Clock
    input index : UInt<6>
    input data : UInt<2>
    input write : UInt<1>
    output value : UInt<2>
    cmem tailRam : UInt<2>[64]
    read mport rd = tailRam[index], clock
    connect value, rd
    when write :
      write mport wr = tailRam[index], clock
      connect wr, data
