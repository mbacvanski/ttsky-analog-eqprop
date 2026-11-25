"""Portable release records for this stage. Keep Magic's original files in the build."""
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'drawn'))
from account_flat import ext_caps, parse_spice


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def ordered_caps(raw, spice):
    """Order equivalent two-terminal capacitor records. Preserve all other bytes."""
    lines = raw.splitlines(keepends=True)
    pattern = (rb'C([0-9]+) (\S+) (\S+) (\S+)([ \t]*(?:;[^\n]*)?)\n' if spice else
               rb'cap ("[^"]*") ("[^"]*") (\S+)\n')
    ids, cards, slots = [], [], []
    for i, line in enumerate(lines):
        if not (re.match(rb'C[0-9]+\s', line) if spice else line.startswith(b'cap ')):
            continue
        match = re.fullmatch(pattern, line)
        if match is None:
            raise ValueError(f'unrecognized capacitor record {line!r}')
        fields = list(match.groups())
        if spice:
            ids.append(int(fields.pop(0)))
        a, b, value, *comment = fields
        cards.append(b' '.join([*sorted((a,b)), value]) + b''.join(comment))
        slots.append(i)
    if not slots or slots != list(range(slots[0], slots[-1]+1)):
        raise ValueError('expected one contiguous capacitor block')
    if spice and sorted(ids) != list(range(len(ids))):
        raise ValueError('SPICE capacitor instance names are not consecutive C0…Cn')
    for index, (slot, card) in enumerate(zip(slots, sorted(cards))):
        prefix = f'C{index} '.encode() if spice else b'cap '
        lines[slot] = prefix + card + b'\n'
    return b''.join(lines), len(slots)


def check_pairs(src, dest, audit):
    """Read back the two formats, then break ties in the six largest errors by node name."""
    expected, aliases, _ = ext_caps(dest/'native_flat.ext')
    ports, devices, caps = parse_spice(dest/'raw.spice')
    original, original_aliases, _ = ext_caps(src/'native_flat.ext')
    if original != expected or original_aliases != aliases or (ports, devices, caps) != parse_spice(src/'raw.spice'):
        raise ValueError('reordering altered extracted capacitances, devices or pins')
    observed = defaultdict(float)
    for (a, b), value in caps.items():
        a, b = aliases.get(a, a), aliases.get(b, b)
        if a != b:
            observed[tuple(sorted((a, b)))] += value
    errors = {pair: observed[pair] - expected.get(pair, 0.) for pair in expected.keys() | observed.keys()}
    if (len(errors) != audit['checked_pairs'] or sum(abs(v) > .012 for v in errors.values()) != audit['pairs_over_0p012fF']
            or not math.isclose(max(map(abs, errors.values())), audit['maximum_absolute_error_fF'], abs_tol=1e-12)):
        raise ValueError('extraction audit differs after readback')
    ordered = sorted(errors, key=lambda p: (-abs(errors[p]), p))
    audit['largest_discrepancies_fF'] = [dict(nodes=list(p), error_fF=errors[p]) for p in ordered[:6]]


def release(folder, stem):
    src = folder / (stem + '_pex')
    dest = folder / 'release_records'
    dest.mkdir(exist_ok=True)
    manifest = json.loads((src/'manifest.json').read_bytes())
    formats = {}
    for name, field in (('native_flat.ext','ext_sha256'), ('raw.spice','raw_spice_sha256')):
        original = (src/name).read_bytes()
        if digest(original) != manifest[field]:
            raise ValueError(f'raw extraction hash mismatch for {name}')
        stable, count = ordered_caps(original, name.endswith('.spice'))
        (dest/name).write_bytes(stable)
        manifest[field] = digest(stable)
        formats[name] = count
    check_pairs(src, dest, manifest['extraction_vs_ext'])
    manifest['release_capacitor_order'] = dict(cards=formats, method='Sort capacitor records and their two endpoints; '
        'retain every value and comment. Give sorted SPICE capacitor cards consecutive C identifiers. '
        'All other bytes are original. Native files and their original manifest are in the build PEX directory.')
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    macros = json.loads((folder/(stem+'_macro_check.json')).read_bytes())
    amp_ref = Path('v5_reference/amp_ref')
    if Path(macros['amp_ref']).parts[-2:] != amp_ref.parts:
        raise ValueError('unexpected amplifier reference for lock5_r')
    for name, record in macros['macros'].items():
        if digest((folder/amp_ref/record['file']).read_bytes()) != record['sha256']:
            raise ValueError(f'amplifier reference changed: {name}')
    macros['amp_ref'] = str(amp_ref)
    (dest/'macro_check.json').write_text(json.dumps(macros,indent=1)+'\n')


if __name__ == '__main__':
    release(Path(sys.argv[1]), sys.argv[2])
