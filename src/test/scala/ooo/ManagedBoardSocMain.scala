package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.BoardSocTop

/** Opt-in native GMII/CMU/UART board candidate. Requires an external RGMII
  * adapter, fixed raw clocks and common reset; not a replacement old bit top.
  */
object ManagedBoardSocMain extends App {
    require(args.nonEmpty && args.length <= 9,
        "usage: ManagedBoardSocMain output [cpu-hz] [profile] [baud] [isa] [aon-hz] [uart-hz] [ddr-ui-hz] [ddr-bytes]")
    ChiselStage.emitSystemVerilogFile(new BoardSocTop(
        socClockHz = args.lift(1).map(_.toInt).getOrElse(100000000),
        externalDdr = true,
        timingProfile = args.lift(2).getOrElse("staged-fetch-feedback"),
        uartBaud = args.lift(3).map(_.toInt).getOrElse(460800),
        isaProfile = args.lift(4).getOrElse("rv64imac"),
        issueWidth = 2,
        peripheralClockHz = args.lift(6).map(_.toInt).getOrElse(50000000),
        clockManagementHz = args.lift(5).map(_.toInt).getOrElse(50000000),
        ddrUiClockHz = args.lift(7).map(_.toInt).getOrElse(250000000),
        ethernetControl = true, ethernetDma = true, managedPeripherals = true,
        ddrMemoryBytes = args.lift(8).map(BigInt(_)).getOrElse(soc.core.ooo.BoardSocConfig.ddrBytes)),
        Array("--target-dir", args.head),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
}
