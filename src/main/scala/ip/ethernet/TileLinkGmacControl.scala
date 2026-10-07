package soc.ip.ethernet

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** Native TL-UL CSR manager, not a wrapper around AXI Ethernet registers.
  * 4 ordered, non-flow reply credits; at most one request accepted per cycle,
  * response visible on the next cycle and stable until D.ready. Each port owns
  * a 4KiB window. Get/PutFull/PutPartial sizes 0..3 only; byte lanes are normal
  * TL 64-bit beat lanes. No TL-C, atomic, burst, PHY or MAC frame engine here.
  * Configuration changes while a frame is active are rejected atomically.
  */
class TileLinkGmacControl(config: GmacParams = GmacParams(),
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)) extends Module {
    require(params.addrWidth == 64 && params.dataWidth == 64 && params.sizeBits >= 2 && params.sizeBits <= 3)
    require(params.sourceBits >= 1)
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(params))
        val ports = Vec(config.ports.size, new GmacPortControl(config.aggregateStats, config.rxAdmissionStop))
        val irq = Output(UInt(config.ports.size.W))
    })
    io.tl.b.valid := false.B
    io.tl.b.bits := 0.U.asTypeOf(io.tl.b.bits)
    io.tl.c.ready := false.B
    io.tl.e.ready := false.B
    val replies = Module(new Queue(new TLBundleD(params), 4, pipe = false, flow = false))
    io.tl.d <> replies.io.deq
    val a = io.tl.a.bits
    val offset = a.address(11, 0) & "hff8".U
    val read = a.opcode === TLOpcode.Get
    val put = a.opcode === TLOpcode.PutFullData || a.opcode === TLOpcode.PutPartialData
    val accessMask = MuxLookup(a.size, 0.U(8.W))((0 to 3).map { n =>
        n.U -> ((((BigInt(1) << (1 << n)) - 1).U(8.W) << a.address(2, 0))(7, 0))
    })
    val aligned = MuxLookup(a.size, false.B)((0 to 3).map { n =>
        n.U -> ((a.address & ((BigInt(1) << n) - 1).U(64.W)) === 0.U)
    })
    val maskLegal = Mux(a.opcode === TLOpcode.PutPartialData,
        (a.mask & ~accessMask) === 0.U, a.mask === accessMask)
    val protocolLegal = (read || put) && a.size <= 3.U && aligned && maskLegal &&
        a.param === 0.U && !a.corrupt
    val mask = Cat((0 until 8).reverse.map(n => Fill(8, a.mask(n))))
    val maskedData = a.data & mask
    val knownOffsets = Seq(0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38,
        0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x70, 0x78, 0x80, 0x88) ++
        (if (config.rxAdmissionStop) Seq(0x90) else Seq.empty)
    val known = knownOffsets.map(n => offset === n.U).reduce(_ || _)
    val writeOffsets = Seq(0x10, 0x18, 0x30, 0x38, 0x70, 0x78) ++
        (if (config.rxAdmissionStop) Seq(0x90) else Seq.empty)
    val writable = writeOffsets.map(n => offset === n.U).reduce(_ || _)
    val allowedBits = MuxLookup(offset, 0.U(64.W))(Seq(
        0x10.U -> 15.U(64.W), 0x18.U -> ((BigInt(1) << 48) - 1).U(64.W),
        0x30.U -> 127.U(64.W), 0x38.U -> 127.U(64.W),
        0x70.U -> 1.U(64.W), 0x78.U -> ((BigInt(1) << 28) - 1).U(64.W),
        0x90.U -> 1.U(64.W)))
    val reservedLegal = (maskedData & ~allowedBits) === 0.U
    val selected = Wire(Vec(config.ports.size, Bool()))
    val portLegal = Wire(Vec(config.ports.size, Bool()))
    val portReady = Wire(Vec(config.ports.size, Bool()))
    val readValues = Wire(Vec(config.ports.size, UInt(64.W)))
    val irqs = Wire(Vec(config.ports.size, Bool()))
    for (n <- config.ports.indices) {
        val port = io.ports(n)
        selected(n) := a.address >= (config.base + n * 4096).U &&
            a.address < (config.base + (n + 1) * 4096).U(65.W)
        val control = RegInit(8.U(64.W))
        val macAddress = RegInit(0.U(64.W))
        val pending = RegInit(0.U(7.W))
        val irqEnable = RegInit(0.U(64.W))
        val mdioResult = RegInit(0.U(17.W))
        val mdioDone = RegInit(false.B)
        val mdio = Module(new MdioClause22(config.controlClockHz, config.mdcHz))
        val rxStopRequest = if (config.rxAdmissionStop) Some(RegInit(false.B)) else None
        val configuration = offset === 0x10.U || offset === 0x18.U
        val mdioStart = put && offset === 0x78.U && maskedData(17)
        // MDIO launch is a complete command, not a partial descriptor rewrite.
        val rxStopWrite = config.rxAdmissionStop.B && put && offset === 0x90.U
        val commandLegal = (!mdioStart && !rxStopWrite) || (a.size === 3.U && a.mask === 255.U)
        portLegal(n) := selected(n) && protocolLegal && known &&
            (!put || (writable && reservedLegal && commandLegal &&
                !(configuration && a.mask.orR && (port.txBusy || port.rxBusy))))
        portReady(n) := !mdioStart || mdio.io.command.ready
        val accepted = io.tl.a.fire && portLegal(n) && put
        val ack = Mux(accepted && offset === 0x30.U, maskedData(6, 0), 0.U(7.W))
        val events = Cat(mdio.io.response.fire, port.events)
        pending := (pending & ~ack) | events
        irqs(n) := (pending & irqEnable(6, 0)).orR
        mdio.io.command.valid := accepted && mdioStart
        mdio.io.command.bits.data := a.data(15, 0)
        mdio.io.command.bits.write := a.data(16)
        mdio.io.command.bits.phy := a.data(22, 18)
        mdio.io.command.bits.register := a.data(27, 23)
        mdio.io.response.ready := true.B
        when(mdio.io.command.fire) { mdioDone := false.B }
        when(mdio.io.response.fire) {
            mdioDone := true.B
            mdioResult := Cat(mdio.io.response.bits.noAck, mdio.io.response.bits.data)
        }
        port.mdc := mdio.io.mdc
        port.mdioOut := mdio.io.mdioOut
        port.mdioOe := mdio.io.mdioOe
        mdio.io.mdioIn := port.mdioIn
        port.txEnable := control(0)
        port.rxEnable := control(1)
        port.promiscuous := control(2)
        port.broadcastEnable := control(3)
        port.macAddress := macAddress(47, 0)
        port.rxStopRequest.foreach(_ := rxStopRequest.get)
        when(accepted) {
            when(offset === 0x10.U) { control := (control & ~mask) | maskedData }
            when(offset === 0x18.U) { macAddress := (macAddress & ~mask) | maskedData }
            when(offset === 0x38.U) { irqEnable := (irqEnable & ~mask) | maskedData }
            rxStopRequest.foreach { requested =>
                when(offset === 0x90.U) { requested := maskedData(0) }
            }
        }
        val clear = accepted && offset === 0x70.U && maskedData(0)
        val txFrames = RegInit(0.U(64.W))
        val rxFrames = RegInit(0.U(64.W))
        val rxDrops = RegInit(0.U(64.W))
        val rxBadFcs = RegInit(0.U(64.W))
        val txBytes = RegInit(0.U(64.W))
        val rxBytes = RegInit(0.U(64.W))
        // Clearing loses no coincident event; event wins over both W1C and clear.
        val increments = port.deltas.map(_.toSeq).getOrElse(Seq(port.events(0).asUInt,
            port.events(1).asUInt, port.events(2).asUInt, port.events(3).asUInt,
            Mux(port.events(0), port.txBytes, 0.U), Mux(port.events(1), port.rxBytes, 0.U)))
        Seq(txFrames, rxFrames, rxDrops, rxBadFcs, txBytes, rxBytes).zip(increments).foreach {
            case (counter, increment) => counter := Mux(clear, 0.U, counter) + increment
        }
        val kind = config.ports(n)
        // CAP records intended media interface, NOT a link-up or implemented-PCS claim.
        val capability = (BigInt(config.maxFrameBytes) << 32) |
            (BigInt(kind.mediaBits) << 16) | (BigInt(1) << kind.capabilityBit) |
            (if (config.rxAdmissionStop) BigInt(1) << 8 else BigInt(0))
        readValues(n) := MuxLookup(offset, 0.U(64.W))(Seq(
            0x00.U -> "h56474d4100010001".U(64.W), 0x08.U -> capability.U(64.W),
            0x10.U -> control, 0x18.U -> macAddress, 0x20.U -> config.maxFrameBytes.U(64.W),
            0x28.U -> Cat(port.rxBusy, port.txBusy, port.linkUp),
            0x30.U -> pending, 0x38.U -> irqEnable,
            0x40.U -> txFrames, 0x48.U -> rxFrames, 0x50.U -> rxDrops, 0x58.U -> rxBadFcs,
            0x60.U -> txBytes, 0x68.U -> rxBytes,
            0x80.U -> Cat(mdioDone, mdio.io.busy), 0x88.U -> mdioResult) ++
            (if (config.rxAdmissionStop) Seq(0x90.U ->
                Cat(rxStopRequest.get && port.rxStopDrained.get, rxStopRequest.get)) else Seq.empty))
    }
    val legal = portLegal.asUInt.orR
    io.tl.a.ready := replies.io.enq.ready && (!legal || Mux1H(selected, portReady))
    replies.io.enq.valid := io.tl.a.fire
    replies.io.enq.bits := 0.U.asTypeOf(replies.io.enq.bits)
    val dataResponse = read || a.opcode === TLOpcode.ArithmeticData || a.opcode === TLOpcode.LogicalData
    replies.io.enq.bits.opcode := Mux(dataResponse, TLOpcode.AccessAckData, TLOpcode.AccessAck)
    replies.io.enq.bits.size := a.size
    replies.io.enq.bits.source := a.source
    replies.io.enq.bits.denied := !legal
    replies.io.enq.bits.corrupt := !legal && dataResponse
    replies.io.enq.bits.data := Mux(legal && read, Mux1H(selected, readValues), 0.U)
    io.irq := irqs.asUInt
}
