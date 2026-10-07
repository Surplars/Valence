package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.TwoEntryRegisterQueue

private[ooo] class VirtualDataRequest extends Bundle {
    val request = new DataRequest
    val context = new VmCsrState
}

private[ooo] class TranslatedDataRequest extends Bundle {
    val request = new DataRequest
    val privilege = UInt(2.W)
    val checkPhysical = Bool()
    val pageFault = Bool()
    val accessFault = Bool()
}

private[ooo] class TranslationResponseOwner extends Bundle {
    val fault = Bool()
    val pageFault = Bool()
}

private[ooo] class CheckedDataRequest extends Bundle {
    val request = new DataRequest
    val fault = Bool()
    val pageFault = Bool()
}

/** In-order DTLB boundary. Hits may enter the translated-request FIFO in the request cycle; a miss blocks new
  * translations, but already translated physical requests and responses continue. The physical port may have multiple
  * requests outstanding. Fault placeholders share its response-order queue without issuing a physical request.
  */
class DataTranslationAdapter(p: OooParams, entries: Int = 8, registerCheckedRequests: Boolean = false) extends Module {
    require(p.virtualMemoryLevels > 0 && Set(4, 8, 16).contains(entries))
    require(!p.registeredTranslationHeads || registerCheckedRequests,
        "registered translation heads require checked request capture")
    val io = IO(new Bundle {
        val virtual = Flipped(new DataPort)
        val physical = new DataPort
        val translation = new SvTranslationPort
        val vmState = Input(new VmCsrState)
        val pmpState = Input(new PmpState)
        val idle = Output(Bool())
        val physicalRequest = Output(Bool())
        val pageFault = Output(Bool())
    })

    // Registered queue boundaries keep the TLB CAM/PMP/TileLink arbitration off one FPGA combinational path.
    val translated = Module(new Queue(new TranslatedDataRequest, entries, pipe = false, flow = false))
    val owners = Module(new Queue(new TranslationResponseOwner, entries, pipe = false, flow = false))
    val waiting = RegInit(false.B)
    val savedRequest = Reg(new DataRequest)
    val savedPrivilege = Reg(UInt(2.W))
    // Register the actual virtual ingress, not merely the translated egress.
    // Capture the architectural context at upstream acceptance; a queued request
    // must not inherit a later SATP/SUM/MXR/privilege value. PMP remains checked
    // at the existing physical authorization boundary. CPU fences drain accepted
    // memory, and idle includes this queue for all integrating clients.
    val virtualRequests = if (p.registeredTranslationHeads)
        Some(Module(new TwoEntryRegisterQueue(new VirtualDataRequest))) else None
    virtualRequests.foreach { stage =>
        stage.io.enq.valid := io.virtual.request.valid
        stage.io.enq.bits.request := io.virtual.request.bits
        stage.io.enq.bits.context := io.vmState
        io.virtual.request.ready := stage.io.enq.ready
    }
    val incoming = virtualRequests.map { stage =>
        val request = Wire(Decoupled(new DataRequest))
        request.valid := stage.io.deq.valid
        request.bits := stage.io.deq.bits.request
        stage.io.deq.ready := request.ready
        request
    }.getOrElse(io.virtual.request)
    val context = virtualRequests.map(_.io.deq.bits.context).getOrElse(io.vmState)
    val active = incoming.bits.virtualized
    val canAccept = !waiting && translated.io.enq.ready

    io.translation.request.valid := incoming.valid && active && canAccept
    io.translation.request.bits.virtualAddress := incoming.bits.address
    io.translation.request.bits.rootPpn := context.satp(43, 0)
    io.translation.request.bits.asid := context.satp(59, 44)
    io.translation.request.bits.mode := context.satp(63, 60)
    io.translation.request.bits.privilege := context.dataPrivilege
    io.translation.request.bits.access := Mux(incoming.bits.atomic,
        Mux(incoming.bits.atomicOp === 2.U, PmpAccess.read,
            Mux(incoming.bits.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(incoming.bits.write, PmpAccess.write, PmpAccess.read))
    io.translation.request.bits.sum := context.sum
    io.translation.request.bits.mxr := context.mxr
    incoming.ready := canAccept && Mux(active, io.translation.request.ready, true.B)
    // A TLB hit can produce a response in the request cycle. Its request.ready already
    // depends on response.ready, so this must not depend on request.fire.
    io.translation.response.ready := translated.io.enq.ready

    val translatedReply = io.translation.response.valid && (waiting || io.translation.request.fire)
    translated.io.enq.valid := (!waiting && incoming.valid && !active) || translatedReply
    val original = Mux(waiting, savedRequest, incoming.bits)
    translated.io.enq.bits := 0.U.asTypeOf(new TranslatedDataRequest)
    translated.io.enq.bits.request := original
    translated.io.enq.bits.request.address := Mux(active || waiting,
        io.translation.response.bits.physicalAddress, original.address)
    translated.io.enq.bits.request.virtualized := false.B
    translated.io.enq.bits.request.uncached := original.uncached ||
        ((active || waiting) && io.translation.response.bits.pbmt =/= 0.U)
    translated.io.enq.bits.privilege := Mux(waiting, savedPrivilege, context.dataPrivilege)
    translated.io.enq.bits.checkPhysical := active || waiting
    translated.io.enq.bits.pageFault := (active || waiting) && io.translation.response.bits.pageFault
    translated.io.enq.bits.accessFault := (active || waiting) && io.translation.response.bits.accessFault

    when(io.translation.request.fire && !io.translation.response.fire) {
        waiting := true.B
        savedRequest := incoming.bits
        savedPrivilege := context.dataPrivilege
    }
    when(waiting && io.translation.response.fire) { waiting := false.B }

    val head = translated.io.deq.bits
    val request = head.request
    val pmp = Module(new PmpChecker(p.pmpEntries))
    pmp.io.state := io.pmpState
    pmp.io.address := request.address
    pmp.io.size := request.size
    pmp.io.privilege := head.privilege
    pmp.io.access := Mux(request.atomic,
        Mux(request.atomicOp === 2.U, PmpAccess.read,
            Mux(request.atomicOp === 3.U, PmpAccess.write, PmpAccess.readWrite)),
        Mux(request.write, PmpAccess.write, PmpAccess.read))
    val atomicOutside = request.atomic && head.checkPhysical &&
        !SpeculativeRamRange.contains(p, request.address, request.size)
    val fault = head.pageFault || head.accessFault ||
        (head.checkPhysical && pmp.io.denied) || atomicOutside
    // Snapshot the request and fault decision before downstream grants.
    // Fault placeholders remain ordered but never issue physical requests.
    val checked: Option[QueueIO[CheckedDataRequest]] = if (registerCheckedRequests)
        Some(if (p.registeredTranslationHeads)
            Module(new TwoEntryRegisterQueue(new CheckedDataRequest)).suggestName("checked").io
        else Module(new Queue(new CheckedDataRequest, 2, pipe = false, flow = false)).suggestName("checked").io)
    else None
    checked.foreach { stage =>
        stage.enq.valid := translated.io.deq.valid
        stage.enq.bits.request := request
        stage.enq.bits.fault := fault
        stage.enq.bits.pageFault := head.pageFault
        translated.io.deq.ready := stage.enq.ready
    }
    val physicalHead = checked.map(_.deq.bits.request).getOrElse(request)
    val physicalFault = checked.map(_.deq.bits.fault).getOrElse(fault)
    val physicalPageFault = checked.map(_.deq.bits.pageFault).getOrElse(head.pageFault)
    val physicalValid = checked.map(_.deq.valid).getOrElse(translated.io.deq.valid)
    val physicalReady = owners.io.enq.ready && (physicalFault || io.physical.request.ready)
    checked match {
        case Some(stage) => stage.deq.ready := physicalReady
        case None => translated.io.deq.ready := physicalReady
    }
    io.physical.request.valid := physicalValid && !physicalFault && owners.io.enq.ready
    io.physical.request.bits := physicalHead
    owners.io.enq.valid := physicalValid && physicalReady
    owners.io.enq.bits.fault := physicalFault
    owners.io.enq.bits.pageFault := physicalPageFault
    io.physicalRequest := io.physical.request.fire

    val owner = owners.io.deq.bits
    io.virtual.response.valid := owners.io.deq.valid &&
        (owner.fault || io.physical.response.valid)
    io.virtual.response.bits := io.physical.response.bits
    when(owner.fault) {
        io.virtual.response.bits.data := 0.U
        io.virtual.response.bits.error := true.B
        io.virtual.response.bits.pageFault := owner.pageFault
    }
    io.physical.response.ready := owners.io.deq.valid && !owner.fault && io.virtual.response.ready
    owners.io.deq.ready := io.virtual.response.fire
    io.pageFault := io.virtual.response.fire && owner.fault && owner.pageFault
    io.idle := !waiting && !translated.io.deq.valid && !owners.io.deq.valid &&
        checked.map(stage => !stage.deq.valid).getOrElse(true.B) &&
        virtualRequests.map(stage => !stage.io.deq.valid).getOrElse(true.B)
}
