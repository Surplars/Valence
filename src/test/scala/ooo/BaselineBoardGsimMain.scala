package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.core.ooo.{
    BoardSocConfig, BoardSocTop, CacheTagConfig, CoherentCacheConcurrency, DdrBridgeConfig, FpgaStorageConfig
}

/** Functional bring-up fixture, deliberately independent of MatchingManagedBoard and its timing candidates.
  * Frozen scope: two-wide RV64IMAC, early issue, 40 MHz, 1 MiB local RAM, 128 KiB ROM,
  * 1.5 Mbaud virtual UART reference and firmware divisor one. No DDR, CMU or physical-board claim.
  * All additional observations are passive scalar ports; none changes the production datapath.
  */
class BaselineBoardGsim extends Module {
    private val expected = BoardSocConfig.boardParams(
        profile = "early-issue", width = 2, externalDdr = false, isa = "rv64imac",
        ddrMemoryBytes = BigInt(512) * 1024 * 1024,
        loadIssueForwarding = Some(false), fpgaStorage = FpgaStorageConfig.Registers)
    require(BoardSocConfig.romBase == BigInt("80000000", 16) && BoardSocConfig.romBytes == 131072)
    require(BoardSocConfig.ramBase == BigInt("80200000", 16) && BoardSocConfig.ramBytes == 1048576)
    require(BoardSocConfig.ramReadLatency == 3)
    require(expected.renameWidth == 2 && expected.commitWidth == 2 && expected.completionWidth == 2)
    require(expected.robEntries == 16 && expected.physicalRegs == 48 && expected.memoryEntries == 2)
    require(expected.registeredImsicInterrupts && expected.earlyRecoveryIssueBlock)
    require(expected.machineSystem && expected.atomicMemory && expected.compressedInstructions)

    private val board = Module(new BoardSocTop(
        vivadoMemories = false, simulation = true, socClockHz = 40000000,
        externalDdr = false, timingProfile = "early-issue", uartBaud = 1500000,
        dataCacheWays = 2, issueWidth = 2, instructionPrefetch = true, isaProfile = "rv64imac",
        peripheralClockHz = 0, ethernetControl = false, ethernetDma = false,
        clockManagementHz = 0, managedPeripherals = false,
        ddrMemoryBytes = BigInt(512) * 1024 * 1024, instructionLineCacheLines = 8,
        dataCacheLines = 32, ddrBridge = DdrBridgeConfig.Legacy,
        cacheConcurrency = CoherentCacheConcurrency(), loadIssueForwarding = Some(false),
        tagConfig = CacheTagConfig.FullWidth, fpgaStorage = FpgaStorageConfig.Registers))
    require(board.platform.core.core.core.p == expected, "functional baseline actual core configuration drifted")
    require(board.platform.ram.nonEmpty && board.io.ddrAxi.isEmpty && board.io.nativeGmac.isEmpty)

    val io = IO(new Bundle {
        val uartRx = Input(Bool())
        val uartTx = Output(Bool())
        val program = Input(chiselTypeOf(board.io.program.get))
        val commit0 = Output(chiselTypeOf(board.io.commit.get(0)))
        val commit1 = Output(chiselTypeOf(board.io.commit.get(1)))
        val trap = Output(chiselTypeOf(board.io.trap.get))
        val fetchPc = Output(UInt(64.W))
        val ramRequest = Output(Bool())
        val ramAddress = Output(UInt(64.W))
        val ramWrite = Output(Bool())
        val ramSize = Output(UInt(2.W))
        val ramMask = Output(UInt(8.W))
        val ramWriteData = Output(UInt(64.W))
        val ramResponse = Output(Bool())
        val ramReadData = Output(UInt(64.W))
        val ramError = Output(Bool())
    })
    board.io.uartRx := io.uartRx
    board.io.program.get := io.program
    // Downloaded application bytes must travel through UART and the real CPU/memory path.
    board.io.ramProgram.get := 0.U.asTypeOf(board.io.ramProgram.get)
    io.uartTx := board.io.uartTx
    io.commit0 := board.io.commit.get(0)
    io.commit1 := board.io.commit.get(1)
    io.trap := board.io.trap.get
    io.fetchPc := board.io.fetchPc.get
    private val ram = board.platform.ram.get.io.port
    io.ramRequest := BoringUtils.bore(ram.request.valid) && BoringUtils.bore(ram.request.ready)
    io.ramAddress := BoringUtils.bore(ram.request.bits.address)
    io.ramWrite := BoringUtils.bore(ram.request.bits.write)
    io.ramSize := BoringUtils.bore(ram.request.bits.size)
    io.ramMask := BoringUtils.bore(ram.request.bits.mask)
    io.ramWriteData := BoringUtils.bore(ram.request.bits.data)
    io.ramResponse := BoringUtils.bore(ram.response.valid) && BoringUtils.bore(ram.response.ready)
    io.ramReadData := BoringUtils.bore(ram.response.bits.data)
    io.ramError := BoringUtils.bore(ram.response.bits.error) || BoringUtils.bore(ram.response.bits.pageFault)
}

object BaselineBoardGsimMain extends App {
    require(args.length == 1, "usage: BaselineBoardGsimMain output-directory")
    val output = Paths.get(args(0))
    Files.createDirectories(output)
    ChiselStage.emitCHIRRTLFile(new BaselineBoardGsim, Array("--target-dir", output.toString))
}
