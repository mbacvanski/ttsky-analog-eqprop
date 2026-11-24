"""Three HVI measurements the rule audit says SkyWater cares about and no deck of ours tests, read from the audit's own
measure.py output (takeover/checks/rule_audit/measure.py, run by check_all.sh on the layout and its staged GDS and LEF).

  PY -I hvi_measures.py MEASURE.json [OUT.json]        exit 1 if any limit is broken

  hvi.5      the smallest distance from drawn HVI to an n-well outside it (a low-voltage well; HV wells lie inside HVI):
             at least 0.64 um, the lowest value on record as accepted on past shuttles (the rule is 0.70; the audit's
             measure.py lists every place below 0.70)
  width      the narrowest HVI: at least 0.84 um (SkyWater's extra rule; measure.py counts widths below 0.84)
  hvpoly.14  HVI edges running across gate poly: no more than lock2's 197 (the audit's count on lock2; 121 poly shapes)
Two more of measure.py's measurements, judged since 24 Nov:
  capm.10    MIM capacitors (capm) with an edge of n-well, diffusion, tap, poly, li1 or metal 1 under them: no more than
             lock4_r's 105 of 109 (the 2020 deck's rule; SkyWater accepted the pattern in 12 Tiny Tapeout projects; it could
             not be fixed here, so the limit holds it where it is)
  licon.15   npc around every poly contact, gate contacts and resistor heads alike: at least 0.10 um, every contact inside
             npc (lock4_r: 0.105 at the gate contacts, 0.18 at the resistor heads; Tiny Tapeout's issue 179)
"""
import json
import sys

LIMITS = dict(hvi5_min_um=0.64, width_min_um=0.84, hvpoly_crossings_max=197, capm10_straddled_max=105, licon15_min_um=0.10)


def main(src, out=None):
    m = json.loads(open(src).read())
    h5 = m["hvi.5"]
    below = h5.get("measured_min_max_um")
    smallest = below[0] if below else None                     # None: no place below 0.70
    under_064 = [p for p in h5.get("all_places", []) if p["min_distance_um"] < LIMITS["hvi5_min_um"]]
    w = m["hvi_width_0.84"]
    hp = m["hvpoly.14"]
    res = dict(source=src, limits=LIMITS,
               hvi5=dict(smallest_um=smallest, places_below_0p70=h5.get("distinct_places", 0), places_below_0p64=len(under_064),
                         worst=h5.get("worst", [])[:3], ok=smallest is None or smallest >= LIMITS["hvi5_min_um"]),
               width=dict(narrower_than_0p84=w["violations_084"], narrowest_below_0p84_um=w.get("narrowest_um"),
                          narrowest_bounding_box_side_um=w.get("hvi_min_bbox_side_um"), ok=w["violations_084"] == 0),
               hvpoly=dict(hvi_edges_across_poly=hp["crossing_edges"], poly_shapes_crossing=hp["poly_shapes_crossing"],
                           ok=hp["crossing_edges"] <= LIMITS["hvpoly_crossings_max"]))
    c10 = m["capm.10"]
    straddled = c10["capm_shapes"] - c10["capm_shapes_free_of_all_six"]
    res["capm10"] = dict(capm_shapes=c10["capm_shapes"], with_a_lower_layer_edge_under=straddled,
                         per_layer={k: v["capm_shapes_with_edges_under"] for k, v in c10["per_layer"].items()}, ok=straddled <= LIMITS["capm10_straddled_max"])
    l15 = {k[len("licon.15_"):]: m[k] for k in ("licon.15_gate_contacts", "licon.15_resistor_head_contacts")}
    res["licon15"] = dict({k: dict(contacts=v["contacts"], outside_npc=v["not_covered_by_npc"], enclosure_below_0p10=v["enclosure_below_0p10"],
                                   smallest_enclosure_um=v["all_contacts_min_enclosure_um"]) for k, v in l15.items()},
                          ok=all(v["not_covered_by_npc"] == 0 and v["enclosure_below_0p10"] == 0 and (v["all_contacts_min_enclosure_um"] or 0) >= LIMITS["licon15_min_um"]
                                 for v in l15.values()))
    res["ok"] = res["hvi5"]["ok"] and res["width"]["ok"] and res["hvpoly"]["ok"] and res["capm10"]["ok"] and res["licon15"]["ok"]
    if out:
        open(out, "w").write(json.dumps(res, indent=1) + "\n")
    print(f"HVI to low-voltage n-well: smallest {smallest if smallest is not None else '>= 0.70'} um (limit 0.64), "
          f"{res['hvi5']['places_below_0p64']} places below 0.64, {res['hvi5']['places_below_0p70']} below 0.70: {'ok' if res['hvi5']['ok'] else 'FAILS'}")
    print(f"HVI width: {w['violations_084']} places narrower than 0.84 um (narrowest bounding-box side {w.get('hvi_min_bbox_side_um')}): "
          f"{'ok' if res['width']['ok'] else 'FAILS'}")
    print(f"HVI edges across gate poly: {hp['crossing_edges']} ({hp['poly_shapes_crossing']} poly shapes; limit 197, lock2's): "
          f"{'ok' if res['hvpoly']['ok'] else 'FAILS'}")
    print(f"capm.10: {straddled} of {c10['capm_shapes']} MIM capacitors with a lower layer's edge under them (limit 105, lock4_r's): "
          f"{'ok' if res['capm10']['ok'] else 'FAILS'}")
    print(f"licon.15: npc around poly contacts at least {min((v['all_contacts_min_enclosure_um'] or 0) for v in l15.values())} um, "
          f"{sum(v['not_covered_by_npc'] for v in l15.values())} outside npc (limit 0.10): {'ok' if res['licon15']['ok'] else 'FAILS'}")
    print("HVI MEASURES:", "ALL WITHIN LIMITS" if res["ok"] else "OUTSIDE A LIMIT")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
