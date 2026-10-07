`timescale 1ns/1ps
// Complete pad-management boundary. No CPU registers or core pipeline changes.
module native_phy_board_control(
    input wire clock_aon, clock_tx, clock_forward, clock_rx,
    input wire cold_reset, tx_reset_request, rx_reset,
    input wire mdio_pad, software_mdc, software_out, software_oe,
    output wire pad_mdc, pad_out, pad_oe, cpu_mdio_input,
    output wire tx_reset_raw, tx_reset_forward, rx_allowed
);
    wire init_mdc, init_out, init_oe, bus_released, verified_ready;
    native_phy_tx_init initializer(.clock(clock_aon), .cold_reset(cold_reset),
        .mdio_pad(mdio_pad), .software_mdc(software_mdc), .software_oe(software_oe),
        .mdc(init_mdc), .mdio_out(init_out), .mdio_oe(init_oe),
        .bus_released(bus_released), .ready(verified_ready), .phy_address(), .fault());
    assign pad_mdc=bus_released ? software_mdc : init_mdc;
    assign pad_out=bus_released ? software_out : init_out;
    assign pad_oe=bus_released ? software_oe : init_oe;
    // CPU's existing two-FF pad synchronizer remains the only CPU boundary.
    // Reads made before ownership transfer must see no ACK, never init traffic.
    assign cpu_mdio_input=bus_released ? mdio_pad : 1'b1;
    wire inhibit_tx=tx_reset_request | ~verified_ready;
    native_tx_reset_boundary tx_release(.clock_tx(clock_tx), .clock_forward(clock_forward),
        .inhibit(inhibit_tx), .reset_raw(tx_reset_raw), .reset_forward(tx_reset_forward));
    (* ASYNC_REG="TRUE" *) reg rx_ready_meta, rx_ready_sync;
    always @(posedge clock_rx or posedge rx_reset)
        if(rx_reset) begin rx_ready_meta<=0; rx_ready_sync<=0; end
        else begin rx_ready_meta<=verified_ready; rx_ready_sync<=rx_ready_meta; end
    assign rx_allowed=rx_ready_sync;
endmodule
