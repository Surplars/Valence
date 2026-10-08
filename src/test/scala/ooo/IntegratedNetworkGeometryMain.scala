package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.BoardSocTop

/** Exact managed network candidate geometry, CHIRRTL evidence only. */
object IntegratedNetworkGeometryMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new BoardSocTop(
        socClockHz = 100000000, externalDdr = true,
        timingProfile = "staged-fetch-turnover", uartBaud = 460800,
        isaProfile = "rv64gc", issueWidth = 2,
        peripheralClockHz = 50000000, clockManagementHz = 50000000,
        ddrUiClockHz = 250000000, ethernetControl = true, ethernetDma = true,
        managedPeripherals = true, ddrMemoryBytes = BigInt(2147483648L),
        instructionLineCacheLines = 512, dataCacheLines = 512),
        Array("--target-dir", args.head))
}
