package ooo

import chisel3._
import chisel3.util.{Cat, MuxLookup}
import _root_.circt.stage.ChiselStage
import soc.core.ooo.{FetchPacketPermission, PacketFetchPmp, PmpChecker, PmpState}

class PmpCheckerGsim(alignedWord: Boolean = false, packet: Boolean = false, wordSpan: Boolean = false,
    balanced: Boolean = false, rawPrefix: Boolean = false, naturalAligned: Boolean = false,
    packetWidth: Int = 2) extends Module {
    require(packetWidth >= 1)
    val io = IO(new Bundle {
        val cfg0      = Input(UInt(8.W))
        val cfg1      = Input(UInt(8.W))
        val cfg2      = Input(UInt(8.W))
        val cfg3      = Input(UInt(8.W))
        val cfg4      = Input(UInt(8.W))
        val cfg5      = Input(UInt(8.W))
        val cfg6      = Input(UInt(8.W))
        val cfg7      = Input(UInt(8.W))
        val cfg8      = Input(UInt(8.W))
        val cfg9      = Input(UInt(8.W))
        val cfg10     = Input(UInt(8.W))
        val cfg11     = Input(UInt(8.W))
        val cfg12     = Input(UInt(8.W))
        val cfg13     = Input(UInt(8.W))
        val cfg14     = Input(UInt(8.W))
        val cfg15     = Input(UInt(8.W))
        val addr0     = Input(UInt(54.W))
        val addr1     = Input(UInt(54.W))
        val addr2     = Input(UInt(54.W))
        val addr3     = Input(UInt(54.W))
        val addr4     = Input(UInt(54.W))
        val addr5     = Input(UInt(54.W))
        val addr6     = Input(UInt(54.W))
        val addr7     = Input(UInt(54.W))
        val addr8     = Input(UInt(54.W))
        val addr9     = Input(UInt(54.W))
        val addr10    = Input(UInt(54.W))
        val addr11    = Input(UInt(54.W))
        val addr12    = Input(UInt(54.W))
        val addr13    = Input(UInt(54.W))
        val addr14    = Input(UInt(54.W))
        val addr15    = Input(UInt(54.W))
        val address   = Input(UInt(64.W))
        val size      = Input(UInt(3.W))
        val access    = Input(UInt(2.W))
        val privilege = Input(UInt(2.W))
        val denied    = Output(Bool())
        val checkedAddress = Output(UInt(64.W))
    })
    val state = WireDefault(0.U.asTypeOf(new PmpState))
    state.cfg(0) := io.cfg0
    state.cfg(1) := io.cfg1
    state.cfg(2) := io.cfg2
    state.cfg(3) := io.cfg3
    state.cfg(4) := io.cfg4
    state.cfg(5) := io.cfg5
    state.cfg(6) := io.cfg6
    state.cfg(7) := io.cfg7
    state.cfg(8) := io.cfg8
    state.cfg(9) := io.cfg9
    state.cfg(10) := io.cfg10
    state.cfg(11) := io.cfg11
    state.cfg(12) := io.cfg12
    state.cfg(13) := io.cfg13
    state.cfg(14) := io.cfg14
    state.cfg(15) := io.cfg15
    state.addr(0) := io.addr0
    state.addr(1) := io.addr1
    state.addr(2) := io.addr2
    state.addr(3) := io.addr3
    state.addr(4) := io.addr4
    state.addr(5) := io.addr5
    state.addr(6) := io.addr6
    state.addr(7) := io.addr7
    state.addr(8) := io.addr8
    state.addr(9) := io.addr9
    state.addr(10) := io.addr10
    state.addr(11) := io.addr11
    state.addr(12) := io.addr12
    state.addr(13) := io.addr13
    state.addr(14) := io.addr14
    state.addr(15) := io.addr15
    PmpState.decodeRegions(state)
    val checker = Module(new PmpChecker)
    checker.io.state     := state
    checker.io.address   := io.address
    checker.io.size      := io.size
    checker.io.access    := io.access
    checker.io.privilege := io.privilege
    io.checkedAddress := io.address
    if (naturalAligned) {
        // The unchanged independent byte-range oracle covers the entire input
        // space. Select the optimized implementation ONLY for its exact domain.
        val size = Mux(io.size <= 3.U, io.size, 3.U)
        val mask = MuxLookup(size, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
        val natural = Module(new PmpChecker(naturalAlignedAccess = true))
        natural.io.state := state
        natural.io.address := Cat(io.address(63, 3), io.address(2, 0) & ~mask)
        natural.io.size := size
        natural.io.access := io.access
        natural.io.privilege := io.privilege
        io.denied := Mux(io.size <= 3.U && (io.address(2, 0) & mask) === 0.U,
            natural.io.denied, checker.io.denied)
    } else if (rawPrefix) {
        val permission = Module(new FetchPacketPermission(16, 2, wordSpan, balanced))
        val offset = Mux(io.address(4), 4.U(3.W), Mux(io.address(3), 2.U(3.W), 0.U(3.W)))
        permission.io.base := io.address - offset
        permission.io.state := state
        permission.io.privilege := io.privilege
        permission.io.virtualized := false.B
        permission.io.instructionLow(0) := Mux(offset === 2.U, 0.U, 3.U)
        permission.io.instructionLow(1) := 3.U
        io.checkedAddress := Mux(offset === 0.U, permission.io.addresses(0), permission.io.addresses(1))
        io.denied := Mux(io.size === 2.U && io.access === 2.U,
            Mux(offset === 0.U, permission.io.denied(0), permission.io.denied(1)), checker.io.denied)
    } else if (packet) {
        val checks = Module(new PacketFetchPmp(16, packetWidth, wordSpan, balancedComparisons = balanced))
        // Exercise every lane offset against the existing independent byte-range
        // oracle. Address subtraction/addition wraps at XLEN before PMP checks.
        val position = io.address(7, 2) % (2 * packetWidth - 1).U
        val offset = position << 1
        checks.io.base := io.address - offset
        checks.io.state := state
        checks.io.privilege := io.privilege
        val denied = checks.io.denied(position)
        io.checkedAddress := checks.io.base + offset
        io.denied := Mux(io.size === 2.U && io.access === 2.U, denied, checker.io.denied)
    } else if (alignedWord) {
        val word = Module(new PmpChecker(alignedWordAccess = true))
        word.io.state := state
        word.io.address := Cat(io.address(63, 2), 0.U(2.W))
        word.io.size := 2.U
        word.io.access := io.access
        word.io.privilege := io.privilege
        io.denied := Mux(io.size === 2.U && io.address(1, 0) === 0.U, word.io.denied, checker.io.denied)
    } else io.denied := checker.io.denied
}

object PmpCheckerGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PmpCheckerGsim(args.drop(1).contains("aligned-word"),
        args.contains("packet"), args.contains("word-span"), args.contains("balanced"), args.contains("raw-prefix"),
        args.contains("natural-aligned"),
        args.find(_.startsWith("width=")).map(_.stripPrefix("width=").toInt).getOrElse(2)),
        Array("--target-dir", args.head))
}
