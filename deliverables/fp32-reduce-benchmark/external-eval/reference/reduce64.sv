// Evaluation-only adapter. Never distribute to contestants.
module reduce64 (
  input logic clk, rst, en, cap, row_last,
  input logic [7:0] sub,
  input logic [255:0] pacc,
  output logic [31:0] root, root_o,
  output logic root_v
);
  wire [31:0] words [8];
  for (genvar k=0;k<8;k++) assign words[k]=pacc[32*k +: 32];
  otpu_vtree #(.LANES(8),.LA(4)) ref_tree
    (.clk,.rst,.en,.cap,.row_last,.sub,.pacc(words),.root,.root_o,.root_v);
endmodule
