package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink._

/** Two TL-UL masters and two address windows; different banks can accept A and return D concurrently. */
class TwoMasterTwoBankTileLinkCrossbar(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    base: BigInt = BigInt("80000000", 16),
    bankBytes: BigInt = 65536,
    secondBankBytes: BigInt = 0,
    prefixAddressDecode: Boolean = false,
    rawResponseMetadata: Boolean = false,
    rawRequestMetadata: Boolean = false
) extends Module {
    require(params.sourceBits >= 1 && params.sourceBits <= 6)
    val managerParams = params.copy(sourceBits = params.sourceBits + 1)
    val io = IO(new Bundle {
        val masters = Vec(2, Flipped(new TLBundle(params)))
        val banks = Vec(2, new TLBundle(managerParams))
    })
    val routers = Seq.fill(2)(Module(new TwoBankTileLinkRouter(params, base, bankBytes, secondBankBytes,
        prefixAddressDecode, rawResponseMetadata)))
    val arbiters = Seq.fill(2)(Module(new TwoMasterTileLinkArbiter(params, rawResponseMetadata, rawRequestMetadata)))
    for (master <- 0 until 2) {
        io.masters(master) <> routers(master).io.host
    }
    for (bank <- 0 until 2) {
        for (master <- 0 until 2) {
            routers(master).io.banks(bank) <> arbiters(bank).io.masters(master)
        }
        io.banks(bank) <> arbiters(bank).io.manager
    }
}
