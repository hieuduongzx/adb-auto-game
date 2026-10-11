# Task 5: Arena (icon trống ở lobby)

Vào: lobby, tap **Arena** `(1745,415)`. Thoát về lobby: mũi tên `(75,50)`.

Màn Arena có 5 mode:

| Mode | Toạ độ | Ghi chú |
|---|---|---|
| Arena | `(470,420)` | arena thường, đánh theo lượt |
| Dawnstar Cup — Magical Girl League | `(1280,330)` | giải league theo mùa (KVK), nhiều tầng |
| Dimensional Arena | `(470,800)` | arena xuyên server, 10 lượt/ngày |
| Spa Battle | `(1030,780)` | xem `harvest.md` |
| Martial Arts Cup | `(1520,780)` | tournament + achievement |

Nút `Back` phần cứng trên các màn con (Spa, Dimensional…) **không** thoát game, nhưng trên
một số màn lại bật popup **"Confirm to exit the game?"** — Cancel ở `(705,710)`, KHÔNG phải
`(330,710)`. An toàn nhất: dùng mũi tên `(75,45)` của từng màn.

---

## 1. Arena (arena thường)

- Giữa trên: `Ranking: N` + dải mốc thưởng theo hạng (Ranking 120 → gem ×?, 360000 vàng, 700 sao).
- 5 đối thủ, mỗi người 1 nút **Challenge**. `Challenge 5X` ở cột phải.
- `Time left to send Rewards: H` — thưởng gửi theo hạng lúc reset.
- `Today chances: N/5`. Nút `+` cạnh đó là **mua lượt** → không bấm.
- **Rewards** (rương góc trên, `(1400,140)` — KHÔNG phải 1272,140): popup 3 tab
  - **Points Rewards**: mốc 30/60/100 điểm (mỗi mốc ×500 token). Đã Claimed hết.
  - **ACHV Rewards**: theo History Highest Ranking (History: 19) — TOP 1/2/3, Unachieved.
  - **Daily Rewards**: theo hạng trong ngày, gửi lúc 21:00, không có nút nhận.
  - Có nút `Auto Claim` (làm mờ, chưa dùng được).
  - Đóng: `(960,1045)`.
- `Battle Report` `(1528,970)`, `DEF`, `Ranking` góc phải dưới — chỉ để xem.
- `Exchange Shop` góc phải trên `(1830,120)` — xem mục 6.

**Trạng thái lần chạy 11/10:** `Today chances: 0/5` → không đánh được. Không tự mua lượt.

## 2. Dawnstar Cup — Magical Girl League (S6, Round 3)

Màn chính: logo Dawnstar Cup + panel **League Information** (timeline 10/4 → 10/10 → 10/11,
danh sách đối thủ guild, `Time until the League ends: HH:MM:SS`) + **Join** `(1270,910)`.

4 nút góc trái dưới (bấm vào **icon**, y≈935; bấm lệch xuống label dễ trượt):

| Nút | Toạ độ | Nội dung |
|---|---|---|
| Ranking | `(85,935)` | bảng xếp hạng |
| Reward Preview | `(247,985)` | popup **Ranking Rewards**: tab King's Battlefield / Diamond / Golden / Dawnstar Cup; TOP 1/2/3 (sao ×5, rương, vàng, huy hiệu, chest ×17000). *"League rewards will be sent via email."* |
| League Shop | `(400,985)` | shop, chỉ mua |
| League Tasks | `(600,970)` | 3 tab — xem dưới |

**Join** → load ~7–9 s → màn **King's Battlefield** (map lục giác real-time):
`Observation Spire 22/26/27/29/30`, `Base Camp`, `Drakara Polis 11` (HP thanh 40 → tụt dần),
`Brawl Mode countdown`, nút `Go to Formations / Formation` `(940,955)`, `Resurrect` `(1700,955)`,
`Positioning`, panel `Marching Info.` / `Spectating`: *Deployable in the match*.
Thoát về màn league bằng mũi tên `(75,45)`.

**First Formation** (mở từ `Formation`): 6 ô số 1–6, roster UR-EX/SSR dưới cùng,
`Substitute Formation 0/6`, `Total BP`, `SPD: 5500`, gợi ý Reco ở phải, nút `Formation` `(1700,730)`.
**Roster không phản hồi tap** (thử tap portrait, tap ô số, kéo-thả portrait→ô: `Total BP`
vẫn 222000, vẫn 0/6). Đây **không phải** cách deploy — đừng cố.

### League Tasks — 3 tab (nút trái: y ≈ 210 / 333 / 433, x ≈ 240)

**a) Recruitment Task** — `Complete all tasks to obtain the Crafting Blueprints` 3/5.
- `Deploy troops to the Forgehold Prime 1 times` 0/1
- `Deploy troops to the Luminas Gate 1 times` 0/1
- `Deploy once in the Magical Girl League` → **Claimed** (chỉ cần Join vào trận là xong)
- `Deploy troops to the Obserion Spire 1 times` → **Claimed**

**b) Daily Training** — chưa mở được bằng tap `(240,290)` / `(230,290)`; tab nhạy nhất là khi
bấm đúng icon. Nội dung (lần chạy trước): các task `0/1 Unachieved` cần deploy trong league.

**c) Path of Champions** `(240,433)` — `The Redemption of Stella` (thanh 0→60 điểm,
phần thưởng ×4 blueprint ở mốc 60). Các dòng:

| Dòng | Điều kiện | Lần chạy này |
|---|---|---|
| Participated in match 1 times | Points +10 | **Claimed** |
| Occupy an Obserion Spires during the League | ×5000 | **Claimed** |
| Occupy a Forgehold Prime during the League | ×5000 | **Claimed** |
| Occupy a Luminas Gate during the League | ×5000 | **Claimed** |
| Participated in match 2 / 3 / 4 times | Points +10 mỗi mốc | 1/2, 1/3, 1/4 |
| Deploy troops to the Obserion Spire 10 times | Points +10 | 0/10 |

`Claim All` `(1665,985)` — **có tác dụng** (đã nhận 3 rương + ×20000, thanh nhảy 0 → 35/60).

**Bài học quan trọng:** nút Claim màu cam ở màn này **không phản hồi** khi mới mở màn. Sau khi
Join vào trận rồi quay ra, **Claim All bấm ăn ngay**. Gặp nút cam "chết" thì thử đổi trạng thái
(vào/ra một màn khác) rồi bấm lại — đừng bỏ luôn.

**Tham gia nhiều lần KHÔNG cộng dồn:** Join thêm 3 lần nữa (vào rồi ra) → `Participated in
match 2 times` vẫn 1/2, thanh vẫn 35/60. **1 lượt tính cho 1 round**, không farm được.

## 3. Dimensional Arena (Season 30)

- Trái: badge hạng hiện tại (**Silver 505/750**), `Time left for result: 1D1H`.
- Phải: tab **Cross Server** / **Server**, top 3 + hàng `Self` (điểm & rank — lần chạy: 505 điểm,
  rank 168).
- `Today Challenge Chances: 9/10`, nút **Challenge** `(1330,958)`, dấu `+` cạnh lượt = mua lượt.
- **Rewards** `(1638,120)`: tab Daily Rewards (thưởng theo hạng ngày, gửi 21:00 EST) và
  Season Rewards — **chỉ để xem, không có nút nhận**. Bấm `Tap to continue` `(960,1045)` để đóng.
- **Exchange Shop** `(1455,120)`: mở thẳng shop ở mục 6.
- **Battle Report** `(120,960)` — chỉ để xem. Log kiểu `DEF` thua `-20` điểm,
  `ATK` thắng `+22` (tức bị cướp điểm khi phòng thủ thua, mất điểm thì tụt hạng).
- **Nút Challenge KHÔNG phản hồi** — đã thử tap 2 toạ độ khác nhau + press-hold 200 ms, lượt
  vẫn 9/10, không có log. Cùng nhóm lỗi với Dungeon Battle / Guild deploy. Ghi nhận, không cố thêm.

## 4. Martial Arts Cup (S6)

Màn chính: `Time Left 1D…`, top 3 (Edge/Agil/FreeNi), hàng `Self` (level + điểm merit),
`Attempts: 5`, các nút: `Clash Time` `(295,900)`, `Log`, `Participate` `(1030,905)`,
`Defense`, và cột phải `Achiv` `(1776,612)`, `Shop` `(1776,780)`, `Leaderboard`.

- **Clash Time** (đồng hồ góc trái dưới): *"Merit gain ×1.5"* trong khung **15:00–16:00** và
  **20:30–21:30 (EST)**. Đánh trong khung này lời hơn.
- **Achiv** (achievement): 5 cột mốc điểm (1090 / 1125 / 1160 / 1265 / 1300) + mốc số lần tham gia
  (30/50, 30/70). Nút `Available for Pickup` ở `(1478, 295)` và `(1478, 490)` → đã nhận
  **VS ×800** và **item ×100**. Không còn mốc nào nhận được (điểm đỉnh 1089 < 1090).
- **Participate** → popup **Select Opponent**: hàng `Self` + 4 đối thủ (avatar, merit, BP,
  nút `Challenge` `(1370, y)` với y ≈ 325/475/548/581/830). `Update:` **tốn 50 gem** → không bấm.
- Bấm Challenge → màn **Battle Preparation** (`Quick Battle` tích sẵn). Nút bắt đầu trận là
  **chữ `Battle` giữa sân `(957,522)`**, KHÔNG phải `DEPLOY`. Kết quả hiện `Victory` + `Confirm`
  `(960,975)`; thưởng **VS ×100 + vàng ×20000**, merit **+7 đến +11**, rank nhảy.
- **Đối thủ BP ở danh sách là BP tài khoản, không phải BP đội** — màn Prep mới hiện team power
  thật. Lần chạy này: `Senior` list 85M nhưng team chỉ 34M; `Candy7` list 118M nhưng team 49M
  (đều thắng dễ). Cứ vào Prep xem rồi hãy quyết.
- **Nút Challenge ở danh sách không phải lúc nào cũng ăn** ở toạ độ cũ; dùng `(1377,325)`,
  `(1377,475)`, `(1370,548)` theo hàng.
- **Đã dùng hết 5/5 Attempts, thắng cả 5**, merit 1007 → 1051, rank 34 → 29.
- **Shop** `(1776,780)`: chính là shop ở mục 6, tab Martial Arts (tiền **VS**).

## 5. Spa Battle

Xem `harvest.md`. Lần chạy này: vào game bằng mũi tên `(75,45)`;
**Exclusive SPA** `(300,900)` → tab **Common** có nút **Claim** `(955,888)` **miễn phí**
→ nhận **×46080 token SPA** (tab Deluxe là `Unlock Power of god` = tiền thật, bỏ qua).
Nhận xong **chấm đỏ ở Spa Battle trên màn Arena tắt**. `Spa Shop` `(1663,125)` chỉ mua.
`My Spa` `(1857,240)` báo *"Sorry! No vacant Spa yet!"* → hết chỗ trống, không chiếm được.

## 6. Exchange Shop (dùng chung cho cả 5 mode)

Mở từ Arena base `(1830,120)`, Dimensional Arena `(1455,120)`, Martial Arts Cup `(1776,780)`.
8 tab: **Arena · Guild · Sakura · Conquest · League · Luxury Shop · Martial Arts · Weekly Fund**.
Tiền: token tím (arena) 5950, token xanh 155K, VS 35200, SPA 2761K, sakura 0, vàng 0…
**Toàn bộ là mua, không có ô Free/Claim** → không bấm (đúng quy tắc chỉ nhận đồ miễn phí).
Chấm đỏ trên tab chỉ là "có món mới", không phải có quà nhận.

---

## Quy tắc an toàn

Được tap: `Join`, `Claim` / `Claim All` (cam), `Battle` giữa sân `(957,522)`, `Confirm` kết quả,
`Tap to continue` `(960,1045)`, `Refresh`, các nút chuyển tab, mũi tên thoát, `Achiv` + ô
`Available for Pickup`.

**Không tap**: `+` cạnh lượt/tiền (mua), `Update:` trong Select Opponent (50 gem),
`Unlock Power of god`, mọi ô `$`, `Purchase`, nút giá gem.
Không tự mua lượt (`Today chances 0/5` thì để đó), không quẹt `Challenge 5X` khi chưa xem.

## Kết quả lần chạy 11/10/2026

### Đã nhận (miễn phí)
- **Dawnstar Cup → League Tasks → Path of Champions**: Claim All 4 dòng đầu
  (3 rương + ×20000), thanh The Redemption of Stella 0 → **35/60**.
- **Recruitment Task**: `Deploy once in the Magical Girl League` + `Obserion Spire` → Claimed (3/5).
- **Martial Arts Cup → Achiv**: VS ×800 + item ×100.
- **Martial Arts Cup → Participate**: thắng **5/5** trận (đối thủ team 34M/49M/55M),
  merit 1007 → 1051, rank 34 → **29**; mỗi trận VS ×100 + vàng ×20000.
- **Spa Battle → Exclusive SPA (Common)**: ×46080 token SPA.

### Trạng thái còn dở
- **Arena thường**: `Today chances 0/5`, hết lượt (hồi theo ngày). Rewards đã claim hết.
- **Dimensional Arena**: còn **9/10 lượt** nhưng **nút Challenge không phản hồi** (lỗi client).
  Season 30 còn `1D1H`, Silver 505/750.
- **Dawnstar Cup**: round 3 sắp hết (countdown vài phút lúc rời). Điểm The Redemption 35/60 —
  muốn lên 60 phải chơi ở round sau (mỗi round chỉ tính 1 lượt tham gia).
  `Deploy troops to the Forgehold Prime / Luminas Gate` (Recruitment Task) chưa làm được.
  First Formation **không nhận input** → không deploy quân được.
- **Martial Arts Cup**: `Attempts` hết; mốc 1090 điểm (đỉnh hiện tại 1089) và
  tham gia 50/70 chưa đạt. Canh **Clash Time** (EST 15:00–16:00, 20:30–21:30) để ăn merit ×1.5.
- **Exchange Shop**: chưa mua gì (cố ý).

### Lỗi/bẫy đã gặp
1. **Nút cam "chết"**: Claim / Challenge / Battle đôi khi không phản hồi dù toạ độ đúng và
   không có log. Cách chữa đã kiểm chứng: **đổi trạng thái màn** (vào/ra một màn khác) rồi
   bấm lại — Path of Champions Claim All hoạt động đúng như vậy.
2. **`Back` (keyevent 4)** trên vài màn con bật **"Confirm to exit the game?"** → Cancel `(705,710)`.
3. **Tap vào label nút (y≈985) dễ trượt** — bấm vào **icon** phía trên (y≈935).
4. Toạ độ **Rewards** của Arena base là **`(1400,140)`**, không phải `(1272,140)`.
