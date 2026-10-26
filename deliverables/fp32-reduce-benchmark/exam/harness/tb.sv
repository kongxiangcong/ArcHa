module tb;
  logic clk=0, rst, en, cap, row_last;
  logic [7:0] sub;
  logic [255:0] pacc;
  wire [31:0] root, root_o;
  wire root_v;
  reduce64 dut(.*);
  integer fd, rc, er, ee, ec, el, es, ev, count=0;
  logic [255:0] ep;
  logic [31:0] expected, prev_root, prev_o;
  logic prev_v;
  bit have_prev=0;
  string vectors;
  initial begin
    if (!$value$plusargs("vectors=%s", vectors)) $fatal(1,"vectors missing");
    fd=$fopen(vectors,"r");
    if (!fd) $fatal(1,"cannot open vectors");
    while (!$feof(fd)) begin
      rc=$fscanf(fd,"%d %d %d %d %d %h %d %h\n",er,ee,ec,el,es,ep,ev,expected);
      if (rc!=8) $fatal(1,"malformed vector");
      clk=0; rst=1'(er); en=1'(ee); cap=1'(ec); row_last=1'(el); sub=8'(es); pacc=ep;
      #5; clk=1; #5;
      if (root_v !== 1'(ev)) $fatal(1,"valid mismatch cycle %0d",count);
      if (ev && (root !== expected || root_o !== expected))
        $fatal(1,"value mismatch cycle %0d got %h/%h expected %h",count,root,root_o,expected);
      if (have_prev && !en && !rst && (root !== prev_root || root_o !== prev_o || root_v !== prev_v))
        $fatal(1,"pause changed output cycle %0d",count);
      prev_root=root; prev_o=root_o; prev_v=root_v; have_prev=1; count++;
    end
    $fclose(fd);
    $display("FR64_PASS cycles=%0d",count); $finish;
  end
endmodule
