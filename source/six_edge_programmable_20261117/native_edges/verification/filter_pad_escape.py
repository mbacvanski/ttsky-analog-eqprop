"""Route the package-side filter lead on actual local interconnect and the four TT signal metals."""
import argparse
from array import array
from collections import Counter
import heapq
import json
from pathlib import Path

import klayout.db as db

from filter_placement_survey import quiet_route
from route_split import circuit


METAL = ("li", "m1", "m2", "m3", "m4")
CUT = ("mcon", "v1", "v2", "v3")
WIDTH_HALF = (110, 75, 75, 150, 150)
SPACE = (180, 150, 150, 315, 315)
VIA_LANDING_HALF = (175, 170, 190, 205, 205)
CUT_HALF = (85, 75, 100, 100)
CUT_AVOID = (285, 260, 325, 325)


class RoutingWindow:
    def __init__(self, roi, pitch, offset):
        self.pitch = pitch
        self.left = (roi.left // pitch) * pitch + offset
        self.bottom = (roi.bottom // pitch) * pitch + offset
        self.nx = (roi.right - self.left) // pitch + 1
        self.ny = (roi.top - self.bottom) // pitch + 1
        self.area = self.nx * self.ny

    def mask(self, region):
        cells = bytearray(self.area)
        for poly in region.decompose_trapezoids_to_region().each():
            b = poly.bbox()
            x0 = max(0, (b.left - self.left + self.pitch - 1) // self.pitch)
            y0 = max(0, (b.bottom - self.bottom + self.pitch - 1) // self.pitch)
            x1 = min(self.nx - 1, (b.right - self.left) // self.pitch)
            y1 = min(self.ny - 1, (b.top - self.bottom) // self.pitch)
            if x0 <= x1 and y0 <= y1:
                value = bytes([1]) * (x1 - x0 + 1)
                for y in range(y0, y1 + 1):
                    begin = y * self.nx + x0
                    cells[begin: begin + len(value)] = value
        return cells

    def coords(self, node):
        level, site = divmod(node, self.area)
        y, x = divmod(site, self.nx)
        return level, self.left + x*self.pitch, self.bottom + y*self.pitch


def shortest(window, planar, contacts, starts, goals):
    """Prefer a short package lead, with a small additional cost on each new contact."""
    goal_coords = [window.coords(n) for n in goals]
    gx = [v[1] for v in goal_coords]
    gy = [v[2] for v in goal_coords]
    x0, x1, y0, y1 = min(gx), max(gx), min(gy), max(gy)
    def heuristic(n):
        _, x, y = window.coords(n)
        return max(0, x0-x, x-x1) + max(0, y0-y, y-y1)

    dist = array("i", [2**31-1]) * (5*window.area)
    prev = array("i", [-1]) * len(dist)
    queue = []
    for node in starts:
        dist[node] = 0
        heapq.heappush(queue, (heuristic(node), 0, node))
    while queue:
        _, travel, cur = heapq.heappop(queue)
        if travel != dist[cur]:
            continue
        if cur in goals:
            path = [cur]
            while prev[path[-1]] >= 0:
                path.append(prev[path[-1]])
            return path[::-1]
        level, site = divmod(cur, window.area)
        y, x = divmod(site, window.nx)
        choices = []
        # Planar edges use a fine Manhattan grid. Their center spacing excludes
        # nearby metal, and the final shape-level connectivity/DRC tests are separate.
        for edge, ok in ((-1, x > 0), (1, x+1 < window.nx),
                         (-window.nx, y > 0), (window.nx, y+1 < window.ny)):
            if ok and not planar[level][site+edge]:
                choices.append((cur+edge, window.pitch+(10 if level == 0 else 0)))
        for other in (level-1, level+1):
            if 0 <= other < len(METAL) and not contacts[min(level, other)][site] and not planar[other][site]:
                choices.append((other*window.area+site, 550))
        for new, increment in choices:
            total = travel + increment
            if total < dist[new]:
                dist[new], prev[new] = total, cur
                heapq.heappush(queue, (total + heuristic(new), total, new))
    raise ValueError("No design-rule-spaced local route from package pad to the actual entry resistor")


def write_path(layout, top, coords):
    lines = []
    vias = Counter()
    travel = Counter()
    def draw(name, x, y, X, Y, half):
        box = db.Box(min(x,X)-half, min(y,Y)-half, max(x,X)+half, max(y,Y)+half)
        top.shapes(layout.layer(*quiet_route.METALS[name])).insert(box)
    for a,b in zip(coords,coords[1:]):
        level,x,y=a
        nxt,X,Y=b
        if level != nxt:
            assert (x,y) == (X,Y) and abs(nxt-level) == 1
            low=min(nxt,level)
            for l in (nxt,level):
                draw(METAL[l],x,y,X,Y,VIA_LANDING_HALF[l])
            draw(CUT[low],x,y,X,Y,CUT_HALF[low])
            vias[CUT[low]]+=1
        else:
            travel[METAL[level]]+=abs(X-x)+abs(Y-y)
        axis = (level,nxt) if level != nxt else (level, 'y' if x==X else 'x')
        if lines and lines[-1][2]==axis:
            lines[-1][1]=b
        else:
            lines.append([a,b,axis])
    for (l,x,y),(n,X,Y),_ in lines:
        if l==n:
            draw(METAL[l],x,y,X,Y,WIDTH_HALF[l])
    return dict(added_planar_length_um=sum(travel.values())/1000,
                by_layer_um={k:v/1000 for k,v in travel.items()},via_count=dict(vias),
                centerline_legs_nm=[dict(start=a,end=b) for a,b,_ in lines])


def route(source, targets, output):
    layout = db.Layout()
    layout.read(str(source))
    top = layout.top_cell()
    pins=json.loads(targets.read_bytes())
    nets, shorts, con = circuit(layout,top,pins)
    assert not shorts and {k:len(v) for k,v in nets.items() if len(v)>1} == {"res_sel":2}
    pad, = [p for p in pins if p[1]=="TT:uio_in[6]"]
    resistor, = [p for p in pins if p[1]=="R:res_sel"]
    components=[con.probe(p[2],p[3],p[4]) for p in (pad,resistor)]
    assert len(set(components)) == 2 and set(components) == nets["res_sel"].keys()
    # Within this window, the pad can first descend north of the congested top
    # power/echo bank, then cross it on a lower layer wherever the real mask permits.
    bounds=db.Box(75000,192000,125000,225500)
    roi=db.Region(bounds)
    halo=roi.sized(4000)
    win=RoutingWindow(bounds,90,45)
    other=[]
    terminals=[set(),set()]
    planar=[]
    for level,name in enumerate(METAL):
        landing=[con.region(net,name)&halo for net in components]
        blocked=(con.layers[name]&halo)-landing[0]-landing[1]
        other.append(blocked)
        thick=blocked.sized(WIDTH_HALF[level]+SPACE[level])
        if name=="m3":
            thick+=db.Region(top.begin_shapes_rec(layout.layer(89,44))).sized(1620)
        mask=win.mask(thick&roi)
        planar.append(mask)
        for index, region in enumerate(landing):
            sites=win.mask(region.sized(10)&roi)
            terminals[index].update(level*win.area+i for i,v in enumerate(sites) if v and not mask[i])
    vias=[]
    for low,cut in enumerate(CUT):
        bad = (con.layers[cut]&halo).sized(CUT_AVOID[low])
        for level in (low,low+1):
            bad+=other[level].sized(VIA_LANDING_HALF[level]+SPACE[level])
        if cut in ("v2","v3"):
            bad+=db.Region(top.begin_shapes_rec(layout.layer(89,44))).sized(675)
        vias.append(win.mask(bad&roi))
    path=shortest(win,planar,vias,*terminals)
    report=write_path(layout,top,[win.coords(n) for n in path])
    connected,conflict,_=circuit(layout,top,pins)
    if conflict or any(len(v)!=1 for v in connected.values()):
        raise ValueError(("Actual routed geometry has a registered wiring conflict",conflict))
    quiet_route.save(layout,top,output)
    report.update(route_grid_nm=win.pitch,route_window_nm=bounds.to_s(),physical_terminal_count=len(pins),
                  full_registered_copper_connectivity=True)
    output.with_suffix(".json").write_text(json.dumps(report,indent=1)+"\n")
    print(report["added_planar_length_um"],report["by_layer_um"],report["via_count"],flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("open_gds",type=Path)
    ap.add_argument("targets",type=Path)
    ap.add_argument("output",type=Path)
    a=ap.parse_args()
    route(a.open_gds,a.targets,a.output)
