import sys, json, numpy as np
src, outdir = sys.argv[1], sys.argv[2]
s=open(src).read()
def geo(gid):
    i=s.index('<geometry id="%s"'%gid); k=s.index('>',s.index('<float_array',i)); j=s.index('</float_array>',k)
    return np.array(s[k+1:j].split(),float).reshape(-1,3)
def tris(gid):
    i=s.index('<geometry id="%s"'%gid); e=s.index('</geometry>',i); seg=s[i:e]
    out=[]
    for part in seg.split('<triangles')[1:]:
        k=part.index('<p>'); j=part.index('</p>'); out.append(np.array(part[k+3:j].split(),int))
    return np.concatenate(out).reshape(-1,3) if out else np.zeros((0,3),int)
import re
names=dict(re.findall(r'<geometry id="(g\d+)" name="([^"]+)"',s))
P=geo('g0'); xs=np.unique(P[:,0]); ys=np.unique(P[:,1]); H=np.zeros((len(ys),len(xs)))
H[np.searchsorted(ys,P[:,1]),np.searchsorted(xs,P[:,0])]=P[:,2]
def h(x,y):
    fx=np.interp(x,xs,np.arange(len(xs))); fy=np.interp(y,ys,np.arange(len(ys)))
    i=min(int(fx),len(xs)-2); j=min(int(fy),len(ys)-2); tx=fx-i; ty=fy-j
    return H[j,i]*(1-tx)*(1-ty)+H[j,i+1]*tx*(1-ty)+H[j+1,i]*(1-tx)*ty+H[j+1,i+1]*tx*ty
# building roof triangles (2D) for obstacle tests
roofs=[]
for gid,nm in names.items():
    if nm.startswith('osm-') or nm.startswith('overture-'):
        p=geo(gid); t=tris(gid)
        if len(t)==0: continue
        a,b,c=p[t[:,0]],p[t[:,1]],p[t[:,2]]; n=np.cross(b-a,c-a); up=n[:,2]/(np.linalg.norm(n,axis=1)+1e-9)>0.9
        roofs.append(np.stack([a[up],b[up],c[up]],1))
roofs=np.concatenate(roofs)
def in_building(x,y):
    a,b,c=roofs[:,0,:2],roofs[:,1,:2],roofs[:,2,:2]
    v0=b-a; v1=c-a; v2=np.array([x,y])-a
    den=v0[:,0]*v1[:,1]-v1[:,0]*v0[:,1]; den[den==0]=1e-12
    u=(v2[:,0]*v1[:,1]-v1[:,0]*v2[:,1])/den; v=(v0[:,0]*v2[:,1]-v2[:,0]*v0[:,1])/den
    return bool(((u>=0)&(v>=0)&(u+v<=1)).any())
RISE,RUN=0.17,0.28
stairPos=[];stairIdx=[];rampPos=[];rampIdx=[]
def box(c8):
    base=len(stairPos)//1
    stairPos.extend(c8)
    f=[(0,1,2),(0,2,3),(4,6,5),(4,7,6),(0,4,5),(0,5,1),(1,5,6),(1,6,2),(2,6,7),(2,7,3),(3,7,4),(3,4,0)]
    for q in f: stairIdx.extend([base+q[0],base+q[1],base+q[2]])
entries=[]; added=0; skipped=0
railPos=[]; railIdx=[]
allsec={gid:geo(gid).reshape(-1,4,3) for gid,nm in names.items() if nm.startswith('bridge-')}
endpts=[]
for gid,sc in allsec.items():
    for e in (0,len(sc)-1): endpts.append((gid,sc[e,:2,:2].mean(0)))
def near_other_end(pt,gid):
    return any(g!=gid and np.linalg.norm(pt-e)<5 for g,e in endpts)
def rail(p0,p1,z0,z1,out):
    # thin parapet 1.05 m high, 0.15 m thick, offset inward by out-vector
    H=1.05; T=0.15
    a=np.array(p0); b=np.array(p1); o=np.array(out)*T
    base=len(railPos)
    for (pt,z) in ((a,z0),(b,z1)):
        railPos.extend([(*pt,z),(*pt,z+H),(*(pt+o),z+H),(*(pt+o),z)])
    # faces: outer (0,1,5,4), inner (3,7,6,2), top (1,2,6,5), ends
    for q in [(0,4,5,1),(3,2,6,7),(1,5,6,2),(0,1,2,3),(4,7,6,5)]:
        railIdx.extend([base+q[0],base+q[1],base+q[2],base+q[0],base+q[2],base+q[3]])
for gid,nm in names.items():
    if not nm.startswith('bridge-'): continue
    p=geo(gid); sec=p.reshape(-1,4,3)
    ctr=sec[:,:2,:2].mean(1); top=sec[:,0,2]
    length=float(np.sum(np.linalg.norm(np.diff(ctr,axis=0),axis=1)))
    for i in range(len(sec)-1):
        for side,other in ((0,1),(1,0)):
            p0=sec[i,side,:2]; p1=sec[i+1,side,:2]
            mid=(p0+p1)/2
            if near_other_end(mid,gid): continue
            inward=sec[i,other,:2]-sec[i,side,:2]; inward/=np.linalg.norm(inward)+1e-9
            rail(p0,p1,sec[i,side,2],sec[i+1,side,2],inward)
    for end in (0,len(sec)-1):
        nb=1 if end==0 else len(sec)-2
        if len(sec)<2: continue
        c=ctr[end]; d=c-ctr[nb]; d/=np.linalg.norm(d)+1e-9   # outward
        rel=top[end]-h(*c)
        L,R=sec[end,0,:2],sec[end,1,:2]; w=np.linalg.norm(R-L); perp=(R-L)/(w+1e-9)
        if rel<0.8:
            st=c+d*3; entries.append({'id':gid,'x':st[0],'y':st[1],'h':float(h(*st)),'dx':-d[0],'dy':-d[1],'len':length,'stairs':False})
            continue
        # build a straight stair outward until it meets the ground
        z=top[end]; dist=0; steps=[]; ok=True
        while True:
            z-=RISE; dist+=RUN; q=c+d*dist
            gz=h(*q)
            if any(in_building(*(q+perp*o)) for o in (-w/2,0,w/2)): ok=False;break
            if z<=gz+0.02: break
            if dist>40: ok=False;break
            steps.append((dist,z))
        if not ok or not steps: skipped+=1; continue
        added+=1
        for (dd,zz) in steps:
            a=c+d*(dd-RUN); b=c+d*dd
            zlo=min(h(*a),h(*b))-0.3
            pts=[]
            for (pt,zz2) in ((a,zz),(b,zz)):
                pass
            corners=[a-perp*w/2,a+perp*w/2,b+perp*w/2,b-perp*w/2]
            c8=[(x,y,zz) for x,y in corners]+[(x,y,zlo) for x,y in corners]
            box(c8)
        # walking surface: a sloped ramp from deck end to ground
        q=c+d*(steps[-1][0]+RUN); gz=h(*q)
        base=len(rampPos)
        for pt,zz in ((c,top[end]),(q,gz)):
            rampPos.extend([(*(pt-perp*w/2),zz),(*(pt+perp*w/2),zz)])
        rampIdx.extend([base,base+2,base+1, base+1,base+2,base+3])
        rail(c-perp*w/2,q-perp*w/2,top[end],gz,perp)
        rail(c+perp*w/2,q+perp*w/2,top[end],gz,-perp)
        st=q+d*2; entries.append({'id':gid,'x':st[0],'y':st[1],'h':float(h(*st)),'dx':-d[0],'dy':-d[1],'len':length,'stairs':True})
print('stairs added',added,'skipped',skipped,'entries',len(entries))
meta=json.load(open(outdir+'/city.json')); buf=bytearray(open(outdir+'/city.bin','rb').read())
def add(arr):
    off=len(buf); buf.extend(arr.tobytes())
    while len(buf)%4: buf.append(0)
    return [off,arr.size]
def yup(a): a=np.array(a,float); return np.c_[a[:,0],a[:,2],-a[:,1]].astype(np.float32)
# orientation fix so faces point outward: rely on DoubleSide render; collision uses ramp only
meta['layers']['STAIRS']={'pos':add(yup(stairPos)),'idx':add(np.array(stairIdx,np.uint32)),'n':added}
# ramp triangles: ensure up-facing in Y-up after transform
R=yup(rampPos); I=np.array(rampIdx,np.uint32).reshape(-1,3)
a,b,c=R[I[:,0]],R[I[:,1]],R[I[:,2]]; n=np.cross(b-a,c-a); flip=n[:,1]<0; I[flip]=I[flip][:,[0,2,1]]
meta['layers']['RAMPS']={'pos':add(R),'idx':add(I.ravel()),'n':added}
meta['layers']['RAILS']={'pos':add(yup(railPos)),'idx':add(np.array(railIdx,np.uint32)),'n':1}
br=[]
for e in sorted(entries,key=lambda e:e['stairs']):
    br.append({'x':round(e['x'],2),'z':round(-e['y'],2),'y':round(e['h'],2),'yaw':round(float(np.arctan2(-e['dx'],e['dy'])),3),'len':round(e['len'],1),'stairs':e['stairs'],'id':int(e['id'][1:])})
meta['bridges']=sorted(br,key=lambda b:-b['len'])
open(outdir+'/city.bin','wb').write(buf); json.dump(meta,open(outdir+'/city.json','w'))
