import sys, json, re, numpy as np, xml.etree.ElementTree as ET
src, outdir = sys.argv[1], sys.argv[2]
ns={'c':'http://www.collada.org/2005/11/COLLADASchema'}
root=ET.parse(src).getroot()
def q(t): return '{%s}%s'%(ns['c'],t)
geoms={}
for g in root.iter(q('geometry')):
    m=g.find(q('mesh'))
    fa=m.find('.//'+q('float_array'))
    pos=np.array(fa.text.split(),dtype=np.float64).reshape(-1,3)
    tris=[];lines=[]
    for t in m.findall(q('triangles')):
        p=t.find(q('p'))
        if p is not None and p.text: tris.append(np.array(p.text.split(),dtype=np.int64))
    for t in m.findall(q('lines')):
        p=t.find(q('p'))
        if p is not None and p.text: lines.append(np.array(p.text.split(),dtype=np.int64))
    geoms[g.get('id')]=(g.get('name'),pos,np.concatenate(tris) if tris else None,np.concatenate(lines) if lines else None)
libnodes={n.get('id'):n for n in root.find(q('library_nodes'))}
layers={}  # name -> list of (pos, idx)
treeM=[]
def mat(n):
    m=n.find(q('matrix'))
    return np.array(m.text.split(),dtype=float).reshape(4,4) if m is not None else np.eye(4)
def walk(n,M,layer):
    M=M@mat(n)
    for ig in n.findall(q('instance_geometry')):
        name,pos,tri,lin=geoms[ig.get('url')[1:]]
        im=ig.find('.//'+q('instance_material'))
        matname=im.get('target')[1:] if im is not None else 'white'
        p=(np.c_[pos,np.ones(len(pos))]@M.T)[:,:3]
        if tri is not None:
            key=layer if layer!='TERRAIN' else 'TERRAIN'
            if layer.startswith('BUILDINGS'): key='B_'+matname
            layers.setdefault(key,[]).append((p,tri))
        if lin is not None:
            layers.setdefault('LINE_'+layer,[]).append((p,lin))
    for inn in n.findall(q('instance_node')):
        if inn.get('url')=='#TREE_DEF': treeM.append(M)
    for c in n.findall(q('node')):
        walk(c,M,layer)
vs=root.find('.//'+q('visual_scene'))
for top in vs.findall(q('node')):
    walk(top,np.eye(4),top.get('name'))
buf=bytearray(); meta={'layers':{}}
def add(arr):
    off=len(buf); b=arr.tobytes(); buf.extend(b)
    while len(buf)%4: buf.append(0)
    return [off,arr.size]
for k,parts in layers.items():
    P=[];I=[];base=0
    for p,idx in parts:
        P.append(p);I.append(idx+base);base+=len(p)
    P=np.concatenate(P);I=np.concatenate(I)
    # Z-up -> Y-up : (x,y,z)->(x,z,-y)
    Y=np.c_[P[:,0],P[:,2],-P[:,1]].astype(np.float32)
    meta['layers'][k]={'pos':add(Y),'idx':add(I.astype(np.uint32)),'n':len(parts)}
    print(k,len(parts),len(Y),len(I))
T=[]
for M in treeM:
    sx,sy,sz=M[0,0],M[1,1],M[2,2]; x,y,z=M[0,3],M[1,3],M[2,3]
    T.append([x,z,-y,sx,sz])
meta['trees']=add(np.array(T,dtype=np.float32).ravel())
tg=[g for g in geoms.values() if g[0]=='TREE'][0]
meta['treeGeom']={'pos':add(np.c_[tg[1][:,0],tg[1][:,2],-tg[1][:,1]].astype(np.float32)),'idx':add(tg[2].astype(np.uint32))}
print('trees',len(T))
open(outdir+'/city.bin','wb').write(buf)
json.dump(meta,open(outdir+'/city.json','w'))
print('bytes',len(buf))
# ---- per-bridge entry points ----
def terrain_h():
    P=layers['TERRAIN'][0][0]
    xs=np.unique(P[:,0]); ys=np.unique(P[:,1]); H=np.zeros((len(ys),len(xs)))
    H[np.searchsorted(ys,P[:,1]),np.searchsorted(xs,P[:,0])]=P[:,2]
    def h(x,y):
        fx=np.interp(x,xs,np.arange(len(xs))); fy=np.interp(y,ys,np.arange(len(ys)))
        i=min(int(fx),len(xs)-2); j=min(int(fy),len(ys)-2); tx=fx-i; ty=fy-j
        return H[j,i]*(1-tx)*(1-ty)+H[j,i+1]*tx*(1-ty)+H[j+1,i]*(1-tx)*ty+H[j+1,i+1]*tx*ty
    return h
h=terrain_h(); br=[]
for p,idx in layers['BRIDGES']:
    xy=p[:,:2]; c=xy.mean(0); d=np.linalg.norm(xy-c,axis=1); A=xy[d.argmax()]
    B=xy[np.linalg.norm(xy-A,axis=1).argmax()]; L=np.linalg.norm(B-A)
    def end(E):
        near=p[np.linalg.norm(xy-E,axis=1)<4]; top=near[:,2].max(); return top, top-h(*E)
    ta,da=end(A); tb,db=end(B)
    if db<da: A,B,ta,tb,da,db=B,A,tb,ta,db,da
    # step from A inward along A->B by 2m
    u=(B-A)/max(L,1e-6); S=A+u*2
    br.append({'len':round(float(L),1),'maxH':round(float((p[:,2]-np.array([h(x,y) for x,y in xy])).max()),1),
      'x':round(float(S[0]),2),'z':round(float(-S[1]),2),'y':round(float(max(h(*S),ta))+0.5,2),
      'yaw':round(float(np.arctan2(-u[0],u[1])) ,3)})
meta['bridges']=sorted(br,key=lambda b:-b['len'])
json.dump(meta,open(outdir+'/city.json','w'))
print(meta['bridges'][:6])
