"""Rebuild the bias variant from the repository's files into an empty folder and run the base flow's checks on it.

  python rebuild.py FOLDER W1 L1 W2 L2 [--schematic VARIANT.spice] [--expect GDS_SHA256]

Steps (each logged as FOLDER/NN_*.log), as the base flow's filter_reservoir_rebuild.py does them:
  00 bias_stage.py        free b1/b2, place, route                         -> chip.gds
  01 check_die.py chip    Magic full rule check, flat LVS + wrong-netlist control
  02 repair.py --fill     the base flow's same-net and minimum-area repair          -> chip_fill.gds
  03 check_die.py         the same checks on chip_fill
  with --patch: 04 supply_patch.py (the layout stream's local supply patch -> chip_lock.gds), 05 check_die.py chip_lock
  with --v4 V4.spice as well (second candidate, netlist version 4, on top of the lock build):
                 06 v4_stage.py (H1's bias network made H2's -> chip_v4.gds),
                 07 check_die.py as it stands on a copy (chip_v4_base_table: its dummy table still describes the old
                    H1 cells, so it reports property errors on four dummy strips; kept on record),
                 08 check_die_v4.py (check_die.py with the dummy table brought to the version-4 cells) on chip_v4
  with --wells WELL_PATCH.json: the n-well/lvtn fix on the last GDS: cellfix_stage.py (pw4_shunt, pw4_bridge, pw4_rblock4
                 corrected by the earlier chip's generator, ne_bias_writer again from the corrected writer) -> <stem>_c.gds,
                 then well_patch.py apply (n-well rectangles) -> <stem>_w.gds, then its checks (check_die_v4.py with
                 --v4, check_die.py otherwise)
  with --strap BLOCK.json STRAP.json: the XPROG ground strap (variant D) on the last GDS: strap_patch.py (the bias
                 layout's block file: boxes removed from a cell, cuts added; then the layout stream's strap rectangles)
                 -> <stem>_s.gds, then its checks (check_die_v4.py with --v4, check_die.py otherwise)
  with --rzero CELL.gds V5.spice (on top of --v4 and --strap): rzero_patch.py (cell ar4_rzero's shapes replaced by the
                 checked cell file: the REF buffer's zero resistor at L 0.70) -> <stem>_r.gds, then check_die_v4.py
                 against netlist version 5, which is also the extraction's schematic (every check_die_v4.py run also
                 checks the amplifier macros against its netlist version: macro_check.py)
  with --antenna-patch JSON (on top of lock4_r): four M2 cuts, dual via2 landings, M3 jumpers and scrap removal;
                 version-5 LVS and DRC, two resistor models at every etch, and Magic on truncated stage copies
  then           antenna (the base flow's signoff.antenna) and extract.py (capacitance-only board model) on the last GDS
Without --schematic the interim circuit (scripts/variant_schematic.py on the selected layout's circuit) is used.
"""
import argparse, gzip, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
SIX = HERE.parents[3]
NE = SIX / 'native_edges'
# interpreters from the environment: PY (default: the one running this script, passed on to the stages through the
# environment) and KLAYOUT_PY, KLayout's Python, as the layout stream's scripts take it
KPY = Path(os.environ.get('KLAYOUT_PY') or Path.home() / '.local/opt/klayout-py/bin/python')
PY = Path(os.environ.get('PY') or sys.executable); os.environ['PY'] = str(PY)


def run(folder, i, name, cmd, cwd):
    with (folder / f'{i:02d}_{name}.log').open('w') as log:
        subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)


def main(folder, w1, l1, w2, l2, schematic=None, expect=None, patch=None, v4=None, wells=None, cellfix_level=1, strap=None,
         rzero=None, antenna_patch=None):
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('rebuild needs an empty folder')
    folder.mkdir(parents=True, exist_ok=True)
    if schematic is None:
        schematic = folder / 'variant_interim.spice'
        subprocess.run([str(PY), '-I', str(HERE / 'variant_schematic.py'),
                        str(NE / 'verification/evidence/layout_bbf78759_gate_p897/reference.spice.gz'),
                        str(schematic), w1, l1, w2, l2], check=True, stdout=subprocess.DEVNULL)
    lay = NE / 'layout'
    run(folder, 0, 'bias_stage', [KPY, '-B', HERE / 'bias_stage.py', folder, w1, l1, w2, l2], HERE)
    run(folder, 1, 'check_die', [PY, '-B', lay / 'check_die.py', folder / 'chip', '--negative', '--schematic', schematic], lay)
    run(folder, 2, 'repair', [KPY, '-B', lay / 'repair.py', folder / 'chip', folder / 'chip_fill', '--fill',
                              '--targets', folder / 'chip_targets.json'], lay)
    run(folder, 3, 'check_die', [PY, '-B', lay / 'check_die.py', folder / 'chip_fill', '--negative', '--schematic', schematic], lay)
    final, i = 'chip_fill', 4
    if patch:
        run(folder, 4, 'supply_patch', [KPY, '-B', HERE / 'supply_patch.py', folder / 'chip_fill.gds', patch, folder / 'chip_lock.gds'], HERE)
        run(folder, 5, 'check_die', [PY, '-B', lay / 'check_die.py', folder / 'chip_lock', '--negative', '--schematic', schematic], lay)
        final, i = 'chip_lock', 6
    last_schematic = schematic
    if v4:
        if not patch:
            raise ValueError('--v4 builds on the lock build: give --patch as well')
        run(folder, 6, 'v4_stage', [KPY, '-B', HERE / 'v4_stage.py', folder / 'chip_lock.gds', folder], HERE)
        shutil.copyfile(folder / 'chip_v4.gds', folder / 'chip_v4_base_table.gds')
        run(folder, 7, 'check_die_base_table', [PY, '-B', lay / 'check_die.py', folder / 'chip_v4_base_table', '--negative',
                                                 '--schematic', v4], lay)
        run(folder, 8, 'check_die_v4', [PY, '-B', HERE / 'check_die_v4.py', folder / 'chip_v4', '--negative', '--schematic', v4], HERE)
        final, i, last_schematic = 'chip_v4', 9, v4
    if wells:
        run(folder, i, 'cellfix_stage', [KPY, '-B', HERE / 'cellfix_stage.py', folder / f'{final}.gds', folder / f'{final}_c.gds',
                                         folder / 'cellfix.json'] + ([cellfix_level] if cellfix_level != 1 else []), HERE)
        run(folder, i + 1, 'well_patch', [KPY, '-B', HERE / 'well_patch.py', 'apply', folder / f'{final}_c.gds', wells,
                                          folder / f'{final}_w.gds'], HERE)
        if v4:
            run(folder, i + 2, 'check_die_v4', [PY, '-B', HERE / 'check_die_v4.py', folder / f'{final}_w', '--negative',
                                                '--schematic', v4], HERE)
        else:
            run(folder, i + 2, 'check_die', [PY, '-B', lay / 'check_die.py', folder / f'{final}_w', '--negative',
                                             '--schematic', last_schematic], lay)
        final, i = f'{final}_w', i + 3
    if strap:
        run(folder, i, 'strap_patch', [KPY, '-B', HERE / 'strap_patch.py', folder / f'{final}.gds', folder / f'{final}_s.gds',
                                       folder / 'strap_patch.json'] + list(strap), HERE)
        if v4:
            run(folder, i + 1, 'check_die_v4', [PY, '-B', HERE / 'check_die_v4.py', folder / f'{final}_s', '--negative',
                                                '--schematic', v4], HERE)
        else:
            run(folder, i + 1, 'check_die', [PY, '-B', lay / 'check_die.py', folder / f'{final}_s', '--negative',
                                             '--schematic', last_schematic], lay)
        final, i = f'{final}_s', i + 2
    if rzero:
        if not (v4 and strap):
            raise ValueError('--rzero builds on lock3: give --v4 and --strap as well')
        cell_gds, v5 = rzero
        run(folder, i, 'rzero_patch', [KPY, '-B', HERE / 'rzero_patch.py', folder / f'{final}.gds', folder / f'{final}_r.gds',
                                       folder / 'rzero_patch.json', cell_gds], HERE)
        run(folder, i + 1, 'check_die_v4', [PY, '-B', HERE / 'check_die_v4.py', folder / f'{final}_r', '--negative',
                                            '--schematic', v5], HERE)
        final, i, last_schematic = f'{final}_r', i + 2, v5
    if antenna_patch:
        if not rzero or hashlib.sha256(last_schematic.read_bytes()).hexdigest() != '399eac539f89319920f6f0921f33a6454fbd4b10d10704f1164dfca0bb13a8c6':
            raise ValueError('--antenna-patch requires --rzero and the lock4_r version-5 schematic')
        stem = f'{final}_a'
        output = folder / f'{stem}.gds'
        run(folder, i, 'antenna_patch', [KPY, '-B', HERE / 'antenna_patch.py', folder / f'{final}.gds',
                                         output, folder / 'antenna_patch.json', antenna_patch], HERE)
        run(folder, i + 1, 'check_die_v4', [PY, '-B', HERE / 'check_die_v4.py', folder / stem, '--negative',
                                            '--schematic', last_schematic], HERE)
        run(folder, i + 2, 'etch_antenna', [KPY, '-B', HERE / 'antenna_stage.py', output, folder / 'etch_antenna.json',
                                            '--nets-gz', folder / 'etch_nets.json.gz'], HERE)
        run(folder, i + 3, 'magic_etch', [KPY, '-B', HERE / 'antenna_magic.py', output, folder / 'magic_etch',
                                          folder / 'magic_etch.json'], HERE)
        final, i = stem, i + 4
    run(folder, i, 'antenna', [PY, '-B', '-c', f"import sys; sys.path.insert(0, {str(lay)!r}); import signoff; signoff.antenna({str(folder / final)!r})"], lay)
    run(folder, i + 1, 'extract', [PY, '-B', lay / 'extract.py', folder / final, '--schematic', last_schematic,
                               '--unit-mim', lay / 'results/quiet_rc_release/mim_unit.spice', '--unit-mim-count', 3], lay)
    if antenna_patch:
        run(folder, i + 2, 'release_records', [PY, '-B', HERE / 'antenna_records.py', folder, final], HERE)
    gds = (folder / f'{final}.gds').read_bytes()
    receipt = json.loads((folder / f'{final}_checks/receipt.json').read_text())
    summary = dict(gds_sha256=hashlib.sha256(gds).hexdigest(), schematic_sha256=hashlib.sha256(Path(last_schematic).read_bytes()).hexdigest(),
                   Magic_full_DRC=receipt['Magic_full_DRC'], LVS={k: v['result'] for k, v in receipt['comparisons'].items()},
                   antenna=json.loads((folder / f'{final}_checks/antenna.json').read_text()),
                   board_spice_sha256=json.loads((folder / f'{final}_pex/manifest.json').read_text())['board_spice_sha256'],
                   final_stem=final, supply_patch=str(patch) if patch else None)
    if v4:
        base = json.loads((folder / 'chip_v4_base_table_checks/receipt.json').read_text())
        summary['lock_checks_schematic_sha256'] = hashlib.sha256(Path(schematic).read_bytes()).hexdigest()
        summary['LVS_with_base_dummy_table'] = {k: dict(result=v['result'], property_errors=v['property_errors'])
                                                 for k, v in base['comparisons'].items()}
        summary['LVS_property_errors'] = {k: v['property_errors'] for k, v in receipt['comparisons'].items()}
        summary['v4_dummy_table_sha256'] = hashlib.sha256((folder / 'v4_reference/results/poly_cells.json').read_bytes()).hexdigest()
        summary['reference_with_v4_dummies_sha256'] = hashlib.sha256((folder / 'chip_v4_checks/reference.spice').read_bytes()).hexdigest()
    if wells:
        summary['well_patch'] = dict(file=Path(wells).name, sha256=hashlib.sha256(Path(wells).read_bytes()).hexdigest())
        summary['cellfix_output_gds_sha256'] = json.loads((folder / 'cellfix.json').read_text())['output_gds_sha256']
    if strap:
        srec = json.loads((folder / 'strap_patch.json').read_text())
        summary['strap_patch'] = dict(files=srec['patches'], base=srec['base'], input_gds_sha256=srec['input_gds_sha256'],
                                      removed=len(srec['removed']), added=len(srec['added']))
    if rzero:
        rrec = json.loads((folder / 'rzero_patch.json').read_text())
        summary['rzero_patch'] = dict(cell=rrec['cell'], cell_file=rrec['cell_file'], base=rrec['base'],
                                      input_gds_sha256=rrec['input_gds_sha256'])
        summary['reference_v5_sha256'] = hashlib.sha256((folder / f'{final}_checks/reference.spice').read_bytes()).hexdigest()
        mc = json.loads((folder / f'{final}_macro_check.json').read_text())
        summary['macro_check'] = dict(differences=len(mc['differences']), instances=len(mc['instances']),
                                      macros={k: v['sha256'] for k, v in mc['macros'].items()}, verdict=mc['verdict'])
    if antenna_patch:
        summary['antenna_patch_sha256'] = hashlib.sha256(antenna_patch.read_bytes()).hexdigest()
        summary['etch_failures'] = json.loads((folder / 'etch_antenna.json').read_text())['failed_net_stage_models']
        summary['magic_etch_violations'] = json.loads((folder / 'magic_etch.json').read_text())['violations']
        summary['release_manifest_sha256'] = hashlib.sha256((folder / 'release_records/manifest.json').read_bytes()).hexdigest()
        if (summary['antenna']['violations'] or summary['Magic_full_DRC']['total'] or
                receipt['comparisons']['reference']['property_errors'] or
                receipt['comparisons']['reference']['result'] != 'Circuits match uniquely.' or
                receipt['comparisons']['reference_bad']['same_name_port_pairs']):
            raise ValueError('lock5_r final full-die signoff failed')
    (folder / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    print(json.dumps(summary, indent=1))
    if expect and summary['gds_sha256'] != expect:
        raise SystemExit(f"GDS differs from the expected {expect}")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    for k in ('w1', 'l1', 'w2', 'l2'):
        p.add_argument(k)
    p.add_argument('--schematic', type=Path); p.add_argument('--expect'); p.add_argument('--patch', type=Path)
    p.add_argument('--v4', type=Path, help='netlist version 4: add the second candidate on top of the lock build')
    p.add_argument('--wells', type=Path, help="n-well patch for Tiny Tapeout's lvtn.10 rule, applied last")
    p.add_argument('--cellfix-level', type=int, default=1, help='1: lock2_w (0.825 rule); 2: lock2_h (drawn HVI 0.64 as well)')
    p.add_argument('--strap', type=Path, nargs=2, metavar=('BLOCK', 'STRAP'),
                   help='the XPROG ground strap (variant D), applied after the well patch: block file, then strap file')
    p.add_argument('--rzero', type=Path, nargs=2, metavar=('CELL', 'V5'),
                   help="the REF buffer's zero resistor at L 0.70, applied after the strap: cell file, netlist version 5")
    p.add_argument('--antenna-patch', type=Path, help='apply the lock5_r etch-stage antenna repair after --rzero')
    a = p.parse_args()
    main(a.folder.resolve(), a.w1, a.l1, a.w2, a.l2, a.schematic.resolve() if a.schematic else None, a.expect,
         a.patch.resolve() if a.patch else None, a.v4.resolve() if a.v4 else None, a.wells.resolve() if a.wells else None,
         a.cellfix_level, [f.resolve() for f in a.strap] if a.strap else None,
         [f.resolve() for f in a.rzero] if a.rzero else None, a.antenna_patch.resolve() if a.antenna_patch else None)
