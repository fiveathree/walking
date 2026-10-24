"""Add street-level detail from OpenStreetMap to the walking model.

Reads data/city.bin + data/city.json (made by convert.py + stairs.py) and the
compact OSM extracts osm/roads.json + osm/pois.json, then appends:
  layers ROAD_SURF, MARKINGS, CANOPY   (geometry, Y-up metres)
  json   details: signals, lamps, signs, shelters, labels, names
Usage: python3 tools/details.py data osm
"""
import sys, json, math
import numpy as np

data_dir, osm_dir = sys.argv[1], sys.argv[2]
meta = json.load(open(f'{data_dir}/city.json'))
buf = bytearray(open(f'{data_dir}/city.bin', 'rb').read())
# drop layers from a previous run so the script can be re-run
for k in ['ROAD_SURF', 'MARKINGS', 'CANOPY']:
    meta['layers'].pop(k, None)

def arr(o, dt): return np.frombuffer(bytes(buf[o[0]:o[0] + o[1] * 4]), dt)
def layer(k):
    L = meta['layers'][k]
    return arr(L['pos'], np.float32).reshape(-1, 3).astype(float), arr(L['idx'], np.uint32).reshape(-1, 3)

# ---------- surface queries (same idea as the page: grid of up-facing triangles) ----------
CELL = 8.0; HALF = 500
GN = int(math.ceil(2 * HALF / CELL)) + 2
def cell(v): return max(0, min(GN - 1, int(math.floor((v + HALF) / CELL)) + 1))
class Surface:
    def __init__(self):
        self.cells = {}
        self.tris = []
    def add(self, P, I, kind):
        a, b, c = P[I[:, 0]], P[I[:, 1]], P[I[:, 2]]
        n = np.cross(b - a, c - a); ny = n[:, 1] / (np.linalg.norm(n, axis=1) + 1e-12)
        for t in np.nonzero(ny > 0.35)[0]:
            A, B, C = a[t], b[t], c[t]
            u = B - A; v = C - A
            den = u[0] * v[2] - v[0] * u[2]
            if abs(den) < 1e-9: continue
            mnx, mxx = min(A[0], B[0], C[0]), max(A[0], B[0], C[0])
            mnz, mxz = min(A[2], B[2], C[2]), max(A[2], B[2], C[2])
            rec = (A, u, v, den, mnx, mxx, mnz, mxz, kind)
            idx = len(self.tris); self.tris.append(rec)
            for j in range(cell(mnz), cell(mxz) + 1):
                for i in range(cell(mnx), cell(mxx) + 1):
                    self.cells.setdefault(j * GN + i, []).append(idx)
    def at(self, x, z, kinds=None, maxy=1e9):
        best = None; bk = None
        for ti in self.cells.get(cell(z) * GN + cell(x), ()):
            A, u, v, den, mnx, mxx, mnz, mxz, k = self.tris[ti]
            if kinds is not None and k not in kinds: continue
            if x < mnx or x > mxx or z < mnz or z > mxz: continue
            px, pz = x - A[0], z - A[2]
            s = (px * v[2] - v[0] * pz) / den; t = (u[0] * pz - px * u[2]) / den
            if s < -1e-6 or t < -1e-6 or s + t > 1 + 1e-6: continue
            y = A[1] + s * u[1] + t * v[1]
            if y <= maxy and (best is None or y > best): best = y; bk = k
        return best, bk

S = Surface()
S.add(*layer('TERRAIN'), 'T')
S.add(*layer('BRIDGES'), 'B')
if 'RAMPS' in meta['layers']: S.add(*layer('RAMPS'), 'B')
for k in meta['layers']:
    if k.startswith('B_'): S.add(*layer(k), 'H')   # building roofs (for label heights)

def terrain(x, z):
    y, _ = S.at(x, z, ('T',)); return y if y is not None else 0.0
def deck(x, z):
    y, _ = S.at(x, z, ('B',)); return y
def roof(x, z):
    y, _ = S.at(x, z, ('H',)); return y

# ---------- inputs ----------
R = json.load(open(f'{osm_dir}/roads.json'))
PO = json.load(open(f'{osm_dir}/pois.json'))
TYPES = PO['types']; NAMES = PO['names']
def rtype(r): return TYPES[r[0]]
VEH_W = {'trunk': 3.4, 'primary': 3.4, 'secondary': 3.3, 'tertiary': 3.2, 'unclassified': 3.0,
         'residential': 2.9, 'service': 2.6, 'living_street': 2.6, 'pedestrian': 2.5,
         'trunk_link': 3.6, 'secondary_link': 3.6, 'tertiary_link': 3.4}
VEH_LANES = {'trunk': 3, 'secondary': 2, 'tertiary': 2, 'unclassified': 2, 'residential': 2,
             'service': 1, 'pedestrian': 2, 'trunk_link': 1, 'secondary_link': 1, 'tertiary_link': 1}
MAJOR = {'trunk', 'secondary', 'tertiary', 'trunk_link', 'secondary_link', 'unclassified'}

def pts_of(r): return np.array(r[5:], float).reshape(-1, 2)
def densify(P, step):
    out = [P[0]]
    for a, b in zip(P[:-1], P[1:]):
        L = np.linalg.norm(b - a); n = max(1, int(math.ceil(L / step)))
        for i in range(1, n + 1): out.append(a + (b - a) * i / n)
    return np.array(out)
def inside(p, m=0): return abs(p[0]) < HALF - m and abs(p[1]) < HALF - m

geo = {'ROAD_SURF': ([], []), 'MARKINGS': ([], []), 'CANOPY': ([], [])}
def quad(layer_name, a, b, c, d):
    P, I = geo[layer_name]; base = len(P)
    P.extend([a, b, c, d]); I.extend([base, base + 2, base + 1, base, base + 3, base + 2])

def height(x, z, on_bridge, lift):
    if on_bridge:
        d = deck(x, z)
        if d is not None: return d + lift
    return terrain(x, z) + lift

def ribbon(layer_name, P, off0, off1, on_bridge, lift, uv_len=False):
    """Strip between lateral offsets off0..off1 along polyline P (2D, x/z)."""
    if len(P) < 2: return
    n = len(P)
    tang = np.zeros_like(P)
    tang[1:-1] = P[2:] - P[:-2]; tang[0] = P[1] - P[0]; tang[-1] = P[-1] - P[-2]
    tang /= (np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9)
    nor = np.c_[-tang[:, 1], tang[:, 0]]
    L, Rr = P + nor * off0, P + nor * off1
    PP, II = geo[layer_name]
    base = len(PP)
    for i in range(n):
        for q in (L[i], Rr[i]):
            PP.append((q[0], height(q[0], q[1], on_bridge, lift), q[1]))
    for i in range(n - 1):
        a, b, c, d = base + 2 * i, base + 2 * i + 1, base + 2 * i + 3, base + 2 * i + 2
        II.extend([a, d, b, b, d, c])

def dashes(P, step_on, step_off):
    """Split polyline into dash segments."""
    out = []; acc = 0.0; on = True; cur = [P[0]]
    for a, b in zip(P[:-1], P[1:]):
        L = np.linalg.norm(b - a); pos = 0.0
        while pos < L - 1e-9:
            rem = (step_on if on else step_off) - acc
            take = min(rem, L - pos)
            pos += take; acc += take
            pt = a + (b - a) * pos / L
            if on: cur.append(pt)
            if acc >= (step_on if on else step_off) - 1e-9:
                if on and len(cur) > 1: out.append(np.array(cur))
                on = not on; acc = 0.0; cur = [pt]
    if on and len(cur) > 1: out.append(np.array(cur))
    return out

roads_for_props = []   # (P, width, name, kind, bridge)
canopy_posts = []
for r in R:
    t = rtype(r)
    flags, layer_n = r[2], r[3]
    if flags & 4 or layer_n < 0: continue              # tunnels / underground
    P = pts_of(r)
    if len(P) < 2 or np.linalg.norm(P[-1] - P[0]) < 0.5 and len(P) == 2: continue
    bridge = bool(flags & 2)
    if t in VEH_W:
        lanes = r[1] or VEH_LANES.get(t, 2)
        w = max(3.2, lanes * VEH_W[t])
        D = densify(P, 3.0)
        ribbon('ROAD_SURF', D, -w / 2, w / 2, bridge, 0.07)
        roads_for_props.append((D, w, r[4], t, bridge, lanes, bool(flags & 1)))
        # markings
        if t in MAJOR or lanes >= 2:
            if t in ('trunk', 'secondary', 'trunk_link', 'secondary_link'):
                for e in (-w / 2 + 0.35, w / 2 - 0.35):
                    ribbon('MARKINGS', D, e - 0.07, e + 0.07, bridge, 0.1)
            if lanes >= 2:
                for k in range(1, lanes):
                    off = -w / 2 + k * w / lanes
                    for seg in dashes(D, 3.0, 6.0):
                        if len(seg) >= 2: ribbon('MARKINGS', seg, off - 0.08, off + 0.08, bridge, 0.1)
    elif t == 'footway' and (flags & 8):
        # covered walkway: roof 2.9 m above the walking surface
        D = densify(P, 2.0)
        PP, II = geo['CANOPY']
        tang = np.gradient(D, axis=0); tang /= (np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9)
        nor = np.c_[-tang[:, 1], tang[:, 0]]
        base = len(PP); w = 1.9
        hs = [height(p[0], p[1], bridge, 0) + 2.9 for p in D]
        for i, p in enumerate(D):
            for s in (-w, w):
                q = p + nor[i] * s
                PP.append((q[0], hs[i], q[1]))
        for i in range(len(D) - 1):
            a, b, c, d = base + 2 * i, base + 2 * i + 1, base + 2 * i + 3, base + 2 * i + 2
            II.extend([a, d, b, b, d, c])
        canopy_posts.append((D, nor, hs))

# ---------- props from point features ----------
def nearest_road(x, z, maxd=9.0):
    best = None
    for (D, w, nm, t, br, lanes, ow) in roads_for_props:
        if br: continue
        d = np.linalg.norm(D - [x, z], axis=1); i = int(d.argmin())
        if d[i] < maxd and (best is None or d[i] < best[0]):
            j = min(i + 1, len(D) - 1); k = max(i - 1, 0)
            tg = D[j] - D[k]; tg /= (np.linalg.norm(tg) + 1e-9)
            best = (d[i], D[i], tg, w)
    return best

details = {'signals': [], 'lamps': [], 'signs': [], 'shelters': [], 'labels': [], 'names': [], 'stops': []}
# canopy support posts every ~7 m on both edges (bottom = walking surface, top = roof)
details['posts'] = []
for D, nor, hs in canopy_posts:
    acc = 7.0
    for i in range(len(D)):
        if i > 0: acc += float(np.linalg.norm(D[i] - D[i - 1]))
        if acc < 7.0 and i != len(D) - 1: continue
        acc = 0.0
        for sgn in (-1, 1):
            q = D[i] + nor[i] * sgn * 1.75
            if not inside(q, 1): continue
            top = hs[i]
            details['posts'].append([round(q[0], 2), round(top - 2.9, 2), round(q[1], 2), 0])
name_ix = {}
def nm_index(s):
    if s not in name_ix: name_ix[s] = len(details['names']); details['names'].append(s)
    return name_ix[s]
def yaw_of(tg): return math.atan2(-tg[0], -tg[1])   # three.js: rotation.y so local -Z points along tg

zebra_done = []
for p in PO['pois']:
    ty = TYPES[p[0]]; x, z = p[2], p[3]
    if not inside((x, z), 2): continue
    if ty == 'highway=crossing':
        nr = nearest_road(x, z, 6)
        if not nr: continue
        _, c, tg, w = nr
        if any(np.hypot(c[0] - a, c[1] - b) < 4 for a, b in zebra_done): continue
        zebra_done.append((c[0], c[1]))
        nor = np.array([-tg[1], tg[0]])
        nbar = max(3, int(w / 1.1))
        for k in range(nbar):
            off = -w / 2 + 0.55 + k * (w - 1.1) / max(1, nbar - 1)
            a = c + nor * (off - 0.25) - tg * 1.6; b = c + nor * (off + 0.25) - tg * 1.6
            cc = c + nor * (off + 0.25) + tg * 1.6; d = c + nor * (off - 0.25) + tg * 1.6
            ys = [terrain(q[0], q[1]) + 0.11 for q in (a, b, cc, d)]
            quad('MARKINGS', (a[0], ys[0], a[1]), (b[0], ys[1], b[1]), (cc[0], ys[2], cc[1]), (d[0], ys[3], d[1]))
    elif ty == 'highway=traffic_signals':
        nr = nearest_road(x, z, 8)
        if not nr: continue
        _, c, tg, w = nr
        nor = np.array([-tg[1], tg[0]])
        for s in (-1, 1):
            q = c + nor * s * (w / 2 + 0.9)
            if not inside(q, 1): continue
            # light faces oncoming traffic on that side
            details['signals'].append([round(q[0], 2), round(terrain(q[0], q[1]), 2), round(q[1], 2), round(yaw_of(tg * -s), 3)])
    elif ty in ('amenity=shelter', 'public_transport=platform', 'highway=bus_stop'):
        nr = nearest_road(x, z, 12)
        if not nr: continue
        _, c, tg, w = nr
        nor = np.array([-tg[1], tg[0]])
        side = 1 if np.dot([x - c[0], z - c[1]], nor) >= 0 else -1
        q = c + nor * side * (w / 2 + 1.6)
        if any(np.hypot(q[0] - s[0], q[1] - s[2]) < 6 for s in details['shelters']): continue
        roof_y = roof(q[0], q[1]); ty0 = terrain(q[0], q[1])
        if roof_y is not None and roof_y > ty0 + 1: continue        # would sit inside a building
        nm = NAMES[p[1]] if p[1] >= 0 else ''
        details['shelters'].append([round(q[0], 2), round(ty0, 2), round(q[1], 2),
                                    round(math.atan2(nor[0] * side, nor[1] * side), 3), nm_index(nm) if nm else -1])

# street lamps every 32 m along vehicle roads, alternating sides on wide roads
for (D, w, nm, t, br, lanes, ow) in roads_for_props:
    if t in ('service',) and w < 4: continue
    acc = 16.0; side = 1
    for a, b in zip(D[:-1], D[1:]):
        L = np.linalg.norm(b - a); acc += L
        if acc < 32: continue
        acc = 0
        tg = (b - a) / (L + 1e-9); nor = np.array([-tg[1], tg[0]])
        q = b + nor * side * (w / 2 + 0.6)
        if not inside(q, 2): continue
        y = deck(q[0], q[1]) if br else None
        if br and y is None: continue
        y = y if y is not None else terrain(q[0], q[1])
        r_ = roof(q[0], q[1])
        if r_ is not None and r_ > y + 1: continue
        details['lamps'].append([round(q[0], 2), round(y, 2), round(q[1], 2), round(math.atan2(-nor[0] * side, -nor[1] * side), 3)])
        if w > 9: side = -side

# street name signs: every ~110 m along each named vehicle road, on the left kerb
by_name = {}
for (D, w, nm, t, br, lanes, ow) in roads_for_props:
    if nm < 0 or br: continue
    by_name.setdefault(nm, []).append((D, w))
for nm, parts in by_name.items():
    text = NAMES[nm]
    placed = []
    for D, w in parts:
        acc = 40.0
        for a, b in zip(D[:-1], D[1:]):
            L = np.linalg.norm(b - a); acc += L
            if acc < 110: continue
            tg = (b - a) / (L + 1e-9); nor = np.array([-tg[1], tg[0]])
            q = b + nor * (w / 2 + 1.0)
            if not inside(q, 3) or any(np.hypot(q[0] - s[0], q[1] - s[1]) < 70 for s in placed): continue
            r_ = roof(q[0], q[1]); y = terrain(q[0], q[1])
            if r_ is not None and r_ > y + 1: continue
            acc = 0; placed.append(q)
            details['signs'].append([round(q[0], 2), round(y, 2), round(q[1], 2), round(math.atan2(-tg[0], -tg[1]), 3), nm_index(text)])

# ---------- labels ----------
def kind_of(ty, flag):
    if ty.startswith('railway=station') or ty == 'public_transport=station' or ty == 'railway=stop': return 'station'
    if 'place_of_worship' in ty or 'temple' in ty or ty.startswith('historic'): return 'temple'
    if 'school' in ty or 'kindergarten' in ty: return 'school'
    if ty.startswith('leisure') or ty.startswith('landuse=plant') or 'fountain' in ty: return 'park'
    if ty.startswith('shop') or ty in ('amenity=restaurant', 'amenity=fast_food', 'amenity=cafe', 'amenity=bank'): return 'shop'
    if ty.startswith('building') or ty.startswith('landuse=residential'): return 'estate'
    return 'place'
seen = []
for p in PO['pois']:
    if p[1] < 0: continue
    ty = TYPES[p[0]]; x, z = p[2], p[3]; flag = p[4] if len(p) > 4 else 0
    if not inside((x, z), 4): continue
    if ty in ('public_transport=platform', 'public_transport=stop_position', 'public_transport=stop_area', 'highway=bus_stop',
              'amenity=parking', 'highway=elevator'): continue
    text = NAMES[p[1]]
    if not text: continue
    zh = text.split(' ')[0] if any('一' <= ch <= '鿿' for ch in text) else text
    en = text[len(zh):].strip() if zh != text else ''
    k = kind_of(ty, flag)
    if flag == 2 and k == 'estate' and (len(p) < 6 or p[5] < 8): k = 'minor'   # low buildings: only label up close
    if ty.startswith('railway=stop') or ty == 'public_transport=station': k = 'station'
    if any(zh == s[0] and np.hypot(x - s[1], z - s[2]) < 120 for s in seen): continue
    seen.append((zh, x, z))
    g = terrain(x, z); r_ = roof(x, z)
    y = (r_ + 4) if (r_ is not None and r_ > g + 2) else g + 7
    details['labels'].append([zh, en, round(x, 1), round(y, 1), round(z, 1), k])

# ---------- write ----------
def add(a):
    off = len(buf); buf.extend(a.tobytes())
    while len(buf) % 4: buf.append(0)
    return [off, int(a.size)]
for k, (P, I) in geo.items():
    if not P: continue
    meta['layers'][k] = {'pos': add(np.array(P, np.float32)), 'idx': add(np.array(I, np.uint32)), 'n': 1}
meta['details'] = details
open(f'{data_dir}/city.bin', 'wb').write(buf)
json.dump(meta, open(f'{data_dir}/city.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print({k: len(v[0]) for k, v in geo.items()}, {k: len(v) for k, v in details.items()})
