package soc.core.ooo

/** Explicit capacity-only experiment. Omitted dimensions retain the selected
  * profile's existing values; storage topology and port widths do not change.
  * A legal but register-starved combination remains useful as a control.
  */
final case class BackendCapacityConfig(
    robEntries: Option[Int] = None,
    physicalRegs: Option[Int] = None
) {
    require(robEntries.forall(Set(16, 32, 64).contains), "ROB experiment supports 16, 32 or 64 entries")
    require(physicalRegs.forall(Set(48, 64).contains), "PRF experiment supports 48 or 64 entries")

    def configure(p: OooParams): OooParams = {
        require((robEntries.isEmpty && physicalRegs.isEmpty) ||
            (p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2),
            "backend capacity experiment retains the two-wide backend")
        p.copy(robEntries = robEntries.getOrElse(p.robEntries), physicalRegs = physicalRegs.getOrElse(p.physicalRegs))
    }
}
