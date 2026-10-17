package soc.core.ooo

import chisel3._
import chisel3.util._

/** Shape validation is not ROB authority. The producer must bind its one-bit
  * qualification to the existing immutable head token/request owner.
  */
private[ooo] object PostedCollectionRead {
    def shape(p: OooParams, request: DataRequest): Bool = {
        val lanes = MuxLookup(request.size, 255.U(8.W))(
            Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        !request.write && !request.atomic && !request.virtualized &&
            !request.precheckedLoad && !request.uncached &&
            SpeculativeRamRange.contains(p, request.address, request.size) &&
            AlignedMemoryDisjoint.aligned(request.address, request.size) &&
            request.mask === (lanes << request.address(2, 0))(7, 0)
    }

    def held(request: DecoupledIO[DataRequest], qualified: Bool): Unit = {
        val stalled = RegNext(request.valid && !request.ready, false.B)
        val oldRequest = RegEnable(request.bits, request.valid && !request.ready)
        val oldQualified = RegEnable(qualified, request.valid && !request.ready)
        when(stalled) {
            assert(request.valid && request.bits.asUInt === oldRequest.asUInt && qualified === oldQualified,
                "held collection read lost its original request/qualification")
        }
    }
}
