package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo.{BoardSocConfig, BoardSocTop}

/** Avoid exposing a Vec at the GSIM top boundary (the pinned generator needs scalar accessors). */
class BoardSocGsim(externalDdr: Boolean = false, clockHz: Int = 40000000,
    timingProfile: String = BoardSocConfig.timingProfile, uartBaud: Int = 1500000,
    dataCacheWays: Int = BoardSocConfig.dataCacheWays,
    issueWidth: Int = BoardSocConfig.issueWidth, instructionPrefetch: Boolean = true,
    isaProfile: String = BoardSocConfig.isaProfile) extends Module {
    private val board = Module(new BoardSocTop(vivadoMemories = false, simulation = true,
        externalDdr = externalDdr, socClockHz = clockHz, timingProfile = timingProfile, uartBaud = uartBaud,
        dataCacheWays = dataCacheWays, issueWidth = issueWidth, instructionPrefetch = instructionPrefetch,
        isaProfile = isaProfile))
    val io = IO(new Bundle {
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val program = Input(chiselTypeOf(board.io.program.get))
        val ramProgram = Input(new Bundle {
            val write = Bool()
            val index = UInt(17.W)
            val data = UInt(64.W)
        })
        val ddrReady = Input(Bool())
        val ddrAxi = if (externalDdr) Some(new soc.ip.axi.Axi4MemoryPort(32, 4)) else None
        val trap = Output(chiselTypeOf(board.io.trap.get))
        val commit0 = Output(Bool())
        val commit0Pc = Output(UInt(64.W))
        val commit1 = Output(Bool())
        val commit1Pc = Output(UInt(64.W))
        val fetchPc = Output(UInt(64.W))
        val cacheProfile = Output(new soc.core.ooo.CoherentCacheProfile)
        val headProfile = Output(new soc.core.ooo.HeadProfile)
    })
    board.io.uartRx := io.uartRx
    board.io.program.get := io.program
    board.io.ramProgram.foreach(_ := io.ramProgram)
    if (externalDdr) {
        board.io.ddrReady.get := io.ddrReady
        io.ddrAxi.get <> board.io.ddrAxi.get
    }
    io.uartTx := board.io.uartTx
    io.trap := board.io.trap.get
    io.commit0 := board.io.commit.get(0).valid
    io.commit0Pc := board.io.commit.get(0).bits.pc
    io.commit1 := board.io.commit.get(1).valid
    io.commit1Pc := board.io.commit.get(1).bits.pc
    io.fetchPc := board.io.fetchPc.get
    io.cacheProfile := board.io.cacheProfile.get
    io.headProfile := board.io.headProfile.get
}

/** Same memory sizes, address map, latency and compact core as the FPGA board. */
object BoardSocGsimMain extends App {
    require(args.length >= 1 && args.length <= 9,
        "usage: BoardSocGsimMain output-directory [ddr] [clock-hz] " +
            "[baseline|early-issue|queued-memory|registered-response|registered-replay|staged-fabric|staged-control] " +
            "[uart-baud] [cache-ways] " +
            "[issue-width:2|4] [instruction-prefetch:0|1] [isa:rv64imac|rv64imafc|rv64gc]")
    require(args.lift(7).forall(Set("0", "1").contains), "instruction-prefetch must be 0 or 1")
    val output = Paths.get(args.head)
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new BoardSocGsim(args.lift(1).contains("ddr"),
        args.lift(2).map(_.toInt).getOrElse(40000000),
        args.lift(3).getOrElse(BoardSocConfig.timingProfile),
        args.lift(4).map(_.toInt).getOrElse(1500000),
        args.lift(5).map(_.toInt).getOrElse(BoardSocConfig.dataCacheWays),
        args.lift(6).map(_.toInt).getOrElse(BoardSocConfig.issueWidth),
        !args.lift(7).contains("0"),
        args.lift(8).getOrElse(BoardSocConfig.isaProfile)),
        Array("--target-dir", output.toString))
}
