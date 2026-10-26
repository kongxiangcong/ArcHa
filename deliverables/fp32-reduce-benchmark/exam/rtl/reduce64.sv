// Independently authored, deliberately simple common starting design.
// Full six-level tree. This is a functional baseline, not a competitive reference.
module reduce64 (
  input logic clk, rst, en, cap, row_last,
  input logic [7:0] sub,
  input logic [255:0] pacc,
  output logic [31:0] root, root_o,
  output logic root_v
);
  import otpu_fp::*;
  f32_t saved [64];
  wire [31:0] x [64];
  wire [31:0] level [7][64];
  logic [27:0] valid;
  always_ff @(posedge clk) begin
    if (rst) valid <= '0;
    else if (en) valid <= {valid[26:0], cap && row_last};
    if (en && cap && !rst)
      for (int k=0; k<8; k++) saved[8*sub+k] <= pacc[32*k +: 32];
  end
  for (genvar i=0; i<64; i++) begin : g_in
    // Bypass the last beat so level 1 samples the entire row on its last edge.
    if (i>=56) assign x[i]=pacc[32*(i-56) +: 32];
    else assign x[i]=saved[i];
    assign level[0][i]=x[i];
  end
  for (genvar l=0; l<6; l++) begin : g_level
    for (genvar i=0; i<(32>>l); i++) begin : g_add
      otpu_fadd #(.LAT(4)) add (.clk, .en,
        .a(level[l][i]), .b(level[l][i+(32>>l)]), .y(level[l+1][i]));
    end
  end
  otpu_delay #(.W(32), .N(4)) pad (.clk, .en, .d(level[6][0]), .q(root));
  assign root_o=root;
  assign root_v=valid[27];
endmodule
