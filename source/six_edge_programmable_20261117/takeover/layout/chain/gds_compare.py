"""Compare two GDS streams (plain or gzipped): bytes, GDS records ignoring their order, cells and instances,
and the merged geometry and labels of every layer of the flattened top cell.

  ~/.local/opt/klayout-py/bin/python -I gds_compare.py OBTAINED.gds STORED.gds[.gz] [OUT.json]

Prints one JSON object; replay.py calls this only for an output whose bytes differ from its stored archive."""
import gzip
import hashlib
import json
import struct
import sys
from collections import Counter

import klayout.db as db


def raw(path):
    data = open(path, 'rb').read()
    return gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data


def records(data):
    """Library header, {structure name: (header records, Counter of element byte strings)}, tail.
    BGNSTR carries dates; it is kept out of the comparison of structure headers."""
    out, i, head, name, element, tail_start = {}, 0, None, None, None, None
    first = None
    while i < len(data):
        size, kind = struct.unpack_from('>HH', data, i)
        if size < 4:
            raise ValueError('Corrupt GDS record at %d' % i)
        body = data[i:i + size]
        if kind == 0x0502:                      # BGNSTR
            first = i if first is None else first
            head, element = [], None
        elif kind == 0x0606:                    # STRNAME
            name = data[i + 4:i + size].rstrip(b'\0').decode()
            head.append(body)
            out[name] = (head, Counter())
        elif kind in (0x0800, 0x0900, 0x0a00, 0x0b00, 0x0c00, 0x2d00):   # element start
            element = [body]
        elif kind == 0x1100:                    # ENDEL
            element.append(body)
            out[name][1][b''.join(element)] += 1
            element = None
        elif kind == 0x0700:                    # ENDSTR
            tail_start = i + size
        elif element is not None:
            element.append(body)
        elif head is not None and name is not None:
            head.append(body)
        i += size
    return data[:first], out, data[tail_start:]


def compare(a_path, b_path):
    a, b = raw(a_path), raw(b_path)
    result = dict(obtained_sha256=hashlib.sha256(a).hexdigest(), stored_sha256=hashlib.sha256(b).hexdigest())
    result['same_bytes'] = a == b
    if a == b:
        return result
    pa, ca, ta = records(a)
    pb, cb, tb = records(b)
    result['same_library_header'] = pa[:4] == pb[:4]
    result['same_structure_names'] = set(ca) == set(cb)
    differing = sorted(n for n in set(ca) | set(cb) if n not in ca or n not in cb or ca[n][1] != cb[n][1])
    result['structures_with_different_element_multisets'] = differing[:50]
    result['same_records_ignoring_order'] = result['same_structure_names'] and not differing
    result['same_structure_order'] = list(ca) == list(cb)
    la, lb = db.Layout(), db.Layout()
    la.read_bytes(a)
    lb.read_bytes(b)
    ta_, tb_ = la.top_cell(), lb.top_cell()
    result['top_cells'] = [ta_.name, tb_.name]

    def instances(top):
        return sorted((i.cell.name, i.trans.to_s(), i.na, i.nb) for i in top.each_inst())
    ia, ib = instances(ta_), instances(tb_)
    result['top_instances'] = dict(obtained=len(ia), stored=len(ib),
                                   only_obtained=[list(x) for x in sorted(set(ia) - set(ib))][:20],
                                   only_stored=[list(x) for x in sorted(set(ib) - set(ia))][:20])
    infos = {(la.get_info(i).layer, la.get_info(i).datatype) for i in la.layer_indexes()} | \
            {(lb.get_info(i).layer, lb.get_info(i).datatype) for i in lb.layer_indexes()}
    layers = {}
    for layer, purpose in sorted(infos):
        ra, rb = db.Region(), db.Region()
        tx = []
        for lay, top, reg in ((la, ta_, ra), (lb, tb_, rb)):
            idx = lay.find_layer(layer, purpose)
            labels = Counter()
            if idx is not None:
                reg.insert(top.begin_shapes_rec(idx))
                it = top.begin_shapes_rec(idx)
                while not it.at_end():
                    s = it.shape()
                    if s.is_text():
                        t = s.text.transformed(it.trans())
                        labels[(t.string, t.x, t.y)] += 1
                    it.next()
            tx.append(labels)
        ra.merge(); rb.merge()
        xor = ra ^ rb
        entry = dict(obtained_area_um2=ra.area() / 1e6, stored_area_um2=rb.area() / 1e6,
                     xor_area_um2=xor.area() / 1e6, same_labels=tx[0] == tx[1])
        if entry['xor_area_um2'] or not entry['same_labels']:
            entry['xor_bbox_um'] = [v / 1000 for v in (xor.bbox().left, xor.bbox().bottom, xor.bbox().right, xor.bbox().top)] if not xor.is_empty() else None
            layers[f'{layer}/{purpose}'] = entry
    result['layers_compared'] = len(infos)
    result['layers_with_differences'] = layers
    result['same_geometry_and_labels_on_every_layer'] = not layers
    return result


if __name__ == '__main__':
    report = compare(sys.argv[1], sys.argv[2])
    text = json.dumps(report, indent=1)
    if len(sys.argv) > 3:
        open(sys.argv[3], 'w').write(text + '\n')
    print(text)
