# Task 5: Arena (icon trống ở lobby)

Vào: lobby, tap **Arena** `(1745,415)`. Thoát về lobby: mũi tên `(75,50)`.

Màn Arena có 5 mode:

| Mode | Toạ độ | Ghi chú |
|---|---|---|
| Arena | `(465,392)` | arena thường, đánh theo lượt |
| Dawnstar Cup — Magical Girl League | `(1390,300)` | giải league theo mùa (KVK), nhiều tầng |
| Dimensional Arena | `(465,800)` | arena xuyên server, 10 lượt/ngày |
| Spa Battle | `(1030,780)` | xem `harvest.md` |
| Martial Arts Cup | `(1390,760)` | tournament + achievement |

**Tap vào card giữa thẻ** (vùng ảnh), không tap vào label chữ phía dưới — label nằm ngoài
vùng nhận tap của vài thẻ.

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
  - **Points Rewards**: mốc 30/60/100 điểm (mỗi mốc ×500 token) — tab mặc định, đã Claimed hết.
  - **ACHV Rewards** `(390,345)`: theo History Highest Ranking (History: 19) — TOP 1/2/3, Unachieved.
  - **Daily Rewards** `(390,463)`: theo hạng trong ngày, gửi lúc 21:00, không có nút nhận.
  - Có nút `Auto Claim` (làm mờ, chưa dùng được).
  - Đóng: `(960,1045)`.
- `Battle Report`, `DEF`, `Ranking` góc phải dưới — chỉ để xem.
- `Exchange Shop` góc phải trên `(1830,120)` — xem mục 6.

**Trạng thái lần chạy 11/10:** `Today chances: 0/5` (hết lượt, `Time left to send Rewards: 2H59M`
→ reset sau ~3 h). Rewards cả 3 tab không còn gì nhận. Không tự mua lượt.

## 2. Dawnstar Cup — Magical Girl League (S6, Round 3)

Màn chính: logo Dawnstar Cup + panel **League Information** (timeline 10/4 → 10/10 → 10/11,
danh sách đối thủ guild, `Time until the League ends: HH:MM:SS`) + **Join** `(1270,910)`.
Timeline đọc: mốc đang chạy sáng vàng, mốc kế bên nền xám.

4 nút góc trái dưới (bấm vào **icon**, y≈935; bấm lệch xuống label dễ trượt):

| Nút | Toạ độ | Nội dung |
|---|---|---|
| Ranking | `(85,935)` | bảng xếp hạng |
| Reward Preview | `(247,985)` | popup **Ranking Rewards**: tab King's Battlefield / Diamond / Golden / Dawnstar Cup; TOP 1/2/3 (sao ×5, rương, vàng, huy hiệu, chest ×17000). *"League rewards will be sent via email."* |
| League Shop | `(400,985)` | shop, chỉ mua |
| League Tasks | `(560,940)` | 3 tab — xem dưới |

**Join** → load ~7–9 s → màn **King's Battlefield** (map lục giác real-time):
`Observation Spire 22/26/27/29/30`, `Base Camp`, `Drakara Polis 11` (HP thanh 40 → tụt dần),
`Brawl Mode countdown`, nút `Go to Formations / Formation` `(940,955)`, `Resurrect` `(1700,955)`,
`Positioning`, panel `Marching Info.` / `Spectating`: *Deployable in the match*.
Thoát về màn league bằng mũi tên `(75,45)`.

**First Formation** (mở từ `Formation`): 6 ô số 1–6, roster UR-EX/SSR dưới cùng,
`Substitute Formation 0/6`, `Total BP`, `SPD: 5500`, gợi ý Reco ở phải, nút `Formation` `(1700,730)`.
**Roster không phản hồi tap** (thử tap portrait, tap ô số, kéo-thả portrait→ô: `Total BP`
vẫn 222000, vẫn 0/6). Đây **không phải** cách deploy — đừng cố.

### League Tasks — 3 tab (nút trái)

Tap tab bằng **giữa ô** (không phải icon bên trái):

| Tab | Toạ độ | Nội dung |
|---|---|---|
| Recruitment Task | `(240,185)` | tiến độ tổng 3/5 |
| Daily Training | `(180,293)` | 4 task deploy trong league, 0/1 hết |
| Path of Champions | `(240,433)` | The Redemption of Stella |

**a) Recruitment Task** — `Complete all tasks to obtain the Crafting Blueprints` 3/5.
- `Deploy troops to the Forgehold Prime 1 times` 0/1
- `Deploy troops to the Luminas Gate 1 times` 0/1
- `Deploy once in the Magical Girl League` → **Claimed** (chỉ cần Join vào trận là xong)
- `Deploy troops to the Obserion Spire 1 times` → **Claimed**

**b) Daily Training** — `Refresh Tasks at 03:00 (EST) during League time`. 4 task
(`Deploy once in the Magical Girl League` / `Obserion Spire` / `Forgehold Prime` / `Luminas Gate`)
đều 0/1 Unachieved. Thưởng mỗi task: badge ×100 + rương ×1. **Không làm được** vì cần deploy
trong King's Battlefield (màn First Formation không nhận input).

**c) Path of Champions** — `The Redemption of Stella` (thanh 0→60 điểm,
`End time: Reset after Dawnstar Cup Season 6`, phần thưởng ×4 blueprint ở mốc 60). Các dòng:

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

- Trái: badge hạng hiện tại (`Silver 505/750` → 721/750), `Time left for result: 1D1H`.
- Phải: tab **Cross Server** / **Server**, top 3 + hàng `Self` (điểm & rank).
- `Today Challenge Chances: N/10`, nút **Challenge `(1602,984)`**, dấu `+` cạnh lượt = **mua lượt**.
- **Rewards** `(1638,120)`: tab Daily Rewards (thưởng theo hạng ngày, gửi 21:00 EST) và
  Season Rewards — **chỉ để xem, không có nút nhận**. Bấm `Tap to continue` `(960,1045)` để đóng.
- **Exchange Shop** `(1455,120)`: mở thẳng shop ở mục 6.
- **Battle Report** `(120,960)` — chỉ để xem. Log kiểu `DEF` thua `-20` điểm,
  `ATK` thắng `+22` (tức bị cướp điểm khi phòng thủ thua, mất điểm thì tụt hạng).

### Vòng đánh — đã chạy trọn 9 trận, 9 thắng

1. **Challenge `(1602,984)`** → màn **chọn đối thủ**: 4 cột, mỗi cột 1 avatar + điểm + tên +
   server + `BP` + `Victory Points N` + nút **Challenge** dưới mỗi cột.
   `My BP` ở đáy trái, `Today Challenge Chances` đáy giữa, **Refresh** `(1455,985)` đáy phải.
2. **Chọn cột yếu**: tap Challenge theo cột — `(265,852)` / `(740,852)` / `(1200,852)` /
   `(1665,852)`. **BP ở danh sách là BP đội thật** ở mode này (khác Martial Arts Cup): đối thủ
   50M/16M/60M thắng chắc; 294M/351M/510M thì bỏ. **Toàn bộ 4 cột đều mạnh → bấm Refresh
   `(1455,985)`** rồi xem lại (đã dùng 1 lần, list đổi ngay).
3. → **Battle Preparation**: `Total BP` 2 bên, `Deployed Heroes: 12/12`, hint
   *"Drag heroes to adjust their positions"*. Không cần chỉnh gì.
4. **Bắt đầu trận**: tap **quả cầu lửa / chữ `Battle` giữa sân `(960,490)`**. (Tap `(960,515)`
   trượt — nhắm vào tâm quả cầu cao hơn một chút.)
5. Trận chạy → có nút **Skip `(1830,490)`** ở cột icon phải (`buff / Skip / x2 SPD / Open`).
   **Bấm Skip liên tục** để tua animation (animation kỹ năng chèn giữa trận nên đôi khi phải
   bấm 8–10 lần trong ~10 giây).
6. **Victory** → `Battle Result`: `Winning Streak` + điểm streak, dải hạng (Points +N, thanh
   Silver). `Tap to continue` `(960,1045)`.
7. Popup **Pts Change**: `Points 527 (+22)`, `Ranking 150 (+17)`. `Tap to continue` `(960,1045)`
   → về màn chính. Có lúc phải bấm `Tap to continue` 2–3 lần qua các popup nối tiếp và màn
   loading mây (~6 s).

**Kết quả 11/10:** 9 lượt liên tiếp **thắng cả 9** (đối thủ 9.4M–98M BP). Điểm
**505 → 721/750** (Silver), hạng **168 → 88**. Mỗi thắng +22…+27 điểm tuỳ mốc điểm đối thủ
(`Victory Points` ghi trên cột). Còn 1 lượt đầu ngày đã dùng trước đó. **Không mua lượt lần nào.**

**TRƯỚC ĐÂY GHI SAI:** note cũ nói *"nút Challenge không phản hồi (lỗi client)"* với toạ độ
`(1330,958)`. Đó là **toạ độ sai của mình** — nút thật ở **`(1602,984)`**, tap vào là mở ngay.
Đã kiểm chứng lại bằng cách crop `img[880:1080, 1450:1800]`: nút cam chiếm x≈1450–1765,
y≈940–1030. **Bài học: đo biên nút bằng crop ảnh, đừng ước lượng bằng mắt.**

## 4. Martial Arts Cup (S6)

Màn chính: `Time Left 1D…`, top 3 (Edge/Agil/FreeNi), hàng `Self` (level + điểm merit),
`Attempts: N`, các nút: `Clash Time` `(295,900)`, `Log`, `Participate` `(1030,905)`,
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
- **Trạng thái 11/10:** `Attempts: 0`, merit 1051, rank 29, `Time Left 1D 04:09:10` →
  chưa hồi lượt. `+` cạnh Attempts = mua → không bấm.
- **Shop** `(1776,780)`: chính là shop ở mục 6, tab Martial Arts (tiền **VS**).

## 5. Spa Battle

Xem `harvest.md`. Nhánh vào: card Spa Battle `(1030,780)` → màn **Relaxation SPA** (Map1).

- Map 1–6 ở cột trái; 3 hồ trên map có chủ (countdown 05:5x). `Current Spa Occupancy: 0/3`.
- **Exclusive SPA** `(300,975)`: 2 thẻ — **Common** (32 Up/Min, cap 24 h, có nút **Claim**)
  và **Deluxe** (184 Up/Min, `Unlock Power of god to claim` = tiền thật, bỏ qua).
  - Common **tích token theo thời gian** → quay lại là **Claim được tiếp** (không phải 1 lần/ngày).
    Lần chạy này bấm Claim `(955,888)` → nhận **×1824 token SPA** (lần trước ×46080).
  - Popup chúc mừng `Tap to continue` `(960,1045)`.
- `My Spa` `(1815,240)` → *"Sorry! No vacant Spa yet!"* → hết chỗ trống, không chiếm được.
- `Spa Zone` `(1830,90)`, `Spa Shop` `(1830,170)` (chỉ mua), `Battle Record` `(1830,335)`,
  `Produce Up Token` `(1830,500)`, `Ranking` `(1830,690)`.
- Nhận Common xong **chấm đỏ ở Spa Battle trên màn Arena tắt**.
- `Double Bonus` `(1490,110)` trên màn Relaxation SPA: bảng thông báo, không nhận được gì.

## 6. Exchange Shop (dùng chung cho cả 5 mode)

Mở từ Arena base `(1830,120)`, Dimensional Arena `(1455,120)`, Martial Arts Cup `(1776,780)`.
8 tab: **Arena · Guild · Sakura · Conquest · League · Luxury Shop · Martial Arts · Weekly Fund**.
Tiền: token tím (arena) 5950, token xanh 155K, VS 35200, SPA 2761K, sakura 0, vàng 0…
**Toàn bộ là mua, không có ô Free/Claim** → không bấm (đúng quy tắc chỉ nhận đồ miễn phí).
Chấm đỏ trên tab chỉ là "có món mới", không phải có quà nhận.

---

## Quy tắc an toàn

**Quy tắc vàng: `Arena` không được mua lượt.** Không tap dấu `+` cạnh `Today chances` /
`Today Challenge Chances` / `Attempts`, không tap `Update:` (50 gem), không `Unlock Power of god`.

Được tap: `Join`, `Claim` / `Claim All` (cam), `Battle` giữa sân `(957,522)` / `(960,490)`,
**`Skip` trong trận `(1830,490)`**, `Confirm` kết quả, `Tap to continue` `(960,1045)`,
`Refresh`, các nút chuyển tab, mũi tên thoát, `Achiv` + ô `Available for Pickup`,
`Exclusive SPA → Common → Claim`.

**Không tap**: `+` cạnh lượt/tiền (mua), `Update:` trong Select Opponent (50 gem),
`Unlock Power of god`, mọi ô `$`, `Purchase`, nút giá gem.

KHÔNG tự mua lượt (`Today chances 0/5` thì để đó), và không quẹt `Challenge 5X` khi chưa xem.

## Kết quả lần chạy 11/10/2026

### Đã nhận (miễn phí)
- **Dimensional Arena**: **9 trận liên tiếp toàn thắng**, điểm **505 → 721/750** (Silver),
  hạng **168 → 88**. Dùng hết 10/10 lượt, **không mua lượt**.
- **Dawnstar Cup → League Tasks → Path of Champions**: Claim All 4 dòng đầu
  (3 rương + ×20000), thanh The Redemption of Stella 0 → **35/60**.
- **Recruitment Task**: `Deploy once in the Magical Girl League` + `Obserion Spire` → Claimed (3/5).
- **Martial Arts Cup → Achiv**: VS ×800 + item ×100.
- **Martial Arts Cup → Participate**: thắng **5/5** trận (đối thủ team 34M/49M/55M),
  merit 1007 → 1051, rank 34 → **29**; mỗi trận VS ×100 + vàng ×20000.
- **Spa Battle → Exclusive SPA (Common)**: ×46080 rồi quay lại nhận tiếp **×1824** token SPA.

### Trạng thái còn dở
- **Arena thường**: `Today chances 0/5` (`Time left to send Rewards: 2H59M`), Rewards cả 3 tab
  đã claim hết. Chờ reset ngày.
- **Dimensional Arena**: hết lượt `0/10`, Silver **721/750** gần lên mốc 750.
  Season 30 còn ~`1D1H`. Chờ hồi lượt (10 lượt/ngày).
- **Dawnstar Cup**: S32 Round 3 đang ở pha **Ranking** (timeline 10/4 → 10/10 → 10/11).
   Điểm The Redemption 35/60 — muốn lên 60 phải chơi ở round sau (mỗi round chỉ tính 1 lượt).
  `Deploy troops to the Forgehold Prime / Luminas Gate` (Recruitment + Daily Training) chưa làm
  được. First Formation **không nhận input** → không deploy quân được.
- **Martial Arts Cup**: `Attempts 0/5` (chưa hồi), merit 1051, rank 29; mốc 1090 điểm
  chưa đạt. Canh **Clash Time** (EST 15:00–16:00, 20:30–21:30) để ăn merit ×1.5.
- **Spa Battle**: `Occupancy 0/3`, `My Spa` báo hết chỗ.
- **Exchange Shop**: chưa mua gì (cố ý).
- **Chấm đỏ trên icon Arena ở lobby vẫn còn** sau khi dọn hết cả 5 mode — là badge tổng không
  tắt, không tìm thấy mục nào còn Claim được.

### Lỗi/bẫy đã gặp
1. **Nút cam "chết"**: Claim / Battle đôi khi không phản hồi dù toạ độ đúng và
   không có log. Cách chữa đã kiểm chứng: **đổi trạng thái màn** (vào/ra một màn khác) rồi
   bấm lại — Path of Champions Claim All hoạt động đúng như vậy. **Không phải lỗi client.**
2. **Toạ độ tự đoán sai là bẫy lớn nhất.** Nút Challenge Dimensional Arena thật ở `(1602,984)`;
   mình từng ghi `(1330,958)` rồi kết luận sai là "nút hỏng". Muốn chắc thì **crop ảnh** vùng
   quanh nút (`img[y0:y1, x0:x1]`, phóng 2x) và in pixel tại toạ độ dự kiến, đừng nhìn ảnh render.
3. **`Back` (keyevent 4)** trên vài màn con bật **"Confirm to exit the game?"** → Cancel `(705,710)`.
4. **Tap vào label nút (y≈985) dễ trượt** — bấm vào **icon/vùng ảnh** phía trên (y≈935).
5. Toạ độ **Rewards** của Arena base là **`(1400,140)`**, không phải `(1272,140)`.
6. **Tap liên tục quá nhanh làm lạc hướng** — mỗi bước phải screenshot kiểm tra, nhất là sau
   `Tap to continue` (có màn loading mây ~6 s, bấm sớm là mất tap). Tap nhầm vào avatar ở lobby
   sẽ mở **Account Information** → đóng bằng `Tap to continue` `(960,1045)`.
7. **Skip trong trận**: animation kỹ năng chèn giữa trận nên phải bấm Skip nhiều lần, không
   phải 1 lần là xong.
