"""Stairs, parapets and bridge entrances.

Usage: python3 tools/stairs.py model.dae data [osm]
With an osm folder, OpenStreetMap highway=steps become real stairs:
  - steps tagged bridge/layer>0 tilt their (flat) bridge deck so it runs from the deck down to the ground
  - other steps get a flight of steps plus an invisible walking ramp along the OSM line
Bridge ends that still float above the street and have no OSM stair get a straight generated stair.
"""
import sys, json, numpy as np
src, outdir = sys.argv[1], sys.argv[2]
osmdir = sys.argv[3] if len(sys.argv) > 3 else None
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
# terrain height from the actual terrain triangles (the page walks on these, so stairs must match them)
TT=tris('g0'); TC={}
for t in TT:
    gi=np.searchsorted(xs,P[t,0]).min(); gj=np.searchsorted(ys,P[t,1]).min(); TC.setdefault((gi,gj),[]).append(t)
def h(x,y):
    fx=np.interp(x,xs,np.arange(len(xs))); fy=np.interp(y,ys,np.arange(len(ys)))
    i=min(int(fx),len(xs)-2); j=min(int(fy),len(ys)-2)
    for t in TC.get((i,j),()):
        a,b,c=P[t]; den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-12: continue
        u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den; v=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
        if u>=-1e-6 and v>=-1e-6 and u+v<=1+1e-6: return u*a[2]+v*b[2]+(1-u-v)*c[2]
    tx=fx-i; ty=fy-j
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
def roof_at(x,y):
    a,b,c=roofs[:,0,:2],roofs[:,1,:2],roofs[:,2,:2]
    v0=b-a; v1=c-a; v2=np.array([x,y])-a
    den=v0[:,0]*v1[:,1]-v1[:,0]*v0[:,1]; den[den==0]=1e-12
    u=(v2[:,0]*v1[:,1]-v1[:,0]*v2[:,1])/den; v=(v0[:,0]*v2[:,1]-v2[:,0]*v0[:,1])/den
    k=(u>=0)&(v>=0)&(u+v<=1)
    return roofs[k,0,2].max() if k.any() else None
def in_building(x,y): return roof_at(x,y) is not None
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
orig={gid:sc.copy() for gid,sc in allsec.items()}   # before OSM steps tilt any deck
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
def ramp_quad(a,b,za,zb,perp,w):
    base=len(rampPos)
    for pt,zz in ((a,za),(b,zb)):
        rampPos.extend([(*(pt-perp*w/2),zz),(*(pt+perp*w/2),zz)])
    rampIdx.extend([base,base+2,base+1, base+1,base+2,base+3])

# ---------- OpenStreetMap steps ----------
osm_tops=[]      # (x, y, z, bottom x, bottom y, bottom z, dir x, dir y) of OSM stairs that end on a deck
tilted=set(); osm_n={'bridge':0,'ground':0,'flat':0,'indoor':0}
if osmdir:
    R=json.load(open(osmdir+'/roads.json',encoding='utf8')); TY=json.load(open(osmdir+'/pois.json',encoding='utf8'))['types']
    # OSM x/z (z = south) -> DAE x/y (y = north)
    ways=[(TY[r[0]],r[2],r[3],np.c_[np.array(r[5::2],float),-np.array(r[6::2],float)]) for r in R]
    # deck height samples from the original bridge decks
    D=[]
    for sc in orig.values():
        for i in range(len(sc)-1):
            a,b,c,d=sc[i,0],sc[i,1],sc[i+1,1],sc[i+1,0]
            n=max(2,int(np.linalg.norm(d-a)/0.7)+1); m=max(2,int(np.linalg.norm(b-a)/0.7)+1)
            for u in np.linspace(0,1,n):
                l=a+(d-a)*u; r=b+(c-b)*u
                for v in np.linspace(0,1,m): D.append(l+(r-l)*v)
    D=np.array(D)
    def deck_near(p,r=3.0):
        k=np.hypot(D[:,0]-p[0],D[:,1]-p[1])<r
        return D[k,2].max() if k.any() else None
    def polylen(pts): return np.r_[0,np.cumsum(np.linalg.norm(np.diff(pts,axis=0),axis=1))]
    def at(pts,cum,t):
        i=min(max(np.searchsorted(cum,t)-1,0),len(pts)-2); f=(t-cum[i])/max(cum[i+1]-cum[i],1e-9)
        return pts[i]+(pts[i+1]-pts[i])*f
    def project(pts,cum,p):
        """distance along the line of the point nearest p, and how far p is from the line"""
        best=(1e9,0)
        for i in range(len(pts)-1):
            a,b=pts[i],pts[i+1]; ab=b-a; L=np.linalg.norm(ab)
            t=np.clip(np.dot(p-a,ab)/max(L*L,1e-9),0,1); d=np.linalg.norm(a+ab*t-p)
            if d<best[0]: best=(d,cum[i]+t*L)
        return best[1],best[0]
    osm_ids=[i for i,(t,f,l,pts) in enumerate(ways) if t=='steps' and not f&4 and l>=0 and len(pts)>=2
           and np.abs(pts).max()<499]
    # height of each stair end: ground if it meets a street-level way or nothing at all (a dead end is
    # on the pavement), the deck if it meets a bridge, else whatever the stair it joins says
    def touching(p,me):
        out=[]
        for j,(t,f,l,pts) in enumerate(ways):
            if j==me: continue
            d=np.hypot(*(pts-p).T); k=int(d.argmin())
            if d[k]<0.6: out.append((j,k==0 or k==len(pts)-1))
        return out
    endz={}
    for i in osm_ids:
        pts=ways[i][3]
        for e,p in ((0,pts[0]),(1,pts[-1])):
            g=h(*p); dz=deck_near(p); touch=touching(p,i)
            ground=any(ways[j][0]!='steps' and not ways[j][1]&6 and ways[j][2]==0 for j,_ in touch)
            raised=any(ways[j][0]!='steps' and (ways[j][1]&2 or ways[j][2]>0) for j,_ in touch)
            if dz is None or dz<g+1 or ground or not touch: endz[i,e]=g
            elif raised: endz[i,e]=dz
            else: endz[i,e]=None
            endz.setdefault(('t',i,e),[(j,k) for j,k in touch if ways[j][0]=='steps' and k])
    for _ in range(5):
        for i in osm_ids:
            for e in (0,1):
                if endz[i,e] is not None: continue
                p=ways[i][3][-e]
                for j,_ in endz['t',i,e]:
                    if j not in osm_ids: continue
                    for e2 in (0,1):
                        if endz[j,e2] is not None and np.linalg.norm(ways[j][3][-e2]-p)<0.6: endz[i,e]=endz[j,e2]
    for i in osm_ids:
        t,f,l,pts=ways[i]; cum=polylen(pts); L=cum[-1]
        bridge=bool(f&2 or l>0)
        za,zb=[endz[i,e] if endz[i,e] is not None else (deck_near(pts[-e]) if bridge else None) or h(*pts[-e]) for e in (0,1)]
        dh=zb-za
        if abs(dh)<0.25 or L<1: osm_n['flat']+=1; continue
        if bridge and max(za,zb)<h(*pts[0])+1 and max(za,zb)<h(*pts[-1])+1: osm_n['flat']+=1; continue   # up and over: keep the deck
        if not bridge and np.mean([in_building(*at(pts,cum,t)) and roof_at(*at(pts,cum,t))>max(za,zb)+2
                                   for t in np.linspace(0,L,6)])>0.5: osm_n['indoor']+=1; continue
        n=max(2,int(round(abs(dh)/0.16)))
        w=2.4
        if bridge:
            # tilt the deck sections that lie along this stair
            # (only sections near the deck height, so a bridge crossing above or below is left alone)
            widths=[]
            for gid,sc in allsec.items():
                o=orig[gid]
                for k in range(len(sc)):
                    c=o[k,:2,:2].mean(0); tt,dd=project(pts,cum,c)
                    if dd>2.0 or abs(o[k,0,2]-max(za,zb))>1.5: continue
                    sc[k,:,2]=o[k,:,2]+za+dh*tt/L-o[k,0,2]; tilted.add(gid)
                    widths.append(np.linalg.norm(o[k,0,:2]-o[k,1,:2])-0.3)
            if widths: w=min(widths)
            else: bridge=False
        osm_n['bridge' if bridge else 'ground']+=1
        # profile: a tilted deck is a straight slope; on the ground it follows the hill (shifted so the ends
        # meet their heights) and only ever climbs, so steepest parts get the most steps
        ts=np.linspace(0,L,max(2,int(L/0.1)+1))
        if bridge: pz=za+dh*ts/L
        else:
            def across(t):                                     # highest ground across the stair's width
                p=at(pts,cum,t); d=at(pts,cum,min(t+0.5,L))-at(pts,cum,max(t-0.5,0)); d/=np.linalg.norm(d)+1e-9
                q=np.array([-d[1],d[0]])*w/2; return max(h(*p),h(*(p+q)),h(*(p-q)))
            g=np.array([across(t) for t in ts])
            if abs(za-h(*pts[0]))<1e-6: za=g[0]                  # ends on the ground start on its high side too
            if abs(zb-h(*pts[-1]))<1e-6: zb=g[-1]
            dh=zb-za; n=max(2,int(round(abs(dh)/0.16)))
            if abs(dh)<0.25: osm_n['ground']-=1; osm_n['flat']+=1; continue
            pz=g+(za-g[0])*(1-ts/L)+(zb-g[-1])*ts/L
            pz=np.maximum.accumulate(pz) if dh>0 else np.minimum.accumulate(pz)
            pz=za+(pz-pz[0])*dh/((pz[-1]-pz[0]) or 1)
        u=(pz-za)/dh                                                   # 0 at the start, 1 at the end
        cuts=np.interp(np.arange(n+1)/n,u+np.arange(len(u))*1e-9,ts); cuts[0],cuts[-1]=0,L
        for k in range(n):
            top=za+dh*(k+0.5)/n+(0 if bridge else 0.1)            # a little proud of the hillside so it shows
            for a in np.arange(cuts[k],cuts[k+1]-1e-6,2.0):       # long treads are cut so they follow bends
                b=min(a+2.0,cuts[k+1])
                pa,pb=at(pts,cum,a),at(pts,cum,b); d=pb-pa; d/=np.linalg.norm(d)+1e-9; perp=np.array([-d[1],d[0]])
                zlo=top-0.45 if bridge else min(h(*pa),h(*pb),top)-0.3
                corners=[pa-perp*w/2,pa+perp*w/2,pb+perp*w/2,pb-perp*w/2]
                box([(x,y,top) for x,y in corners]+[(x,y,zlo) for x,y in corners])
        if not bridge:
            # walking surface along the profile, cut every metre so it follows the bends
            rs=np.r_[np.arange(0,L,1.0),L]; rz=np.interp(rs,ts,pz)
            for a,b,z0,z1 in zip(rs[:-1],rs[1:],rz[:-1],rz[1:]):
                pa,pb=at(pts,cum,a),at(pts,cum,b); d=pb-pa; d/=np.linalg.norm(d)+1e-9; perp=np.array([-d[1],d[0]])
                ramp_quad(pa,pb,z0,z1,perp,w)
                if abs(dh)>1:
                    rail(pa-perp*w/2,pb-perp*w/2,z0,z1,perp); rail(pa+perp*w/2,pb+perp*w/2,z0,z1,-perp)
        # remember stairs that climb onto a deck, so the generated stair there can be dropped
        for e in (0,1):
            top=(za,zb)[e]; bot=(zb,za)[e]; pt=pts[-e]; pb=pts[-1+e]
            if top-bot>0.8 and deck_near(pt) is not None:
                dv=(pts[1]-pts[0]) if e==1 else (pts[-2]-pts[-1]); dv=dv/(np.linalg.norm(dv)+1e-9)
                osm_tops.append((pt[0],pt[1],top,pb[0],pb[1],float(h(*pb)),dv[0],dv[1]))
    print('osm steps',osm_n,'decks tilted',len(tilted))

# ---------- parapets and entrances on every bridge ----------
endpts=[]
for gid,sc in allsec.items():
    for e in (0,len(sc)-1): endpts.append((gid,sc[e,:2,:2].mean(0)))
def near_other_end(pt,gid):
    return any(g!=gid and np.linalg.norm(pt-e)<5 for g,e in endpts)
covered=0
for gid,sec in allsec.items():
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
        tiltedEnd=gid in tilted and abs(sec[end,0,2]-orig[gid][end,0,2])>0.3
        if rel<0.8:
            st=c+d*3; entries.append({'id':gid,'x':st[0],'y':st[1],'h':float(h(*st)),'dx':-d[0],'dy':-d[1],'len':length,'stairs':bool(tiltedEnd)})
            continue
        # an OSM stair already climbs to this end: start from its foot
        osm=[o for o in osm_tops if np.hypot(o[0]-c[0],o[1]-c[1])<6 and abs(o[2]-top[end])<1.2]
        if osm:
            o=osm[0]; covered+=1
            entries.append({'id':gid,'x':o[3]-o[6]*1.5,'y':o[4]-o[7]*1.5,'h':o[5],'dx':o[6],'dy':o[7],'len':length,'stairs':True})
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
            corners=[a-perp*w/2,a+perp*w/2,b+perp*w/2,b-perp*w/2]
            c8=[(x,y,zz) for x,y in corners]+[(x,y,zlo) for x,y in corners]
            box(c8)
        # walking surface: a sloped ramp from deck end to ground
        q=c+d*(steps[-1][0]+RUN); gz=h(*q)
        ramp_quad(c,q,top[end],gz,perp,w)
        rail(c-perp*w/2,q-perp*w/2,top[end],gz,perp)
        rail(c+perp*w/2,q+perp*w/2,top[end],gz,-perp)
        st=q+d*2; entries.append({'id':gid,'x':st[0],'y':st[1],'h':float(h(*st)),'dx':-d[0],'dy':-d[1],'len':length,'stairs':True})
print('generated stairs',added,'skipped',skipped,'ends served by OSM stairs',covered,'entries',len(entries))
meta=json.load(open(outdir+'/city.json')); buf=bytearray(open(outdir+'/city.bin','rb').read())
# write the tilted decks back into the BRIDGES layer (same size, so it is patched in place)
if tilted:
    L=meta['layers']['BRIDGES']; off,cnt=L['pos']
    Y=np.frombuffer(bytes(buf[off:off+cnt*4]),np.float32).reshape(-1,3).copy()
    O=np.concatenate([orig[g].reshape(-1,3) for g in allsec]); N=np.concatenate([allsec[g].reshape(-1,3) for g in allsec])
    Z=np.c_[Y[:,0],-Y[:,2],Y[:,1]]
    k=np.array([np.linalg.norm(O-p,axis=1).argmin() for p in Z]); err=np.linalg.norm(O[k]-Z,axis=1).max()
    assert err<0.05, 'bridge vertices do not line up with the DAE (%.3f m)'%err
    Y[:,1]=N[k,2]; buf[off:off+cnt*4]=Y.astype(np.float32).tobytes()
def add(arr):
    off=len(buf); buf.extend(arr.tobytes())
    while len(buf)%4: buf.append(0)
    return [off,arr.size]
def yup(a): a=np.array(a,float); return np.c_[a[:,0],a[:,2],-a[:,1]].astype(np.float32)
# orientation fix so faces point outward: rely on DoubleSide render; collision uses ramp only
meta['layers']['STAIRS']={'pos':add(yup(stairPos)),'idx':add(np.array(stairIdx,np.uint32)),'n':added+osm_n['bridge']+osm_n['ground']}
# ramp triangles: ensure up-facing in Y-up after transform
R=yup(rampPos); I=np.array(rampIdx,np.uint32).reshape(-1,3)
a,b,c=R[I[:,0]],R[I[:,1]],R[I[:,2]]; n=np.cross(b-a,c-a); flip=n[:,1]<0; I[flip]=I[flip][:,[0,2,1]]
meta['layers']['RAMPS']={'pos':add(R),'idx':add(I.ravel()),'n':added+osm_n['ground']}
meta['layers']['RAILS']={'pos':add(yup(railPos)),'idx':add(np.array(railIdx,np.uint32)),'n':1}
br=[]
for e in sorted(entries,key=lambda e:e['stairs']):
    br.append({'x':round(e['x'],2),'z':round(-e['y'],2),'y':round(e['h'],2),'yaw':round(float(np.arctan2(-e['dx'],e['dy'])),3),'len':round(e['len'],1),'stairs':e['stairs'],'id':int(e['id'][1:])})
meta['bridges']=sorted(br,key=lambda b:-b['len'])
open(outdir+'/city.bin','wb').write(buf); json.dump(meta,open(outdir+'/city.json','w'))
