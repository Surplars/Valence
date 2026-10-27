package soc.core.ooo

import chisel3._
import chisel3.util._

/** Numerical-only use of an existing registered successful load result.
  * No state, PRF publication, permission, credit or completion is created here.
  * The caller binds full producer/consumer ownership and kill at capture, and
  * retains registered-source readiness for every actual memory/proof admission.
  */
object RegisteredMemoryOperandAuthority {
    /** Exact existing producer ownership gate, separate from registered rank metadata. */
    def producerAuthority(load: ValidIO[UInt], completionValid: Bool, exception: Bool, live: Bool,
        ownerToken: UInt, completionToken: UInt, ordinaryLoad: Bool, writesRd: Bool,
        destination: UInt): Bool =
        load.valid && completionValid && !exception && live && ownerToken === completionToken &&
            ordinaryLoad && writesRd && destination === load.bits && load.bits =/= 0.U

    def allowed(forwarded: Bool, producerAuthority: Bool, producerKilled: Bool): Bool =
        !forwarded || (producerAuthority && !producerKilled)

    def hit(source: UInt, load: ValidIO[UInt]): Bool =
        source =/= 0.U && load.valid && load.bits === source

    def ready(source: UInt, registeredReady: Bool, load: ValidIO[UInt]): Bool =
        registeredReady || hit(source, load)

    def value(source: UInt, registeredReady: Bool, stored: UInt,
        load: ValidIO[UInt], data: UInt): UInt =
        Mux(registeredReady, stored, Mux(hit(source, load), data, stored))
}
