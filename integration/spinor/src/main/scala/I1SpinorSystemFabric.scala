package soc.integration.spinor

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.core.inorder._
import soc.ip.axi.Axi4MemoryPort
import soc.ip.bus.RegisterPort
import soc.ip.tilelink.{RegisteredTileLinkBoundary, TwoMasterTileLinkArbiter}
import soc.ip.uart.UartConsole

/** Always-on system fabric: two independent I/D owners, real AXI responses,
  * and the existing UART/timer/PLIC/CMU address map. Native cache adapters and
  * CPU/fabric CDC live in the CPU assembly, before these local TL ports.
  */
class I1SpinorSystemFabric(p: FiveStageSocConfig) extends Module {
    require(p.managedPeripherals && !p.withNetwork && !p.withBootRom && !p.withJtagLoader)
    require(!p.core.coherentCaches && p.core.fpgaTimingCuts && p.ddrSlots == 2)
    val clientParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 1, sizeBits = 3)
    val io = IO(new Bundle {
        val clients = Vec(2, Flipped(new TLBundle(clientParams)))
        val axi = new Axi4MemoryPort(32, 4)
        val cmu = new RegisterPort
        val cmuIrq = Input(Bool())
        val uartRx = Input(Bool()); val uartTx = Output(Bool())
        val externalIrq = Input(Bool()); val memoryReady = Input(Bool())
        val time = Output(UInt(64.W))
        val machineIrq = Output(Bool()); val supervisorIrq = Output(Bool())
        val timerIrq = Output(Bool()); val softwareIrq = Output(Bool())
        val idle = Output(Bool())
    })
    val routes = (0 until 2).map(i => Module(new FiveStageTileLinkRoute(clientParams,
        p.ddrBase, p.ddrBytes, allowRegisters = i == 1, registeredAdmission = true)))
    val arbiter = Module(new TwoMasterTileLinkArbiter(clientParams))
    for (i <- 0 until 2) {
        routes(i).io.host <> io.clients(i)
        arbiter.io.masters(i) <> routes(i).io.memory
    }
    routes.head.io.registers.request.ready := false.B
    routes.head.io.registers.response.valid := false.B
    routes.head.io.registers.response.bits := 0.U.asTypeOf(routes.head.io.registers.response.bits)
    val cut = Module(new RegisteredTileLinkBoundary(arbiter.managerParams))
    cut.io.upstream <> arbiter.io.manager
    val maxBeats = math.max(8, p.core.cacheLineBytes / 8)
    val bridge = Module(new I1TileLinkAxi4OutstandingBridge(arbiter.managerParams, 32, 4,
        maxBeats, 0, 0, 0, p.ddrBase, p.ddrBytes, 2, maxOutstandingWrites = 1,
        unorderedResponses = true, parallelAdmission = true))
    bridge.io.tl <> cut.io.downstream
    io.axi <> bridge.io.axi

    val peripherals = Module(new FiveStagePeripherals(p))
    peripherals.io.registers <> routes(1).io.registers
    peripherals.io.cmuControl.get <> io.cmu
    peripherals.io.cmuIrq.get := io.cmuIrq
    peripherals.io.externalIrq := io.externalIrq
    peripherals.io.ddrReady := io.memoryReady
    peripherals.io.resetFault := false.B
    peripherals.io.loaderControl.request.ready := false.B
    peripherals.io.loaderControl.response.valid := false.B
    peripherals.io.loaderControl.response.bits := 0.U.asTypeOf(peripherals.io.loaderControl.response.bits)
    val uart = Module(new UartConsole(clockHz = p.clockHz, referenceClockHz = p.uartBaud * 16))
    uart.io.mmio <> peripherals.io.externalUart.get
    uart.io.rx := io.uartRx
    peripherals.io.uartRx := io.uartRx
    peripherals.io.externalUartIrq.get := uart.io.irq
    io.uartTx := uart.io.tx
    io.time := peripherals.io.time
    io.machineIrq := peripherals.io.machineExternalIrq
    io.supervisorIrq := peripherals.io.supervisorExternalIrq
    io.timerIrq := peripherals.io.timerIrq
    io.softwareIrq := peripherals.io.softwareIrq

    // Count ownership from accepted A through the FINAL D beat, including
    // MMIO and denied bursts. Empty transport alone cannot prove AXI completion.
    val owned = RegInit(VecInit(Seq.fill(2)(false.B)))
    val remaining = Reg(Vec(2, UInt(TLBurst.beats(0.U(clientParams.sizeBits.W), clientParams).getWidth.W)))
    for (i <- 0 until 2) {
        val client = io.clients(i)
        when(client.a.fire) {
            assert(!owned(i), "native I/D client accepted a second live owner")
            owned(i) := true.B
            remaining(i) := Mux(client.a.bits.opcode === TLOpcode.Get,
                TLBurst.beats(client.a.bits.size, clientParams), 1.U)
        }
        when(client.d.fire) {
            assert(owned(i), "fabric D beat has no accepted I/D owner")
            remaining(i) := remaining(i) - 1.U
            when(remaining(i) === 1.U) { owned(i) := false.B }
        }
    }
    io.idle := !owned.asUInt.orR && !io.clients.map(_.a.valid).reduce(_ || _)
}
