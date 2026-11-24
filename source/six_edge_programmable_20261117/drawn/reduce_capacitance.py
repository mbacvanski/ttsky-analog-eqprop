"""Eliminate floating linear metal islands while preserving charge at every device port."""
from collections import defaultdict
import itertools

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import spsolve


def fraction_ff(value):
    units={'f':1.,'p':1000.,'n':1e6,'u':1e9,'':1e15}
    suffix=value[-1].lower() if value[-1].isalpha() else ''
    return float(value[:-1] if suffix else value)*units[suffix]


def reduce(text,unconnected_ports=()):
    unconnected_ports=set(unconnected_ports)
    front=[]; caps=[]; driven=set()
    physical_pins=set()

    for line in text.splitlines():
        fields=line.split()
        if line.startswith('X'):
            i=next(i for i,v in enumerate(fields) if v.startswith('sky130_fd_pr__'))
            assert not (set(fields[1:i])&unconnected_ports), "Unconnected port reaches an extracted device"
            driven.update(fields[1:i])
            front.append(line)
        elif line.startswith('R'):
            assert len(fields)==4 and float(fields[3])>0.
            assert not (set(fields[1:3])&unconnected_ports), "An unbonded port has a physical wire path"
            driven.update(fields[1:3])
            front.append(line)
        elif line.startswith('.subckt'):
            physical_pins.update(fields[2:])
            keep=[p for p in fields[2:] if p not in unconnected_ports]
            driven.update(keep)
            front.append(" ".join([*fields[:2],*keep]) if unconnected_ports else line)
        elif line.startswith('C'):
            a,b=fields[1:3]
            c=fraction_ff(fields[3])
            if c<0:raise ValueError('Negative extracted capacitance')
            if c and a!=b:caps.append((a,b,c))
        elif not line.startswith('.ends'):
            front.append(line)
    assert unconnected_ports<=physical_pins
    nodes=sorted({n for a,b,c in caps for n in (a,b)})
    active=sorted(set(nodes)&driven)
    free=sorted(set(nodes)-driven)
    graph=defaultdict(dict)
    def add(a,b,v):
        graph[a][b]=graph[b][a]=graph[a].get(b,0.)+v
    for a,b,c in caps:add(a,b,c)
    for n in free:
        edges=graph.pop(n,{})
        total=sum(edges.values())
        for a in edges:del graph[a][n]
        for (a,ca),(b,cb) in itertools.combinations(edges.items(),2):
            add(a,b,ca*cb/total)
    result=sorted((a,b,c) for a,links in graph.items() for b,c in links.items() if a<b)
    def matrix(nodes,edges):
        ix={v:i for i,v in enumerate(nodes)}
        row=[];col=[];val=[]
        for a,b,c in edges:
            i,j=ix[a],ix[b]
            row.extend((i,j,i,j));col.extend((i,j,j,i));val.extend((c,c,-c,-c))
        return sparse.coo_matrix((val,(row,col)),shape=(len(nodes),)*2).tocsr()
    original=matrix(active+free,caps)
    condensed=matrix(active,result)
    n=len(active)
    volts=np.random.default_rng(17112026).uniform(-1,1,(n,16))
    projected=original[:n,:n]@volts
    if free:
        block=original[n:,n:]
        cross=original[n:,:n]
        # Components attached only to each other have no external current.
        _,cc=connected_components(block,directed=False)
        attached=np.flatnonzero(np.asarray(abs(cross).sum(axis=1)).ravel()>0)
        connected=np.flatnonzero(np.isin(cc,cc[attached]))
        if len(connected):
            vf=spsolve(block[connected,:][:,connected],-(cross[connected,:]@volts))
            projected += (cross[connected,:].T@vf)
    solved=condensed@volts
    error=float(np.max(np.abs(solved-projected)))
    assert error/max(1,float(np.max(abs(projected))))<1e-11,error
    lines=front+[f'Cw{i} {a} {b} {c:.15g}f' for i,(a,b,c) in enumerate(result)]+['.ends sx_drawn']
    return '\n'.join(lines)+'\n',dict(floating_linear_nodes_eliminated=len(free),
              original_positive_capacitors=len(caps),reduced_capacitors=len(result),independent_voltage_vectors=16,
              maximum_external_charge_error_fC_at_1V=error)
