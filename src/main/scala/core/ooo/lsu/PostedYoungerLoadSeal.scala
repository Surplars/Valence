package soc.core.ooo

import chisel3._

/** A preparation classification only; the caller retains staged full-token validity
  * and the original posted/head authorization and nonposted launch boundary.
  * This Scala helper adds no module, state or payload read port.
  */
object PostedYoungerLoadSeal {
    private def ordinaryMemory(request: IntegerRequest): Bool =
        request.memory && !request.atomic && !request.system && !request.mulDiv &&
            request.controlFlow === ControlFlow.none && request.operation === IntegerOp.add &&
            !request.fetchFault && !request.fetchPageFault

    def defer(
        postedBusy: Bool,
        headValid: Bool,
        headRequest: IntegerRequest,
        choiceValid: Bool,
        younger: Bool,
        live: Bool,
        pending: Bool,
        indexMatches: Bool,
        selected: IntegerRequest,
        physical: Bool,
        ordinaryRam: Bool,
        pmpAllowed: Bool,
        aligned: Bool
    ): Bool = {
        // An unselected head load/atomic retains the old intent boundary, too.
        val headAllows = !headRequest.memory || (ordinaryMemory(headRequest) && headRequest.store)
        postedBusy && headValid && headAllows && choiceValid && younger && live && pending && indexMatches &&
            ordinaryMemory(selected) && !selected.store && physical && ordinaryRam && pmpAllowed && aligned
    }
}
