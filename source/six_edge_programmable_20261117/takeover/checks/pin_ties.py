# Design check (2026-11-23): in a Tiny Tapeout GDS, are uio_oe[*] and uio_out[*] tied to VGND by metal,
# and is every other pin on a net of its own? The circuit netlist has no such pins, so the layout-against-circuit
# comparison cannot see them; if uio_oe floated, the pad could drive against the board.
# usage: ~/.local/opt/klayout-py/bin/python checks/pin_ties.py <gds>     (metal connectivity only, about a minute)
import sys, collections
import klayout.db as kdb
ly = kdb.Layout(); ly.read(sys.argv[1])
top = ly.top_cell()
print("top:", top.name, "dbu", ly.dbu)
# where are the pin labels?
labels = collections.defaultdict(list)
for li in ly.layer_indexes():
    info = ly.get_info(li)
    for s in top.shapes(li).each():
        if s.is_text():
            labels[(info.layer, info.datatype)].append((s.text.string, s.text.x*ly.dbu, s.text.y*ly.dbu))
for k, v in sorted(labels.items()):
    names = sorted({n for n, _, _ in v})
    print("text layer", k, len(v), "labels; e.g.", names[:6])
l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))
def L(l, d, name): return l2n.make_layer(ly.layer(l, d), name)
li1 = L(67, 20, "li1"); mcon = L(67, 44, "mcon"); m1 = L(68, 20, "m1"); via = L(68, 44, "via")
m2 = L(69, 20, "m2"); via2 = L(69, 44, "via2"); m3 = L(70, 20, "m3"); via3 = L(70, 44, "via3")
m4 = L(71, 20, "m4"); via4 = L(71, 44, "via4"); m5 = L(72, 20, "m5")
stack = [li1, mcon, m1, via, m2, via2, m3, via3, m4, via4, m5]
for x in stack: l2n.connect(x)
for a, b in zip(stack[:-1], stack[1:]): l2n.connect(a, b)
# labels: every text layer that exists for a metal is attached to that metal's drawing layer
for (l, metal) in [(67, li1), (68, m1), (69, m2), (70, m3), (71, m4), (72, m5)]:
    for d in (5, 16):
        if (l, d) in labels:
            t = l2n.make_text_layer(ly.layer(l, d), f"t{l}_{d}")
            l2n.connect(metal, t)
l2n.extract_netlist()
nl = l2n.netlist()
c = nl.circuit_by_name(top.name)
bynet = {}
for n in c.each_net():
    nm = n.expanded_name()
    for part in nm.split(","):
        bynet[part] = nm
want = [f"uio_oe[{i}]" for i in range(8)] + [f"uio_out[{i}]" for i in range(8)]
bad = 0
for w in want:
    nm = bynet.get(w)
    ok = nm is not None and "VGND" in nm.split(",")
    bad += (not ok)
    print(f"{w:12s} net: {('(no such label)' if nm is None else nm[:90])}  -> {'tied to VGND' if ok else 'NOT TIED TO VGND'}")
for w in ["VGND", "VDPWR", "ua[0]", "ua[1]", "ua[2]", "uo_out[0]", "ui_in[0]", "uio_in[0]", "uio_in[7]", "ena", "clk", "rst_n"]:
    nm = bynet.get(w); print(f"{w:12s} net: {('(no such label)' if nm is None else nm[:140])}")
multi = sorted({nm for nm in bynet.values() if "," in nm and "VGND" not in nm.split(",")})
print("nets carrying more than one pin label, other than ground:", multi if multi else "none")
alone = [w for w in bynet if "," not in bynet[w]]
print("pins on a net of their own:", len(alone), "of", len(bynet), "labels")
print("RESULT:", "all sixteen tied to VGND" if bad == 0 else f"{bad} of 16 NOT tied", "|", "no two other pins share a net" if not multi else "PINS SHORTED TOGETHER")
