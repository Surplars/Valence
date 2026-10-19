package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder.I1AddressWindow

class I1AddressWindowFixture(width: Int) extends Module {
    require(Set(32, 64).contains(width))
    val end = BigInt(1) << width
    val windows = Seq(
        BigInt(0) -> BigInt(0), BigInt(0) -> BigInt(4096),
        BigInt("80010000", 16) -> BigInt(65536), BigInt(1234) -> BigInt(65537),
        (end - 4096) -> BigInt(4096), BigInt(0) -> end,
        BigInt("2345", 16) -> BigInt(1),
        BigInt("80200000", 16) -> (if (width == 64) BigInt(1) << 31 else BigInt("7fe00000", 16)),
        (if (width == 64) BigInt("fffffffd", 16) else end - 7) -> BigInt(7),
        BigInt("10000007", 16) -> BigInt(33), BigInt(4095) -> BigInt(2),
        BigInt("ff00", 16) -> BigInt("abcdef", 16))
    val io = IO(new Bundle { val address = Input(UInt(width.W)); val hits = Output(UInt(windows.size.W)) })
    io.hits := Cat(windows.reverse.map { case (base, bytes) => I1AddressWindow.contains(io.address, base, bytes) })
}
object I1AddressWindowMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1AddressWindowFixture(args(1).toInt), Array("--target-dir", args.head))
}
