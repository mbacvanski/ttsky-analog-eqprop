"""Board names of the 37 distinct terminals in the flat Tiny Tapeout extraction."""


def board_names(ports):
    aliases=dict(clk="vss",ena="vdd",rst_n="vdd",VDPWR="vdd",VGND="vss")
    primary="bit_a bit_b reset hold_in ref_reset obs_sel0 obs_sel1 obs_sel2".split()
    control="ext_en1 ext_en2 obs2_sel0 obs2_sel1 bias_prog write res_sel weight_prog".split()
    for i in range(8):
        aliases[f"ui_in[{i}]"]=primary[i]
        aliases[f"uio_in[{i}]"]=control[i]
        aliases[f"uo_out[{i}]"]=f"uo_out{i}"
    analog=["pad","ext_bias","pad2",*[f"unused_analog_{i}" for i in range(3,8)]]
    aliases.update({f"ua[{i}]":name for i,name in enumerate(analog)})
    assert len(ports)==len(set(ports))==37 and set(aliases)==set(ports)
    return aliases
