"""Audit the native reciprocal weight as a passive physical two-port and load the clamped sources."""
import gzip
import hashlib
import json
from pathlib import Path
import re

import numpy as np

HERE=Path(__file__).resolve().parent
SIX=HERE.parents[1]
V4=SIX.parent/'programmable_weights_v4_20261114'
FROZEN=SIX/'circuit/frozen_native.spice.gz'
EXPECTED='044ca8cbdc58aa5a5a45a24d47b9e884abf5091fc83048dc1af299b052cad197'
NAMES=('A','B','H1','H2','Z')
EDGES=(('A','H1'),('B','H1'),('A','H2'),('B','H2'),('H1','Z'),('H2','Z'))


def parts(weight):
    if not .25<=weight<=.75:
        raise ValueError('The constant-load native range is [0.25,0.75].')
    return 20/(weight+.25)-20,5*weight-1.25


def ports(gs,gb,left=10.,right=10.):
    """Construct the three physical nodes, eliminate the free midpoint by its KCL equation."""
    matrix=np.zeros((3,3))
    for i,j,g in ((0,2,left),(1,2,right),(0,1,gb)):
        matrix[i,i]+=g;matrix[j,j]+=g;matrix[i,j]-=g;matrix[j,i]-=g
    matrix[2,2]+=gs
    return matrix[:2,:2]-np.outer(matrix[:2,2],matrix[2,:2])/matrix[2,2]


def network(weights):
    assert len(weights)==len(EDGES)
    matrix=np.zeros((len(NAMES),len(NAMES)))
    for w,edge in zip(weights,EDGES):
        ix=[NAMES.index(n) for n in edge]
        matrix[np.ix_(ix,ix)]+=ports(*parts(w))
    return matrix


def neuron(g4,g7,external_diagonal):
    """Two native amp stages, G1=G6=G8=10 µS, G3=G5=5 µS, REF-subtracted."""
    g=10
    return dict(bias_gain=5*(2*g+g4+g7)/(g*(g4+g)),
        self_feedback=g4*(2*g+g4+g7)/(g*(g4+g))-(g+external_diagonal+g4)/g)


def sources():
    raw=gzip.decompress(FROZEN.read_bytes())
    sha=lambda v:hashlib.sha256(v).hexdigest()
    assert sha(raw)==EXPECTED
    lines=raw.decode().splitlines()
    names=['pw4_shunt','pw4_bridge','pw4_rblock4','pw4_mid','pw4_nrn_h','pw4_units3d','pw4_nrn_z','pw4_units5',
           'pw4_dacgate','cd_core_two_az_pq','pdk_rfixed2_m','pdk_rfixed2_h_m','xor_network_v4','xor_chip_v4']
    sections={}
    for name in names:
        start=next(i for i,line in enumerate(lines) if re.match(r'^\.subckt\s+'+name+r'(?:\s|$)',line,re.I))
        end=next(i for i in range(start+1,len(lines)) if lines[i].lower().startswith('.ends'))
        sections[name]=dict(first_line=start+1,last_line=end+1,
             sha256=sha(('\n'.join(lines[start:end+1])+'\n').encode()))
    return dict(frozen_source=str(FROZEN.relative_to(SIX)),compressed_sha256=sha(FROZEN.read_bytes()),
                decompressed_sha256=sha(raw),line_and_text_hash=sections)


def characterize():
    anchors={}
    for weight in np.linspace(.25,.75,101):
        sh,br=parts(weight);m=ports(sh,br)
        np.testing.assert_allclose(np.diag(m),[7.5,7.5],atol=2e-15)
        np.testing.assert_allclose(m[0,1],-10*weight,atol=2e-15)
        np.testing.assert_array_equal(m,m.T)
        assert np.linalg.eigvalsh(m)[0]>-1e-12
        if weight in (.25,.5,.75):
            anchors[str(weight)]=dict(shunt_uS=sh,bridge_uS=br,matrix_uS=m.tolist())
    matrix=network([.25,.75,.625,.375,.25,.75])
    expected=np.array([15.,15.,22.5,22.5,15.])
    np.testing.assert_allclose(np.diag(matrix),expected,atol=1e-13)
    # Positive nudge branch adds 2.5 µS at Z; all ideal anchored source voltages are expressed relative to REF.
    banks={name:neuron(correct,correct,diag) for name,correct,diag in [('H1',32.5,22.5),('H2',32.5,22.5),('Z',27.5,17.5)]}
    assert all(abs(a['bias_gain']-1)<1e-10 and abs(a['self_feedback'])<1e-10 for a in banks.values())
    variants={str(g):neuron(g,g,22.5) for g in [17.5,22.5,25.,32.5]}
    source=[]
    for span in [50,100,150]:
        # Conservative: two independently set conductances up to 7.5µS, and raw voltage up to 25mV.
        max_i_uA=(15*25+2*7.5*span)/1000
        source.append(dict(abs_raw_mV=25,abs_both_hidden_outputs_mV=span,max_source_current_uA=max_i_uA,
                           max_DC_output_resistance_for_0p50mV_ohm=500/max_i_uA,
                           max_DC_output_resistance_for_0p30mV_ohm=300/max_i_uA))
    # A finite leg mismatch makes the endpoint diagonals differ by (L-R)*Gs/(L+R+Gs).
    s,b=parts(.50)
    unequal=ports(s,b,10.1,9.9)
    np.testing.assert_allclose(unequal[0,0]-unequal[1,1],.2*s/(20+s))
    return dict(sources=sources(),method='Explicit three-node nodal admittance and Schur reduction, µS.',
                anchors=anchors,nodes=NAMES,edges=EDGES,example_weights=[.25,.75,.625,.375,.25,.75],
                example_conductance_matrix_uS=matrix.tolist(),single_edge_current_definition='I_left = D_left*V_left - G_cross*V_right; V relative to REF.',
                allowed_positive_cross_uS=[2.5,7.5],matched_diagonal_per_endpoint_uS=7.5,
                required_banks_uS={'H1':32.5,'H2':32.5,'Z_including_nudge':27.5},
                matched_neuron_equation=banks,hidden_bank_error_controls=variants,
                unequal_0p01_relative_leg_control_uS=unequal.tolist(),clamped_driver_bounds=source,
                all_101_ideal_pairs_reciprocal_and_positive_semidefinite=True)


if __name__=='__main__':
    data=characterize()
    (HERE/'edge_math.json').write_text(json.dumps(data,indent=1)+'\n')
    print(data['anchors'],data['hidden_bank_error_controls'])
