package soc.core.ooo

import chisel3._

/** Nominal final-port certificate, not a second handshaken ingress or permission grant.
  * The accepted context is the same live snapshot that the fallback ingress captures.
  * No translation response, queue credit, physical response or owner feeds this builder.
  */
private[ooo] class CertifiedIngressDescriptor(p: OooParams) extends Bundle {
    val result = new TranslatedDataRequest(p)
    val context = new VmCsrState
    val sidecarsAbsent = Bool()
    val routeQualified = Bool()
}

private[ooo] class CertifiedIngressDescriptorBuilder(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val request = Input(new DataRequest(p.dataReturnHandleBits))
        val context = Input(new VmCsrState)
        val authorization = Input(new DataAuthorizationContext)
        val postedPresent = Input(Bool())
        val canonicalPresent = Input(Bool())
        val frozenPresent = Input(Bool())
        val descriptor = Output(new CertifiedIngressDescriptor(p))
    })
    val descriptor = io.descriptor
    val request = io.request
    val mode = io.context.satp(63, 60)
    descriptor.context := io.context
    descriptor.sidecarsAbsent := !io.postedPresent && !io.canonicalPresent && !io.frozenPresent
    // Stable/supported context is a route restriction only. A rejection here does
    // not create a sticky fault in the unchanged registered fallback path.
    descriptor.routeQualified := io.authorization.stable &&
        (io.context.dataPrivilege === 0.U || io.context.dataPrivilege === 1.U) &&
        mode >= 8.U && mode <= (p.virtualMemoryLevels + 5).U
    descriptor.result := 0.U.asTypeOf(new TranslatedDataRequest(p))
    descriptor.result.request := request
    descriptor.result.privilege := io.context.dataPrivilege
    descriptor.result.checkPhysical := true.B
    descriptor.result.pageFault := false.B
    descriptor.result.accessFault := !request.precheckedLoad || request.virtualized ||
        request.write || request.atomic || request.uncached ||
        io.context.dataPrivilege === 3.U || mode === 0.U ||
        request.translationEpoch =/= io.authorization.epoch ||
        io.authorization.changing || io.authorization.flush
    // The address is already PA, not a recovered original VA. Store origin and
    // all posted/frozen authority remain zero; this field cannot create an event.
    descriptor.result.originalVirtualAddress.foreach(_ := request.address)
}
