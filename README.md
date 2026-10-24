# 黃大仙漫步

用第一身視角喺香港黃大仙一帶（22.34115°N, 114.18933°E，1 公里 × 1 公里）周圍行嘅 3D 網頁。

- 腳跟住地形高低行，上斜落斜都得
- 天橋可以由橋頭直接行上去；兩頭都懸空嘅橋頭會自動補返樓梯；橋邊有欄杆
- 唔會穿過建築物
- 飛行模式、小地圖點擊瞬間移動、「去天橋」逐條天橋跳過去
- 手機有虛擬搖桿
- OpenStreetMap 街道細節：瀝青路面同行車線、斑馬線、會轉燈嘅交通燈、街燈、雙語街名牌、巴士站上蓋、有蓋行人天橋
- 地名標籤：港鐵站、黃大仙祠、學校、公園、屋邨大廈名（行近先出現，按 L 收起）
- 夜晚模式（按 N）：大廈亮燈、街燈光暈

## 操作

| 按鍵 | 作用 |
|---|---|
| W A S D / 方向鍵 | 行 |
| 滑鼠 | 轉頭望 |
| Shift | 跑 |
| 空白鍵 | 跳（飛行時：上升） |
| C | 飛行時下降 |
| F | 飛行模式開／關 |
| B | 去下一條天橋 |
| N | 日間／夜晚 |
| L | 顯示／收起地名 |

## 檔案

- `index.html` — 成個網頁（Three.js 由 CDN 載入）
- `data/city.bin`、`data/city.json` — 由 urban:EXPORT 嘅 .dae 模型轉出嚟嘅精簡資料
- `data/satellite.jpg` — 地面衛星圖
- `osm/roads.json`、`osm/pois.json` — 由 OpenStreetMap 抽出嘅道路同地標（已轉成以模型中心為原點嘅米座標）
- `tools/convert.py`、`tools/stairs.py`、`tools/details.py` — 轉換腳本（換第二個地區時用）

換地區：喺 urban:EXPORT 下載新嘅 SketchUp (.dae) 同 Satellite (.jpg)，然後：

```
python3 tools/convert.py 新模型.dae data
python3 tools/stairs.py 新模型.dae data
python3 tools/details.py data osm
cp 新衛星圖.jpg data/satellite.jpg
```

（`osm/` 嘅資料要由 OpenStreetMap API 重新下載該地區，再轉成同樣格式。）

（記得改 `index.html` 入面嘅標題同 `ORIGIN` 座標。）

## 資料來源

地圖 © OpenStreetMap 貢獻者（ODbL）· Overture Maps · 地形 Copernicus GLO-30 DEM © DLR, Airbus, ESA · 衛星圖 Esri · 模型由 [urban:EXPORT](https://urban-export.ildar.space/) 生成。商業用途前請先查閱各來源嘅使用條款。
