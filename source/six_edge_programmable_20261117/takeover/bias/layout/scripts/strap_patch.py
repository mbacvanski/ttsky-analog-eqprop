"""Stage after the well patch: the XPROG ground strap (variant D), applied as supply_patch.py applies the supply patch.
Two inputs, applied in this order, each one of the checked files below (sha256 of its bytes):
  1. the bias layout's block file (inputs/strap_block_d.json):
       {"format": ..., "layouts": [...],
        "remove": {group: [[layer, x0, y0, x1, y1, cell, note], ...]},   an existing box in `cell`, equal to the rectangle
        "add":    {group: [[layer, x0, y0, x1, y1, note], ...]}}         rectangles added to the top cell (chip um)
     every "remove" must match exactly one box of that layer in that cell, and the cell must have exactly one instance
     in the die; removals first, then additions;
  2. the layout stream's strap file, additions only, in local_patch.json's form: {group: [[layer, x0, y0, x1, y1, note]]}.
The input GDS must be lock2_h or lock2_r (by sha256). The output is saved with the base flow's timestamp-free writer, so the
rebuild gives the same bytes.

  KPY strap_patch.py IN.gds OUT.gds RECORD.json BLOCK.json STRAP.json
"""
import hashlib
import json
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / 'layout'))
from prepare_split import save  # noqa: E402  the base flow's timestamp-free GDS writer

# the checked input files (sha256 of the file's bytes) and their role
PATCHES = {
    '39f92f58e37dbacc986d309dce97b115b7267bab29110b72c95406df69676d47': dict(role='block', file='inputs/strap_block_d.json'),
    # copy of takeover/layout/runs/patch/xprog_strap.json, final 24 Nov (layout stream)
    'a01414b9f854331a3a87db45b87f597be782fe85d7fcbacb78c8eb077f10e88b': dict(role='strap', file='inputs/xprog_strap.json'),
}
# the layouts the strap is drawn for: sha256 of the GDS the stage starts from
BASES = {'e88d271c60bf05f3528df3860685abaad8993b4e74f1182c9e6206ace92170b4': 'lock2_h',
         '991393f67b6c14d99276e2e22df2c0a89817975409b56680e9ce1b8c809273b1': 'lock2_r'}
LD = {'met1': (68, 20), 'via': (68, 44), 'met2': (69, 20), 'via2': (69, 44), 'met3': (70, 20), 'via3': (70, 44),
      'met4': (71, 20)}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def instances(ly, cell):
    """Number of placements of `cell` in the whole layout (arrays counted by their size)."""
    n = 0
    for parent_index in cell.each_parent_cell():
        parent = ly.cell(parent_index)
        for inst in parent.each_inst():
            if inst.cell_index == cell.cell_index():
                n += inst.size()
    return n


def main(src, dst, record, *patches):
    assert len(patches) == 2, 'give the block file and the strap file'
    gsha = sha(Path(src).read_bytes())
    base = BASES.get(gsha)
    if base is None:
        raise SystemExit(f'input GDS {gsha} is neither lock2_h nor lock2_r')
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell()
    rec = dict(input_gds_sha256=gsha, base=base, patches=[], removed=[], added=[])
    for k, patch in enumerate(patches):
        raw = Path(patch).read_bytes()
        psha = sha(raw)
        if psha not in PATCHES:
            raise SystemExit(f'{patch}: {psha} is not one of the checked files')
        assert PATCHES[psha]['role'] == ('block', 'strap')[k], (patch, PATCHES[psha])
        data = json.loads(raw)
        rec['patches'].append(dict(file=Path(patch).name, sha256=psha, role=PATCHES[psha]['role']))
        if PATCHES[psha]['role'] == 'block':
            if base not in data['layouts']:
                raise SystemExit(f'{patch} is not drawn for {base}')
            apply(ly, top, data.get('remove', {}), data['add'], rec, Path(patch).name)
        else:
            apply(ly, top, {}, data, rec, Path(patch).name)
    save(ly, top, dst)
    rec['output_gds_sha256'] = sha(Path(dst).read_bytes())
    Path(record).write_text(json.dumps(rec, indent=1) + '\n')
    print(f"{base}: {len(rec['removed'])} boxes removed, {len(rec['added'])} rectangles added -> {dst} "
          f"({rec['output_gds_sha256'][:16]})")


def apply(ly, top, remove, add, rec, source):
    for group, entries in remove.items():
        for lay, x0, y0, x1, y1, cname, note in entries:
            cell = ly.cell(cname)
            assert cell is not None, cname
            assert instances(ly, cell) == 1, (cname, instances(ly, cell))
            want = db.DBox(x0, y0, x1, y1).to_itype(ly.dbu)
            hits = [s for s in cell.shapes(ly.layer(*LD[lay])).each() if s.is_box() and s.box == want]
            others = [s for s in cell.shapes(ly.layer(*LD[lay])).each() if not s.is_box() and s.bbox() == want]
            assert len(hits) == 1 and not others, (group, lay, [x0, y0, x1, y1], cname, len(hits), len(others))
            cell.shapes(ly.layer(*LD[lay])).erase(hits[0])
            rec['removed'].append(dict(source=source, group=group, layer=lay, gds=f'{LD[lay][0]}/{LD[lay][1]}',
                                       box_um=[x0, y0, x1, y1], cell=cname, note=note))
    for group, entries in add.items():
        for lay, x0, y0, x1, y1, note in entries:
            top.shapes(ly.layer(*LD[lay])).insert(db.DBox(x0, y0, x1, y1))
            rec['added'].append(dict(source=source, group=group, layer=lay, gds=f'{LD[lay][0]}/{LD[lay][1]}',
                                     box_um=[x0, y0, x1, y1], note=note))


if __name__ == '__main__':
    main(*sys.argv[1:])
