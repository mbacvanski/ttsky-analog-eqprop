"""Apply the four M2 etch interruptions and remove the isolated M2 polygon."""
import json
import sys
from pathlib import Path

import klayout.db as db

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strap_patch import LD, apply, save, sha

BASE = '99d4968e8f2fe1e137502fbeb3b3280674488797bcfea636f0d883d5e59225d1'
PATCH = 'c5cd7d5f8e497205fa33307e735b8a35bd2932d170834f08aef683f37afbf358'


def main(src, dst, record, patch):
    gsha = sha(src.read_bytes())
    raw = patch.read_bytes()
    if gsha != BASE or sha(raw) != PATCH:
        raise ValueError('antenna patch requires the pinned lock4_r die and patch file')
    data = json.loads(raw)
    ly = db.Layout()
    ly.read(str(src))
    top = ly.top_cell()
    m2 = ly.layer(*LD['met2'])
    rec = dict(base='lock4_r', input_gds_sha256=gsha, patch_sha256=PATCH, removed=[], added=[])
    for name, box in (data['cut'] | {'scrap': data['remove_scrap']}).items():
        window = db.DBox(*box).to_itype(ly.dbu)
        region = db.Region(window)
        hits = [s for s in top.shapes(m2).each_touching(window)
                if not (db.Region(s.polygon) & region).is_empty()]
        if len(hits) != 1:
            raise ValueError(f'{name}: expected exactly one top-level M2 shape crossing the window')
        shape = hits[0]
        old = db.Region(shape.polygon)
        rest = old - region
        if name == 'scrap':
            if not rest.is_empty() or old.bbox() != window:
                raise ValueError('scrap is not confined to its exact window')
            for via in ('via', 'via2'):
                vias = db.Region(top.begin_shapes_rec(ly.layer(*LD[via])))
                if not vias.interacting(old).is_empty():
                    raise ValueError(f'scrap touches {via}')
        elif rest.count() != 2:
            raise ValueError(f'{name}: the window does not split the wire into two pieces')
        rec['removed'].append(dict(group=name, layer='met2', window_um=box,
                                   removed_polygon_dbu=str(old & region)))
        shape.delete()
        top.shapes(m2).insert(rest)
    apply(ly, top, {}, data['add'], rec, patch.name)
    save(ly, top, dst)
    rec['output_gds_sha256'] = sha(dst.read_bytes())
    record.write_text(json.dumps(rec, indent=1) + '\n')
    print(rec['output_gds_sha256'])


if __name__ == '__main__':
    main(*map(Path, sys.argv[1:]))
