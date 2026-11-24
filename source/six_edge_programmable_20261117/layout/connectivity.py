"""Identify exact connected metal from a flattened SKY130 geometry with KLayout."""
import klayout.db as db

METALS = {'li':(67,20),'mcon':(67,44),'m1':(68,20),'v1':(68,44),
          'm2':(69,20),'v2':(69,44),'m3':(70,20),'v3':(70,44),'m4':(71,20)}
INDEX = {name:i for i,name in enumerate(('m1','m2','m3','m4'))}


class Connectivity:
    def __init__(self,layout,cell):
        self.dbu=layout.dbu
        self.e=db.LayoutToNetlist('all',layout.dbu)
        self.layers={}
        for name,pair in METALS.items():
            ix=layout.find_layer(*pair)
            shapes=db.Region(cell.begin_shapes_rec(ix)) if ix is not None else db.Region()
            shapes.merge()
            self.e.register(shapes,name)
            self.layers[name]=shapes
        get=self.layers.__getitem__
        for name in ('li','m1','m2','m3','m4'):
            self.e.connect(get(name))
        # Via3 through CAPM lands on the MIM top plate, insulated from M3.
        cap_layer=layout.find_layer(89,44)
        cap=db.Region(cell.begin_shapes_rec(cap_layer)) if cap_layer is not None else db.Region()
        cap.merge()
        via3=get('v3')
        plain=via3-cap
        top_contact=via3 & cap
        for shapes,name in [(cap,'capm'),(plain,'via3_plain'),(top_contact,'capm_contact')]:
            self.e.register(shapes,name)
        self.e.connect(cap)
        self.e.connect(cap,top_contact)
        self.e.connect(get('m4'),top_contact)
        self.e.connect(get('m3'),plain)
        self.e.connect(get('m4'),plain)
        for via,l,r in [('mcon','li','m1'),('v1','m1','m2'),('v2','m2','m3')]:
            self.e.connect(get(l),get(via))
            self.e.connect(get(via),get(r))
        self.e.extract_netlist()
        self.nets={n.cluster_id:n for n in self.e.netlist().top_circuit().each_net()}

    def probe(self,layer,x,y):
        n=self.e.probe_net(self.layers[layer],db.DPoint(x,y).to_itype(self.dbu))
        return n.cluster_id if n is not None else None

    def region(self,net,layer):
        return self.e.shapes_of_net(self.nets[net],self.layers[layer],True)


def labels(layout,cell,trans=None):
    by_name={}
    for k,(m,d) in METALS.items():
        if k not in INDEX: continue
        ix=layout.find_layer(m,5)
        if ix is None: continue
        for s in cell.shapes(ix).each():
            if not s.is_text():continue
            point=db.DPoint(s.text.x*layout.dbu,s.text.y*layout.dbu)
            if trans is not None:point=trans*point
            by_name.setdefault(s.text.string,[]).append((k,round(point.x,6),round(point.y,6)))
    return by_name


def as_boxes(region,dbu):
    return [[round(v*dbu,5) for v in (b.left,b.bottom,b.right,b.top)]
            for p in region.merged().decompose_trapezoids_to_region().each() for b in [p.bbox()]]
