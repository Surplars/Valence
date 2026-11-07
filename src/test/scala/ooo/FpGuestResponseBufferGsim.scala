package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Uniform host interface; absent production fields are visibly zero, never extra storage. */
class FpGuestBufferPacket extends Bundle {
    val data = UInt(64.W)
    val error = Bool()
    val pageFault = Bool()
    val returnHandle = UInt(6.W)
    val guestFault = new GuestFaultMetadata
}

class FpGuestBufferLane extends Bundle {
    val request = Flipped(Decoupled(new DataRequest(6)))
    val forwardRequest = Decoupled(new DataRequest(6))
    val response = Flipped(Decoupled(new FpGuestBufferPacket))
    val result = Decoupled(new FpGuestBufferPacket)
    val idle = Output(Bool())
}

/** Synthetic response-envelope component test, not guest F/D instruction execution.
  * Every configuration instantiates the production buffer. Only public ports are
  * observed. Requests are an independent passthrough, not response credit owners.
  * Named lanes avoid the GSIM top-level Vec accessor ABI.
  */
class FpGuestResponseBufferGsim extends Module {
    val io = IO(new Bundle {
        val lane0 = new FpGuestBufferLane
        val lane1 = new FpGuestBufferLane
        val lane2 = new FpGuestBufferLane
        val lane3 = new FpGuestBufferLane
        val lane4 = new FpGuestBufferLane
        val lane5 = new FpGuestBufferLane
        val lane6 = new FpGuestBufferLane
        val lane7 = new FpGuestBufferLane
        val lane8 = new FpGuestBufferLane
        val lane9 = new FpGuestBufferLane
        val lane10 = new FpGuestBufferLane
        val lane11 = new FpGuestBufferLane
        val lane12 = new FpGuestBufferLane
        val lane13 = new FpGuestBufferLane
        val lane14 = new FpGuestBufferLane
        val lane15 = new FpGuestBufferLane
    })
    val lanes = Seq(io.lane0, io.lane1, io.lane2, io.lane3, io.lane4, io.lane5, io.lane6, io.lane7,
        io.lane8, io.lane9, io.lane10, io.lane11, io.lane12, io.lane13, io.lane14, io.lane15)
    val modes = Seq((false, false, false), (true, false, false), (true, true, false), (true, true, true))
    for ((lane, index) <- lanes.zipWithIndex) {
        val (registerPayload, registerHead, emptyFlow) = modes(index / 4)
        val metadata = (index / 2) % 2 == 1
        val tagged = index % 2 == 1
        // Exercise every bit, including 63, rather than a narrower default namespace.
        val returnConfig = if (tagged) Some(CpuReturnConfig(32, 31, fpEnabled = true)) else None
        val buffer = Module(new DataResponseBuffer(registerPayload, registerHead, emptyFlow,
            returnConfig = returnConfig, guestFaultMetadata = metadata)).suggestName(s"buffer$index")

        buffer.io.upstream.request.valid := lane.request.valid
        lane.request.ready := buffer.io.upstream.request.ready
        CpuReturnTransport.requestPayload(buffer.io.upstream.request.bits, lane.request.bits)
        buffer.io.upstream.request.bits.returnHandle.foreach(_ := lane.request.bits.returnHandle.get)
        lane.forwardRequest.valid := buffer.io.downstream.request.valid
        buffer.io.downstream.request.ready := lane.forwardRequest.ready
        CpuReturnTransport.requestPayload(lane.forwardRequest.bits, buffer.io.downstream.request.bits)
        lane.forwardRequest.bits.returnHandle.get := buffer.io.downstream.request.bits.returnHandle.getOrElse(0.U)

        buffer.io.downstream.response.valid := lane.response.valid
        lane.response.ready := buffer.io.downstream.response.ready
        buffer.io.downstream.response.bits.data := lane.response.bits.data
        buffer.io.downstream.response.bits.error := lane.response.bits.error
        buffer.io.downstream.response.bits.pageFault := lane.response.bits.pageFault
        buffer.io.downstream.response.bits.returnHandle.foreach(_ := lane.response.bits.returnHandle)
        buffer.io.downstreamGuestFault.foreach(_ := lane.response.bits.guestFault)
        lane.result.valid := buffer.io.upstream.response.valid
        buffer.io.upstream.response.ready := lane.result.ready
        lane.result.bits.data := buffer.io.upstream.response.bits.data
        lane.result.bits.error := buffer.io.upstream.response.bits.error
        lane.result.bits.pageFault := buffer.io.upstream.response.bits.pageFault
        lane.result.bits.returnHandle := buffer.io.upstream.response.bits.returnHandle.getOrElse(0.U)
        lane.result.bits.guestFault := buffer.io.upstreamGuestFault.getOrElse(0.U.asTypeOf(new GuestFaultMetadata))
        lane.idle := buffer.io.idle
    }
}

object FpGuestResponseBufferGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new FpGuestResponseBufferGsim, Array("--target-dir", args(0)))
}
