// Vivado BD pin metadata for the PS-facing Chisel assembly. Pure wiring.
module I1PsPlBoundary (
    input wire rawCpuClock,
    input wire rawVpuClock,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME systemClock, ASSOCIATED_BUSIF M_AXI_HP, ASSOCIATED_RESET boardColdReset" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 systemClock CLK" *)
    input wire systemClock,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME boardColdReset, POLARITY ACTIVE_HIGH" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 boardColdReset RST" *)
    input wire boardColdReset,
    (* X_INTERFACE_INFO = "xilinx.com:interface:gpio:1.0 PS_GPIO TRI_O" *)
    input wire [2:0] ps_gpio_o,
    (* X_INTERFACE_INFO = "xilinx.com:interface:gpio:1.0 PS_GPIO TRI_I" *)
    output wire [2:0] ps_gpio_i,
    (* X_INTERFACE_INFO = "xilinx.com:interface:gpio:1.0 PS_GPIO TRI_T" *)
    input wire [2:0] ps_gpio_t,
    input wire uartRx,
    output wire uartTx,
    input wire externalIrq,
    input wire wakeCpu,
    input wire wakeVpu,
    output wire cpuStopAck,
    output wire vpuStopAck,
    output wire fabricIdle,
    output wire protocolError,
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME M_AXI_HP, PROTOCOL AXI4, ADDR_WIDTH 49, DATA_WIDTH 64, ID_WIDTH 6, ARUSER_WIDTH 1, AWUSER_WIDTH 1" *)
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWVALID" *)
    output wire m_axi_hp_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWREADY" *)
    input wire m_axi_hp_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWID" *)
    output wire [5:0] m_axi_hp_awid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWADDR" *)
    output wire [48:0] m_axi_hp_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWLEN" *)
    output wire [7:0] m_axi_hp_awlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWSIZE" *)
    output wire [2:0] m_axi_hp_awsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWBURST" *)
    output wire [1:0] m_axi_hp_awburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWLOCK" *)
    output wire m_axi_hp_awlock,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWCACHE" *)
    output wire [3:0] m_axi_hp_awcache,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWPROT" *)
    output wire [2:0] m_axi_hp_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWQOS" *)
    output wire [3:0] m_axi_hp_awqos,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP WVALID" *)
    output wire m_axi_hp_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP WREADY" *)
    input wire m_axi_hp_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP WDATA" *)
    output wire [63:0] m_axi_hp_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP WSTRB" *)
    output wire [7:0] m_axi_hp_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP WLAST" *)
    output wire m_axi_hp_wlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP BVALID" *)
    input wire m_axi_hp_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP BREADY" *)
    output wire m_axi_hp_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP BID" *)
    input wire [5:0] m_axi_hp_bid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP BRESP" *)
    input wire [1:0] m_axi_hp_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARVALID" *)
    output wire m_axi_hp_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARREADY" *)
    input wire m_axi_hp_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARID" *)
    output wire [5:0] m_axi_hp_arid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARADDR" *)
    output wire [48:0] m_axi_hp_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARLEN" *)
    output wire [7:0] m_axi_hp_arlen,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARSIZE" *)
    output wire [2:0] m_axi_hp_arsize,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARBURST" *)
    output wire [1:0] m_axi_hp_arburst,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARLOCK" *)
    output wire m_axi_hp_arlock,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARCACHE" *)
    output wire [3:0] m_axi_hp_arcache,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARPROT" *)
    output wire [2:0] m_axi_hp_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARQOS" *)
    output wire [3:0] m_axi_hp_arqos,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP RVALID" *)
    input wire m_axi_hp_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP RREADY" *)
    output wire m_axi_hp_rready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP RID" *)
    input wire [5:0] m_axi_hp_rid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP RDATA" *)
    input wire [63:0] m_axi_hp_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP RRESP" *)
    input wire [1:0] m_axi_hp_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP RLAST" *)
    input wire m_axi_hp_rlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP AWUSER" *)
    output wire m_axi_hp_awuser,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 M_AXI_HP ARUSER" *)
    output wire m_axi_hp_aruser
);
    wire started;
    // Internal level wires do not use the pad tristate outputs.
    assign ps_gpio_i = {started, 2'b00};
    // HP AxUSER=0 selects physical addresses (no SMMU translation).
    assign m_axi_hp_aruser = 1'b0;
    assign m_axi_hp_awuser = 1'b0;
    I1SpinorPsFpga system (
        .rawCpuClock(rawCpuClock), .rawVpuClock(rawVpuClock),
        .systemClock(systemClock), .boardColdReset(boardColdReset),
        .io_start(ps_gpio_o[0]), .io_ddrReady(ps_gpio_o[1]), .io_started(started),
        .io_uartRx(uartRx), .io_uartTx(uartTx),
        .io_externalIrq(externalIrq), .io_wakeCpu(wakeCpu), .io_wakeVpu(wakeVpu),
        .io_cpuStopAck(cpuStopAck), .io_vpuStopAck(vpuStopAck),
        .io_fabricIdle(fabricIdle), .io_protocolError(protocolError),
        .io_hp_aw_valid(m_axi_hp_awvalid),
        .io_hp_aw_ready(m_axi_hp_awready),
        .io_hp_aw_bits_id(m_axi_hp_awid),
        .io_hp_aw_bits_addr(m_axi_hp_awaddr),
        .io_hp_aw_bits_len(m_axi_hp_awlen),
        .io_hp_aw_bits_size(m_axi_hp_awsize),
        .io_hp_aw_bits_burst(m_axi_hp_awburst),
        .io_hp_aw_bits_lock(m_axi_hp_awlock),
        .io_hp_aw_bits_cache(m_axi_hp_awcache),
        .io_hp_aw_bits_prot(m_axi_hp_awprot),
        .io_hp_aw_bits_qos(m_axi_hp_awqos),
        .io_hp_w_valid(m_axi_hp_wvalid),
        .io_hp_w_ready(m_axi_hp_wready),
        .io_hp_w_bits_data(m_axi_hp_wdata),
        .io_hp_w_bits_strb(m_axi_hp_wstrb),
        .io_hp_w_bits_last(m_axi_hp_wlast),
        .io_hp_b_valid(m_axi_hp_bvalid),
        .io_hp_b_ready(m_axi_hp_bready),
        .io_hp_b_bits_id(m_axi_hp_bid),
        .io_hp_b_bits_resp(m_axi_hp_bresp),
        .io_hp_ar_valid(m_axi_hp_arvalid),
        .io_hp_ar_ready(m_axi_hp_arready),
        .io_hp_ar_bits_id(m_axi_hp_arid),
        .io_hp_ar_bits_addr(m_axi_hp_araddr),
        .io_hp_ar_bits_len(m_axi_hp_arlen),
        .io_hp_ar_bits_size(m_axi_hp_arsize),
        .io_hp_ar_bits_burst(m_axi_hp_arburst),
        .io_hp_ar_bits_lock(m_axi_hp_arlock),
        .io_hp_ar_bits_cache(m_axi_hp_arcache),
        .io_hp_ar_bits_prot(m_axi_hp_arprot),
        .io_hp_ar_bits_qos(m_axi_hp_arqos),
        .io_hp_r_valid(m_axi_hp_rvalid),
        .io_hp_r_ready(m_axi_hp_rready),
        .io_hp_r_bits_id(m_axi_hp_rid),
        .io_hp_r_bits_data(m_axi_hp_rdata),
        .io_hp_r_bits_resp(m_axi_hp_rresp),
        .io_hp_r_bits_last(m_axi_hp_rlast)
    );
endmodule
