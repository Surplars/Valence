package ip

import _root_.circt.stage.ChiselStage
import soc.ip.uart.UartConsole

object UartGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new UartConsole(), Array("--target-dir", args.head))
}

object BoardFastUartGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new UartConsole(clockHz = 40000000, fastDivisorOne = true),
        Array("--target-dir", args.head))
}
