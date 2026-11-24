"""The generator devices of the chip strand's cells (PDK generators of Magic, as the accepted flow's devices.py).

Sizes are the netlist's (circuit/v4_netlist.py, sheets). The native NMOS, nfet_03v3_nvt, is new to this flow.
A unit strip is 133.3 kohm of the 0.35 um high-resistance polysilicon: by the accepted formula of pdk_rbias2 (two strips
in series, each half the value) two legs of 11.56 um; the DAC edge's third unit, 122.3 kohm, two legs of 10.60 um.
"""
L_LEG = 11.56        # 0.01 * floor(((133333 / 2 - 587.80457) * 0.35 / 2000) / 0.01 + 0.5)
L_LEG_DAC = 10.60    # the same for 122333 ohm

NVT, RX = "sky130_fd_pr__nfet_03v3_nvt", "sky130_fd_pr__res_xhigh_po_0p35"
DEVICES = {
    # sizing trials: the generator's own ring (guard 1) against the bare device (guard 0)
    "t_sw4_ring": (NVT, dict(w=4, l=0.5, nf=1)),
    "t_sw4": (NVT, dict(w=4, l=0.5, nf=1, guard=0)),
    "t_sw4x3": (NVT, dict(w=4, l=0.5, nf=3, guard=0)),
    "t_sw4x3_ring": (NVT, dict(w=4, l=0.5, nf=3)),
    "t_cl1": (NVT, dict(w=1, l=0.5, nf=1, guard=0)),
    "t_unit_ring": (RX, dict(w=0.35, l=L_LEG, nx=2)),
    "t_unit": (RX, dict(w=0.35, l=L_LEG, nx=2, guard=0)),
    "t_unit6": (RX, dict(w=0.35, l=L_LEG, nx=6, guard=0)),
    "t_unit8_ring": (RX, dict(w=0.35, l=L_LEG, nx=8)),
    "t_tgn8": ("sky130_fd_pr__nfet_01v8", dict(w=2, l=0.15, nf=8, guard=0)),
    "t_tgp8": ("sky130_fd_pr__pfet_01v8", dict(w=4, l=0.15, nf=8, guard=0)),
    "t_tgn8_ring": ("sky130_fd_pr__nfet_01v8", dict(w=2, l=0.15, nf=8)),
    "t_tgp8_ring": ("sky130_fd_pr__pfet_01v8", dict(w=4, l=0.15, nf=8)),
}

# ---- the devices the cells are made of (no ring of their own: each cell draws one shared ground ring)
DEVICES.update({
    "sw4": (NVT, dict(w=4, l=0.5, nf=1, guard=0)),              # isolation and helper switch, DAC edge's switch at z
    "sw8": (NVT, dict(w=4, l=0.5, nf=2, guard=0)),              # a hidden neuron's bus switch and damping switch: two 4 um fingers on the wire's one diffusion
    "sw12": (NVT, dict(w=4, l=0.5, nf=3, guard=0)),             # the output neuron's helper switches: three 4 um fingers
    "cl1": (NVT, dict(w=1, l=0.5, nf=1, guard=0)),              # the clamp of nd in the DAC edge's gate cell
    "strips4": (RX, dict(w=0.35, l=L_LEG, nx=4, guard=0)),
    "strips8": (RX, dict(w=0.35, l=L_LEG, nx=8, guard=0)),      # six legs and a dummy strip at each end
    "strips10": (RX, dict(w=0.35, l=L_LEG, nx=10, guard=0)),    # a hidden neuron's east cell: six legs, the damping unit's two, a dummy at each end
    # the DAC edge's gate: 8 units of the accepted transmission gate (NMOS 2 / 0.15 and PMOS 4 / 0.15, eight fingers each,
    # each in the generator's own ring), and the clamp of nd in its own ring
    "tg8n": ("sky130_fd_pr__nfet_01v8", dict(w=2, l=0.15, nf=8, conn_gates=1)),
    "tg8p": ("sky130_fd_pr__pfet_01v8", dict(w=4, l=0.15, nf=8, conn_gates=1)),
    "cl1r": (NVT, dict(w=1, l=0.5, nf=1)),
    "strips9": (RX, dict(w=0.35, l=L_LEG, nx=9, guard=0)),      # the output neuron's east cell: eight legs and the lower dummy
    "strips3s": (RX, dict(w=0.35, l=L_LEG_DAC, nx=3, guard=0)), # ... and above them the upper dummy and the DAC edge's two short legs
})
