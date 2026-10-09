package ooo

import chisel3._
import soc.core.ooo._
import _root_.circt.stage.ChiselStage

class NextLineAuthorizationGsim(storePrefetch: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val request = Input(new DataRequest)
        val privilege = Input(UInt(2.W))
        val cfg0 = Input(UInt(8.W))
        val pmpAddress0 = Input(UInt(54.W))
        val cfg1 = Input(UInt(8.W))
        val pmpAddress1 = Input(UInt(54.W))
        val cfg2 = Input(UInt(8.W))
        val pmpAddress2 = Input(UInt(54.W))
        val cfg3 = Input(UInt(8.W))
        val pmpAddress3 = Input(UInt(54.W))
        val cfg4 = Input(UInt(8.W))
        val pmpAddress4 = Input(UInt(54.W))
        val cfg5 = Input(UInt(8.W))
        val pmpAddress5 = Input(UInt(54.W))
        val cfg6 = Input(UInt(8.W))
        val pmpAddress6 = Input(UInt(54.W))
        val cfg7 = Input(UInt(8.W))
        val pmpAddress7 = Input(UInt(54.W))
        val cfg8 = Input(UInt(8.W))
        val pmpAddress8 = Input(UInt(54.W))
        val cfg9 = Input(UInt(8.W))
        val pmpAddress9 = Input(UInt(54.W))
        val cfg10 = Input(UInt(8.W))
        val pmpAddress10 = Input(UInt(54.W))
        val cfg11 = Input(UInt(8.W))
        val pmpAddress11 = Input(UInt(54.W))
        val cfg12 = Input(UInt(8.W))
        val pmpAddress12 = Input(UInt(54.W))
        val cfg13 = Input(UInt(8.W))
        val pmpAddress13 = Input(UInt(54.W))
        val cfg14 = Input(UInt(8.W))
        val pmpAddress14 = Input(UInt(54.W))
        val cfg15 = Input(UInt(8.W))
        val pmpAddress15 = Input(UInt(54.W))
        val fault = Input(Bool())
        val allowed = Output(Bool())
        val topAllowed = Output(Bool())
        val address = Output(UInt(64.W))
    })
    val state = Wire(new PmpState)
    state.cfg(0) := io.cfg0
    state.addr(0) := io.pmpAddress0
    state.cfg(1) := io.cfg1
    state.addr(1) := io.pmpAddress1
    state.cfg(2) := io.cfg2
    state.addr(2) := io.pmpAddress2
    state.cfg(3) := io.cfg3
    state.addr(3) := io.pmpAddress3
    state.cfg(4) := io.cfg4
    state.addr(4) := io.pmpAddress4
    state.cfg(5) := io.cfg5
    state.addr(5) := io.pmpAddress5
    state.cfg(6) := io.cfg6
    state.addr(6) := io.pmpAddress6
    state.cfg(7) := io.cfg7
    state.addr(7) := io.pmpAddress7
    state.cfg(8) := io.cfg8
    state.addr(8) := io.pmpAddress8
    state.cfg(9) := io.cfg9
    state.addr(9) := io.pmpAddress9
    state.cfg(10) := io.cfg10
    state.addr(10) := io.pmpAddress10
    state.cfg(11) := io.cfg11
    state.addr(11) := io.pmpAddress11
    state.cfg(12) := io.cfg12
    state.addr(12) := io.pmpAddress12
    state.cfg(13) := io.cfg13
    state.addr(13) := io.pmpAddress13
    state.cfg(14) := io.cfg14
    state.addr(14) := io.pmpAddress14
    state.cfg(15) := io.cfg15
    state.addr(15) := io.pmpAddress15
    PmpState.decodeRegions(state)
    val p = OooParams(machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 131072,
        dataNextLinePrefetch = true, dataStoreNextLinePrefetch = storePrefetch)
    val normal = Module(new NextLineAuthorization(p))
    val top = Module(new NextLineAuthorization(p.copy(speculativeRamBase = (BigInt(1) << 64) - 8192,
        speculativeRamBytes = 8192)))
    Seq(normal, top).foreach { m =>
        m.io.request := io.request
        m.io.privilege := io.privilege
        m.io.pmpState := state
        m.io.fault := io.fault
    }
    io.allowed := normal.io.allowed
    io.topAllowed := top.io.allowed
    io.address := normal.io.address
}
object NextLineAuthorizationGsimMain extends App {
    require(args.lift(1).forall(Set("0", "1").contains))
    ChiselStage.emitCHIRRTLFile(new NextLineAuthorizationGsim(args.lift(1).contains("1")), Array("--target-dir", args.head))
}
