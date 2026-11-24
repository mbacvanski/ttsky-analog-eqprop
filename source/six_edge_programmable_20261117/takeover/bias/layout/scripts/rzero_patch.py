"""Stage after the strap patch: the REF buffer's zero resistor ar4_rzero (sky130_fd_pr__res_xhigh_po_1p41, W 1.41) from
a 0.54 um body to 0.70 um, so that it meets SkyWater's mask-generation rules (resistor body 0.66 um or more,
MR_poly.LEN.2; contact bars 0.64 um or more end to end). Netlist version 5 (rzero/make_variant_v5.py) has the same
change: XBUF3 RZERO=1k -> 1225, L 0.54 -> 0.70.

Every shape of cell ar4_rzero (it has one instance and no subcells) is replaced by the shapes of the checked cell file:
inputs/ar4_rzero_l070.gds, made by scripts/rzero_cell.py with the PDK generator call the amp generator uses
(magic::gencell sky130::sky130_fd_pr__res_xhigh_po_1p41 w 1.41 l 0.70). The cell keeps its name and its instance
(ref4_core, r270 at 36.9, 9.6); no other cell, shape, label or placement is touched. The resistor grows along its
current by 0.08 um at each end; across, nothing changes. The two wires that reach it stay on its pads: the gain1 riser
on R2's pad and the comp via stack on R1's.

The input GDS must be lock3_r or lock3_h (by sha256). The output is saved with the base flow's timestamp-free writer, so the
rebuild gives the same bytes.

  KPY rzero_patch.py IN.gds OUT.gds RECORD.json CELL.gds
"""
import hashlib
import json
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / 'layout'))
from prepare_split import save  # noqa: E402  the base flow's timestamp-free GDS writer

CELL = 'ar4_rzero'
# the checked cell file (sha256 of its bytes)
CELLS = {'899f730f62119604048d3a520257c58da7cb323c0a4cd9c001352aac3cfaaf6b':
         dict(file='inputs/ar4_rzero_l070.gds', generator='sky130_fd_pr__res_xhigh_po_1p41', w=1.41, l=0.70)}
# the layouts it applies to: sha256 of the GDS the stage starts from
BASES = {'88594fa1019f750dd60a50459e5258d6304578ff0521c266214a11d6b05bce0f': 'lock3_r',
         'a3429ad33c95d3f7399f04177010bcc428f7f739e46039d3259690b7e000ad53': 'lock3_h (not built unless asked)'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def instances(ly, cell):
    """Placements of `cell` in the whole layout (arrays counted by their size), with their parent and transformation."""
    out = []
    for parent_index in cell.each_parent_cell():
        parent = ly.cell(parent_index)
        for inst in parent.each_inst():
            if inst.cell_index == cell.cell_index():
                out.extend([(parent.name, str(inst.dcplx_trans))] * inst.size())
    return out


def layers(ly, cell):
    """{(layer, datatype): (shape count, bbox in um, merged region)} of the cell's own shapes (texts apart)."""
    out = {}
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        shapes = [s for s in cell.shapes(li).each() if not s.is_text()]
        if shapes:
            r = db.Region()
            for s in shapes:
                r.insert(s.polygon)
            bb = r.bbox().to_dtype(ly.dbu)
            out[(info.layer, info.datatype)] = (len(shapes), [round(v, 3) for v in (bb.left, bb.bottom, bb.right, bb.top)],
                                                r.merged())
    return out


def labels(ly, cell):
    out = []
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        for s in cell.shapes(li).each():
            if s.is_text():
                out.append(dict(gds=f'{info.layer}/{info.datatype}', text=s.text.string,
                                at_um=[round(s.text.x * ly.dbu, 3), round(s.text.y * ly.dbu, 3)]))
    return sorted(out, key=lambda t: (t['text'], t['gds']))


def main(src, dst, record, cell_gds):
    gsha = sha(Path(src).read_bytes())
    base = BASES.get(gsha)
    if base is None:
        raise SystemExit(f'input GDS {gsha} is neither lock3_r nor lock3_h')
    csha = sha(Path(cell_gds).read_bytes())
    if csha not in CELLS:
        raise SystemExit(f'{cell_gds}: {csha} is not the checked cell file')
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell()
    cell = ly.cell(CELL)
    assert cell is not None and cell.child_cells() == 0, CELL
    places = instances(ly, cell)
    assert len(places) == 1, places
    new = db.Layout(); new.read(str(cell_gds))
    assert new.dbu == ly.dbu, (new.dbu, ly.dbu)
    tops = new.top_cells()
    assert len(tops) == 1 and tops[0].name == CELL and tops[0].child_cells() == 0, [t.name for t in tops]
    nc = tops[0]
    before, labels_before = layers(ly, cell), labels(ly, cell)
    cell.clear_shapes()
    for li in new.layer_indexes():
        info = new.get_info(li)
        if not nc.shapes(li).is_empty():
            cell.shapes(ly.layer(info.layer, info.datatype)).insert(nc.shapes(li))
    after, want = layers(ly, cell), layers(new, nc)
    assert set(after) == set(want) and all((after[k][2] ^ want[k][2]).is_empty() for k in want), 'copy differs'
    assert labels(ly, cell) == labels(new, nc)
    save(ly, top, dst)
    rec = dict(input_gds_sha256=gsha, base=base, cell=CELL, instance=dict(parent=places[0][0], trans=places[0][1]),
               cell_file=dict(CELLS[csha], given=Path(cell_gds).name, sha256=csha),
               layers={f'{k[0]}/{k[1]}': dict(shapes_before=before[k][0] if k in before else 0,
                                              shapes_after=after[k][0] if k in after else 0,
                                              bbox_before_um=before[k][1] if k in before else None,
                                              bbox_after_um=after[k][1] if k in after else None)
                       for k in sorted(set(before) | set(after))},
               labels_before=labels_before, labels_after=labels(ly, cell))
    rec['output_gds_sha256'] = sha(Path(dst).read_bytes())
    Path(record).write_text(json.dumps(rec, indent=1) + '\n')
    print(f"{base}: {CELL} replaced by {Path(cell_gds).name} (l {CELLS[csha]['l']}) -> {dst} ({rec['output_gds_sha256'][:16]})")


if __name__ == '__main__':
    main(*sys.argv[1:])
