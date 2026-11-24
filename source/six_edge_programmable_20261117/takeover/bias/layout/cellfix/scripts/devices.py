"""The generator devices of the cells strand's cells (the PDK's Magic generators, as the accepted flow's devices.py).
Sizes are the circuit strand's (circuit/v4_netlist.py). guard=0: each cell draws its own taps and rings."""
LVT, P18, N18 = "sky130_fd_pr__pfet_01v8_lvt", "sky130_fd_pr__pfet_01v8", "sky130_fd_pr__nfet_01v8"
HV, NVT, MIM = "sky130_fd_pr__nfet_g5v0d10v5", "sky130_fd_pr__nfet_03v3_nvt", "sky130_fd_pr__cap_mim_m3_1"
RX = "sky130_fd_pr__res_xhigh_po_0p35"
G0 = dict(guard=0)
DEVICES = {
    # programmable resistors
    "lvt16": (LVT, dict(w=16, l=2, nf=1, **G0)),          # shunt chain: one of two
    "lvt16x2": (LVT, dict(w=16, l=2, nf=2, **G0)),        # the two in one diffusion (trial)
    "lvt4": (LVT, dict(w=4, l=2, nf=1, **G0)),            # bridge chain: one of four
    "lvt4x4": (LVT, dict(w=4, l=2, nf=4, **G0)),          # the four in one diffusion (trial)
    "lvt1": (LVT, dict(w=1, l=1, nf=1, **G0)),            # writer's PMOS at the gate
    "hv4": (HV, dict(w=0.42, l=4, nf=1, **G0)),           # writer's 5 V NMOS at the gate
    "hv4r": (HV, dict(w=0.42, l=4, nf=1)),                # the same in its own ring (trial)
    "n8": (N18, dict(w=0.42, l=8, nf=1, **G0)),           # hold of wm
    "tgn": (N18, dict(w=0.5, l=0.15, nf=1, **G0)),        # cd_tg_small
    "tgp": (P18, dict(w=1, l=0.15, nf=1, **G0)),
    "nvt1": (NVT, dict(w=1, l=0.5, nf=1, **G0)),          # well clamp, bus clamps
    "mim": (MIM, dict(w=10.99, l=10.99, nx=1, ny=1)),
    # bias word
    "lvt40": (LVT, dict(w=10, l=1, nf=4, **G0)),          # follower 40 / 1 as four fingers of 10 um (same bin as W = 40)
    "hv1": (HV, dict(w=0.42, l=1, nf=1, **G0)),
    "p44": (P18, dict(w=4, l=4, nf=1, **G0)),
    "p105": (P18, dict(w=1, l=0.5, nf=1, **G0)),
    "n42": (N18, dict(w=4, l=2, nf=1, **G0)),
    "n105": (N18, dict(w=1, l=0.5, nf=1, **G0)),
    "p205": (P18, dict(w=2, l=0.5, nf=1, **G0)),
    "hv8": (HV, dict(w=0.42, l=8, nf=1, **G0)),           # pull-down
}
# one-sided gate contacts for the cells as drawn (topc / botc of the PDK generator)
T1, B1 = dict(topc=1, botc=0), dict(topc=0, botc=1)
DEVICES.update({
    "lvt8x2t": (LVT, dict(w=8, l=2, nf=2, **G0, **T1)),    # shunt chain, west half (lying: contacts at its east end)
    "lvt8x2b": (LVT, dict(w=8, l=2, nf=2, **G0, **B1)),    # shunt chain, east half (lying: contacts at its west end)
    "lvt4x4b": (LVT, dict(w=4, l=2, nf=4, **G0, **B1)),    # bridge chain, contacts below
    "lvt1b": (LVT, dict(w=1, l=1, nf=1, **G0, **B1)),
    "lvt1t": (LVT, dict(w=1, l=1, nf=1, **G0, **T1)),
    "hv4t": (HV, dict(w=0.42, l=4, nf=1, **G0, **T1)),
    "hv4b": (HV, dict(w=0.42, l=4, nf=1, **G0, **B1)),
    "n8t": (N18, dict(w=0.42, l=8, nf=1, **G0, **T1)),
    "n8b": (N18, dict(w=0.42, l=8, nf=1, **G0, **B1)),
    "tgnt": (N18, dict(w=0.5, l=0.15, nf=1, **G0, **T1)),
    "tgnb": (N18, dict(w=0.5, l=0.15, nf=1, **G0, **B1)),
    "tgpt": (P18, dict(w=1, l=0.15, nf=1, **G0, **T1)),
    "tgpb": (P18, dict(w=1, l=0.15, nf=1, **G0, **B1)),
    "nvt1t": (NVT, dict(w=1, l=0.5, nf=1, **G0, **T1)),
    "nvt1b": (NVT, dict(w=1, l=0.5, nf=1, **G0, **B1)),
})
# the bias block
DEVICES.update({
    "lvt40t": (LVT, dict(w=10, l=1, nf=4, **G0, **T1)),   # follower 40/1: four 10 um fingers, gates contacted at one end
    "p205t": (P18, dict(w=2, l=0.5, nf=1, **G0, **T1)), "p105t": (P18, dict(w=1, l=0.5, nf=1, **G0, **T1)),
    "n105t": (N18, dict(w=1, l=0.5, nf=1, **G0, **T1)), "n105b": (N18, dict(w=1, l=0.5, nf=1, **G0, **B1)),
    "hv1t": (HV, dict(w=0.42, l=1, nf=1, **G0, **T1)), "hv1b": (HV, dict(w=0.42, l=1, nf=1, **G0, **B1)),
    "hv8t": (HV, dict(w=0.42, l=8, nf=1, **G0, **T1)),
    "n42x6": (N18, dict(w=4, l=2, nf=6, **G0, **T1)), "n42x5": (N18, dict(w=4, l=2, nf=5, **G0, **T1)),
    "p44t": (P18, dict(w=4, l=4, nf=1, **G0, **T1)),
    "rref": (RX, dict(w=0.35, l=24.92, nx=2, guard=0)),   # pdk_rbias2 286 kohm: two legs of 24.92 um
})
DEVICES.update({"p205b": (P18, dict(w=2, l=0.5, nf=1, **G0, **B1))})
DEVICES.update({"p44b": (P18, dict(w=4, l=4, nf=1, **G0, **B1)), "p105b": (P18, dict(w=1, l=0.5, nf=1, **G0, **B1)),
                "nvt_dummy": (NVT, dict(w=1, l=0.5, nf=1, **G0, **T1))})
# the bias block at the circuit strand's sizes of 2026-11-15 afternoon: mirror units NMOS 2/1, PMOS 2/2; pw4_tg NMOS 4/0.5
# (two 2 um fingers) and PMOS 8/0.5 (four 2 um fingers)
DEVICES.update({
    "p22t": (P18, dict(w=2, l=2, nf=1, **G0, **T1)), "p22b": (P18, dict(w=2, l=2, nf=1, **G0, **B1)),
    "n21x6": (N18, dict(w=2, l=1, nf=6, **G0, **T1)), "n21x5": (N18, dict(w=2, l=1, nf=5, **G0, **T1)),
    "tgn4t": (N18, dict(w=2, l=0.5, nf=2, **G0, **T1)), "tgn4b": (N18, dict(w=2, l=0.5, nf=2, **G0, **B1)),
    "tgp8t": (P18, dict(w=2, l=0.5, nf=4, **G0, **T1)), "tgp8b": (P18, dict(w=2, l=0.5, nf=4, **G0, **B1)),
})
DEVICES.update({   # the DAC-line gate's devices, drawn lying (gate contact at one end): PMOS 8/0.5 as two of these in parallel
    "tgp4l": (P18, dict(w=4, l=0.5, nf=1, **G0, **T1)), "tgn4l": (N18, dict(w=4, l=0.5, nf=1, **G0, **T1)),
})
