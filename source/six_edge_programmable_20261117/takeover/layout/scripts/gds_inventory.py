"""Inventory of a GDS: top cell, cell count, top-level instances (name, cell, bbox um), labels on the top cell.
  KPY gds_inventory.py GDS OUT.json"""
import sys, json, collections
import klayout.db as db
gds, out = sys.argv[1], sys.argv[2]
ly = db.Layout(); ly.read(gds)
tops = [c.name for c in ly.top_cells()]
top = ly.top_cell(); dbu = ly.dbu
insts = []
for i in top.each_inst():
    c = i.cell
    b = i.bbox()
    props = {k: v for k, v in i.properties().items()} if hasattr(i, "properties") else {}
    insts.append(dict(cell=c.name, trans=str(i.trans), bbox_um=[round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)],
                      name=str(props.get(61, "")) if props else ""))
labels = collections.defaultdict(list)
for li in ly.layer_indexes():
    info = ly.get_info(li)
    for s in top.shapes(li).each():
        if s.is_text():
            labels[f"{info.layer}/{info.datatype}"].append((s.text.string, round(s.text.x * dbu, 3), round(s.text.y * dbu, 3)))
cells = sorted(c.name for c in ly.each_cell())
res = dict(gds=gds, top_cells=tops, dbu=dbu, bbox_um=[round(v * dbu, 3) for v in (top.bbox().left, top.bbox().bottom, top.bbox().right, top.bbox().top)],
           cells=len(cells), cell_names=cells, top_instances=len(insts), instances=insts,
           top_label_counts={k: len(v) for k, v in labels.items()}, top_labels=labels)
open(out, "w").write(json.dumps(res, indent=1) + "\n")
print("top", tops, "cells", len(cells), "top instances", len(insts), "bbox", res["bbox_um"])
print("label layers", res["top_label_counts"])
for x in insts: print("  ", x["cell"], x["bbox_um"], x["trans"], x["name"])
