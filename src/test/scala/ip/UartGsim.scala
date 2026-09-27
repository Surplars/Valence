package ip

import _root_.circt.stage.ChiselStage
import soc.ip.uart.UartConsole

object UartGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new UartConsole(), Array("--target-dir", args.head))
}
