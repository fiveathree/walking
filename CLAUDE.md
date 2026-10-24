# 黃大仙漫步 (fiveathree/walking): project notes

A first-person 3D walk through a 1 km × 1 km tile of Wong Tai Sin, Kowloon, centred on 22.34115°N, 114.18933°E. It is a static site: one `index.html` plus data files, with no build step and no backend.

## About the owner

- The owner is not a programmer. Write replies to them in **Cantonese (Traditional Chinese)**, keep them plain, and explain any manual steps they have to do (GitHub, Cloudflare) one at a time from the start, using the current button names.
- All UI text is Cantonese, with English as a secondary line where it helps (place names).
- Commits use the `fiveathree` account. Push to `main`.

## Running it locally

```
python3 -m http.server 8000      # then open http://localhost:8000
```

`fetch()` needs http, so the page will not work if you open the file directly. Three.js `0.169.0` loads from jsDelivr through an import map. There are no other runtime dependencies.

## Files

| Path | What it is |
|---|---|
| `index.html` | The whole app: HTML, CSS and one module script. Its sections are marked `/* ---------- name ---------- */` |
| `data/city.bin` | One binary buffer holding every mesh, as Float32 positions and Uint32 indices |
| `data/city.json` | Index into `city.bin` (`layers.{NAME}.pos/idx = [byteOffset, elementCount]`), plus `trees`, `bridges` (entrances) and `details` (street furniture and labels) |
| `data/satellite.jpg` | 1820² Esri image, draped on the terrain. North is at the top |
| `osm/roads.json`, `osm/pois.json` | Compact OpenStreetMap extract (format below) |
| `tools/convert.py` | urban:EXPORT `.dae` → `city.bin` / `city.json` |
| `tools/stairs.py` | Adds stairs and ramps where a bridge end floats above the street, adds parapets, and builds the bridge entrance list |
| `tools/details.py` | Uses OSM to add road surfaces, markings, covered walkways, lamps, traffic lights, street name plates, bus shelters, canopy posts and labels |
| `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png` | Icons |

### Rebuilding the data

The three scripts must run in this order. Each one appends to `city.bin`, so always start again from `convert.py`; re-running only `details.py` makes the file grow.

```
D=path/to/urban-export_22.3412_114.1893_1000m.dae
python3 tools/convert.py "$D" data
python3 tools/stairs.py  "$D" data
python3 tools/details.py data osm
```

The source `.dae`, `.fbx` and `.jpg` came from https://urban-export.ildar.space/ (SketchUp `.dae` export). They are not in the repo. The owner keeps them in their Downloads folder.

## Coordinates

- Three.js Y-up, in metres. The origin is the tile centre and the tile spans x, z ∈ [-500, 500].
- **+x = east, −z = north** (`z = −northing`). The DAE was Z-up and `convert.py` maps `(x, y, z) → (x, z, −y)`.
- lat/lon ↔ metres: `x = (lon − 114.18933) · 111320 · cos(22.34115°)` and `z = −(lat − 22.34115) · 110574`.
- Camera yaw: forward = `(−sin yaw, 0, −cos yaw)`, so yaw 0 looks north and +yaw turns left.
- OSM data lines up with the model to within about 0.6 m (median), so no offset is applied.

## Mesh layers in `city.json`

`TERRAIN` (68×68 grid, about 15 m spacing), `WATER`, `BRIDGES` (64 decks, built from sections of 4 vertices: top-L, top-R, bottom-R, bottom-L), `B_cls-*` (buildings by class), `STAIRS`, `RAMPS` (invisible walking surface for the stairs), `RAILS`, `ROAD_SURF`, `MARKINGS`, `CANOPY`, and `LINE_*` (polylines from the DAE, which are not used). Trees are 2829 instances stored as `[x, y, z, sx, sz]`.

## How walking works (no physics library)

- **Ground:** `surfaceAt(x, z, maxY, mask)` returns the highest up-facing triangle (normal y > 0.35) in an 8 m grid at or below `maxY`. Kinds are `K_TERRAIN`, `K_BRIDGE` (decks, ramps and rail tops) and `K_BUILDING` (roofs).
- **Walls:** near-vertical triangles become 2D segments with a `[lo, hi]` height range. `pushOutOfWalls` pushes a circle of radius 0.35 out of any wall whose range overlaps `[feet + 0.55, feet + 1.75]`. This lets you walk under bridges and step over kerbs.
- **Each step:** move in x/z, push out of walls, apply gravity, then snap to the surface found from `feet + stepUp (0.6)` downward. While on the ground it also snaps down up to 0.7 m.
- **Bridge entrances:** at load time `tryEntry` test-walks every bridge end for 4 s. Only ends that work are kept in `bridgeList`. About 42 of 64 bridges can be reached on foot. The rest end against buildings in the data.
- **Speeds:** walk 4.5 m/s, brisk 7.5 (double-tap W), run 11 (Shift), fly 30 / 90.

## Controls

WASD to move (A/D strafe). Double-tap W for a brisk walk. Shift to run. Space to jump. ←/→ or Q/E to turn. F to fly (Space up, C down). B for the next bridge. N for night. L to toggle labels. Esc releases the mouse. Click the minimap to teleport (it refuses spots inside buildings). On touch screens there is a left joystick, drag on the right half to look, and buttons for run and jump.

## Rendering notes

- Facades use an 8×8 atlas of floors and windows with world-space UVs (3.6 m × 3.0 m per cell). A matching `emissiveMap` lights about 36% of the windows at night.
- Night mode (`setNight`) changes the sky, fog, lights and exposure, turns on the lamp heads, and shows the additive light pools (`pools`).
- Traffic lights cycle together: green 9 s, amber 2 s, red 9 s.
- Labels are `THREE.Sprite`s that fade in within a range set per kind (`LABEL_STYLE`). `updatePlaces()` ray-marches the view direction to find the building or open space being looked at, which drives the centre tag. It also lists the 3 nearest places in the title panel.
- For smoothness, the camera eases toward the mouse target, pointer-lock spikes over 400 px are ignored, `unadjustedMovement` is requested, and HUD work is spread over 4 frames. The shadow camera moves in 4 m steps, and the pixel ratio adapts to frame time (minimum 0.75).
- The player spawns on 金竹里 Kam Chuk Lane outside 宏美閣 (天宏苑), facing the block: `SPAWN = { x: -257, z: -282, yaw: 0.47 }`.

## OSM extract format (`osm/`)

- `roads.json` is an array of `[typeIdx, lanes, flags, layer, nameIdx, x0, z0, x1, z1, …]`. Flags: 1 oneway, 2 bridge, 4 tunnel, 8 covered. Coordinates are whole metres.
- `pois.json` is `{ names[], types[], pois[] }`. Each poi is `[typeIdx, nameIdx, x, z, src?, levels?]`, where src 1 = area centroid and 2 = building centroid.
- How the data was fetched: in a browser, `GET https://api.openstreetmap.org/api/0.6/map.json?bbox=114.184474,22.336628,114.194186,22.345672`, then converted to the compact form above. Bus-route relations and district boundaries were dropped. overpass-api.de returned 406 to the desktop app's browser.

## Claude.ai artifact copy

A copy is also published as a private claude.ai artifact (https://claude.ai/artifact/6hKQEwFysnc5sSBZLMS5Xi). Artifacts cannot serve `.bin`, so that copy:
- uses only the part of `index.html` between the `<!--ARTIFACT-*-->` markers, because the platform adds its own `<head>`
- loads `data/city.b64.txt` (base64 of `city.bin`) instead of `fetchBuf('data/city.bin')`

If you change `index.html`, keep those markers.

## Deploying

The plan is GitHub Pages: Settings → Pages → Deploy from a branch → `main` / `(root)`, giving `https://fiveathree.github.io/walking/`. The owner has to switch this on themselves, and it had not been confirmed when these notes were written.

## Credits that must stay on the page

Map, street names and landmarks © OpenStreetMap contributors (ODbL) · Overture Maps · terrain Copernicus GLO-30 DEM · satellite Esri · model urban:EXPORT. Check each source's terms before any commercial use.

## Known limits and ideas

- Building shapes and heights come from urban:EXPORT and are simplified. The facade pattern is generic.
- OSM road ribbons overlap at some junctions, and their markings can z-fight slightly.
- About 22 bridges cannot be reached on foot, because their ends run into buildings or podiums.
- OSM `highway=steps` (175 ways) are not modelled yet. They could replace the generated stairs.
- Possible next steps: real stairs from OSM, collision for posts and shelters, a fuller night mode (lit lamps on the terrain), a second district (needs a new export plus OSM data), and a mobile performance pass.
