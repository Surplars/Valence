# Optional managed MAC clock-root alignment

This helper is a physical candidate, not timing signoff. It must not stop an
otherwise authorized route merely because native placement uses multiple roots.
It does not modify the recovered `phy_rx` clock or introduce clock exceptions.

## Result contract

- `inspect`: read-only. Returns `SINGLE_ROOT_CANDIDATE` plus `root`, or
  `DEFERRED_MULTI_ROOT` plus a reason. Both include `nets` and `roots_by_net`.
- `apply`: only a fully validated single-root candidate writes the three
  `USER_CLOCK_ROOT` properties and returns `APPLIED_REQUIRES_REROUTE`.
- `DEFERRED_MULTI_ROOT`: no property write, no root selection, and no design or
  routing operation. It means this optional optimization was **not applied**.
  Native timing is still unqualified, not passed or waived.
- Missing objects, malformed/unknown/duplicate regions, missing placement, or
  changed clock topology remain errors before any write. Do not catch all errors
  and relabel them as the reviewed multi-root deferral.

Callers must not unroute before obtaining and handling this result. For a future
candidate invocation, after sourcing the helper:

```tcl
set macRootResult [common_mac_placement::apply]
switch -- [dict get $macRootResult status] {
    APPLIED_REQUIRES_REROUTE {
        update_clock_routing
        # Continue the separately authorized candidate route and full timing checks.
    }
    DEFERRED_MULTI_ROOT {
        # No unroute, update_clock_routing, or root override for this optimization.
        # An independently authorized route-only continuation can proceed unchanged.
        puts "MAC_ROOT_OPTIMIZATION_NOT_APPLIED_NATIVE_ASSIGNMENT_PRESERVED"
    }
    default {error "Unexpected MAC root helper result"}
}
```

The repository currently has no production caller of this optional helper; the
Tcl test is its only checked-in caller. External generated native scripts must
adopt the result contract separately. Do not patch a running native job.

## Why multiple roots are preserved

AMD UG912 documents `CLOCK_ROOT` as the read-only actual clock assignment and
explicitly notes that the router can add roots, for example with Explore. Thus a
single net with `{X3Y3 X2Y3}` is not automatically an invalid net selection.
`USER_CLOCK_ROOT` specifies one region/Pblock, not an instruction to copy the
actual root list. Neither list order nor overlap with another tree identifies
which root serves a particular timing endpoint. Never select the first root,
choose a shared root without branch evidence, or add an unproved delay group.

- https://docs.amd.com/r/en-US/ug912-vivado-properties/CLOCK_ROOT
- https://docs.amd.com/r/en-US/ug912-vivado-properties/USER_CLOCK_ROOT

## Bounded read-only native evidence

After the current job finishes, inspect its own saved physical/routed checkpoint.
Limit queries to these three existing drivers:

- `network_clock/raw_div/O`
- `u_soc/peripherals/gmac/txManaged_gate/buffer/O`
- `u_soc/peripherals/gmac/rxManaged_gate/buffer/O`

For each exact pin, retain the unique immediate output net and its `NAME`,
`CLOCK_ROOT`, `USER_CLOCK_ROOT`, `CLOCK_DELAY_GROUP`, and `ROUTE_STATUS`; record the
buffer's `REF_NAME` and `LOC`. Enumerate only that net's hierarchical segments,
leaf output drivers, and leaf input loads. Confirm there is one actual driver,
and distinguish direct RAW125 register loads from the two serial BUFG input
loads. Summarize those load cells by placed clock region rather than printing an
unbounded design-wide census. Inspect the exact two managed input pins' segments
to confirm the raw-to-managed relationship.

For a failing RAW125-to-managed path in the new report, use its actual verified
source/destination pins for max and min `report_timing -path_type full_clock_expanded`.
Keep both clock paths, clock pins, insertion delays and CPR. Clock-root lists and
load-region counts alone do not prove the root-to-leaf branch assignment or which
single override would improve both setup and hold. Until that evidence supports
a separate physical candidate, preserve the tool's multi-root plan.

Run the synthetic API/negative test with:
`tclsh fpga/common/test_mac_clock_placement.tcl`
This tests control flow and zero-mutation deferral, not Vivado implementation.
