# Task: Bond Festival (Blossom Bonding)

Vào: lobby, tap **Bond Festival** `(1745,700)`. Thoát: mũi tên `(95,50)` (không dùng Back hệ thống).
Tọa độ theo 1920x1080. Tài nguyên sự kiện: ⚡ thể lực (tự hồi), vé sự kiện (hồng), **tem** (stamp),
token nâng cấp quầy, độ nổi tiếng (Festival Popularity).

## Cấu trúc
- **Hub màn chính** (ảnh isometric lễ hội), cột icon bên trái: **Tasks** `(140,490)`,
  **Stamp Book** `(140,655)`, **Exchange** `(140,805)`, **Management** `(100,940)`;
  giữa màn là nút **Wander** `(955,916)`, dưới là dòng `Use ⚡1`.
- **Wander**: tốn 1⚡, đi 1 quầy.
- **Stamp Book**: 2 tab Stamp Collection / Stamp Set.
- **Exchange**: 3 tab Exchange Hall / Post Exchange / My Exchanges.
- **Management** (Stall Management): tab Normal Stall / Special Stall.
- Icon **Tasks** trên map `(140,490)` mở đúng bảng **Quests** (Daily / Events), không có
  bảng riêng.
- Sân khấu **Kagura Dance** `~(420,340)` (kèm bong bóng sake) → màn **Offer** (xem dưới).
- Trên map còn: ✕ `Skip` và **Fast Wander** `(1700,870)` ở mép phải — **không bấm**;
  thanh Popularity + nút (i) ở trên; vé sự kiện & điểm nâng cấp ở góc phải trên.

## Kinh tế: Festival Popularity → Stall Upgrade Points
Thanh **Festival Popularity** trên map, `Lv3` + `N/400`. Tooltip ở nút **(i)** cạnh Lv
`(330,140)` nói rõ:

> Each time you wander, Festival Popularity +10.
> Increase Festival Popularity Level to earn **Stall Upgrade Points** and get rare Stamps
> more easily.
> Next Level: Lv. 4 → **Upgrade Points +1**, mở khoá quầy **BBQ** ("Wandering here will grant
> you stamina x2").

Vậy **điểm nâng cấp quầy** = thẻ vàng có mũi tên đỏ, hiện ở ô góc phải trên map
(icon `~(1655,30)`, số ở `~(1770,45)`). Nguồn duy nhất là **lên cấp Popularity**, mà
Popularity chỉ tăng bằng wander. Đây chính là chìa khoá cho cổng "upgrade your stall":
cổng đó **không phải ngõ cụt**, chỉ là chưa đủ cấp. Thanh Popularity **reset về 0 mỗi lần lên cấp**.

Số ở ô điểm nâng cấp **không đọc được bằng OCR** (chữ số 0 đơn lẻ bị nhận thành `'。'`, `'一'`).
Muốn biết còn dùng được Upgrade hay không thì dựa vào **màu nút**: còn dùng được thì nút cam
(nhận ra bởi `find_orange_buttons`), hết điểm thì nút xám xanh và bị bỏ qua.

## Vòng Wander (đã tự động hoá, `bondfestival.py`)
1. Map → tap **Wander** `(955,916)` (−1⚡).
2. Popup **"Arrived at <quầy>"** → **Confirm** `(960,950)`.
3. Popup **"Stall Rewards"** (tem + vé) → **Confirm** `(960,972)`.
4. Về map. Lặp lại.

Mỗi quầy: +10 Festival Popularity, +1 lượt tính vào quest "Visit N Stalls".

## Kagura Dance & Offer (sân khấu giữa map)
Bong bóng **bình sake + số** trôi trên sân khấu Kagura Dance `~(420,340)`. **Số đó chính là
số Divine Sake đang có** (`×0` = hết sake, `×2` = có 2) — không phải vật phẩm nhặt được,
và nó đổi theo số sake thật ở góc phải màn Offer.

Tap bong bóng (hoặc sân khấu) mở màn **Offer**:

| Vùng | Nội dung |
|---|---|
| Trên giữa | `Amaterasu Omikami Faith Power  N/80000000000` — tiến độ **chung toàn server**, tăng khi bất kỳ ai dâng lễ |
| Phải trên | số **Divine Sake** + nút `+` (**nạp gem — không bấm**) |
| Giữa | nút **Tribute** `(960,940)`, ghi `Use: <sake> 1` / `BP: 107M` |
| Trái | bảng `Divine Sake Count` (1 Mami, 2 ShaKon, 3 Edge) + nút `Ranking` |
| Trái trên | `Rewards` `(110,205)` — xem tỉ lệ quà mỗi lần dâng, không có nút nhận |
| Phải dưới | `Offer N Times` — N = **số sake còn dâng được**, tự cập nhật theo số sake |
| Phải trên | icon `Faith Level` `(1385,150)` — mốc thưởng chung toàn server |

**Tribute** dâng 1 Divine Sake → hiện popup `REWARDS OBTAINED` (1 món ngẫu nhiên: trăng xanh,
W tím, dây tím, bình hồng…) → **+1 lượt "Send Cheers to Kagura Dance"**. Tribute **không tốn gem**.

**Faith Level** (icon `(1385,150)`): thưởng theo mốc tổng Faith Power toàn server —
Lv1: dây tím ×6 + pha lê ×1 + trăng ×2 + vàng ×10000; Lv2: ×7/×2/×4/×20000;
Lv3: ×8/×3/×6/×30000… Quà do **Shizuka Gozen gửi qua mail vào ngày hôm sau**, không nhận trực tiếp.

### Nguồn Divine Sake: đổi Stamp Set
Sake **không bán**, chỉ rơi ra từ **Stamp Book › Stamp Set**:
- Bộ rương **vàng** (4 tem cam, ví dụ Perfect Accuracy): sake ×2 + W tím ×2 + cuộn xanh ×20 + vàng ×10000
- Bộ rương **xanh** (2–3 tem): sake ×1 + pha lê ×1 + vàng ×5000

Vòng kinh tế đầy đủ của event:

> **wander → tem (+10 Popularity) → đổi Stamp Set → Divine Sake → Tribute → Faith Power
> + cheer cho God Words + quà ngẫu nhiên**

## Quests của event
**Daily** (thanh `Time Left` riêng, reset hằng ngày):

| Quest | Điều kiện | Cách làm |
|---|---|---|
| Bond Parade-1 | Visit 20 Stalls | wander 20 lần |
| Bond Parade-2 | Visit 50 Stalls | wander 50 lần |
| Warm-Up Challenge | Exchange Stamp Sets 1X | đổi 1 bộ Stamp Set |
| **Dance with God** | Send Cheers to Kagura Dance **1X** | **Tribute 1 lần** ở màn Offer |
| **Joyful Rewards** | Submit 1 Stamp Exchange Requests | **tự đăng request** ở Post Exchange |

**Events** (5 ngày): *God Words 1–5* = gửi cheer **10 / 25 / 50 / 75 / 100** lần, tức dâng lễ
chừng ấy lần. Thưởng tăng dần: GW-1 = món đỏ ×1 + W tím ×2 + pha lê xanh ×2 + trăng xanh ×2
→ GW-5 = món đỏ ×1 + W tím ×10 + pha lê ×15 + trăng ×15.

### Post Exchange: tự đăng request được, không cần ally nhận
`Exchange` → tab **Post Exchange** `(1268,60)`. 6 ô "My Exchanges", mỗi ô 2 khe tem
**Obtain** (muốn nhận) / **Use** (đem trao) + nút **Post** vàng. Luồng:
1. `Post` → popup **Select Stamp** (chọn tem cho khe Obtain; mỗi tem hiện số đang có) → `Confirm` `(960,845)`
2. popup **Use Stamps** — chọn tem đem trao, có thanh số lượng `1/7` và `-10 / - / + / +10 / MAX`
3. `Exchange` `(960,873)` → request đăng xong: ô hiện `Obtain ↔ Use`, đồng hồ 24h, nút `Later`.

Tem **chỉ bị trừ khi có người nhận** (đăng xong, Stamp Book vẫn hiện nguyên số cũ).
Quest *Joyful Rewards* tính **ngay khi request được đăng** — không cần ai nhận.
Tối đa 6 request cùng lúc; tem phải tự tay nhận khi có người khớp.

## Cổng chặn: nâng cấp quầy
Sau một số lần wander, game chặn:
**"Upgrade your stall before continuing your wander, my Lord!"**
- Confirm → mở **Stall Management**.
- Bấm nút **Go** (xanh) ở quầy có chấm đỏ (quầy "Slot", gắn nhãn *Rec.*, góc dưới phải
  khung Normal Stall, tâm ~`(1578,585)`).
- Trong khung quầy bấm **Upgrade** (nút cam, miễn phí, tốn 1 **Stall Upgrade Point**).
- Xong thì wander lại bình thường.

Khi **chưa có điểm**, nút Upgrade xám và bấm không ăn; bấm "Tap to continue" để đóng khung,
rồi **thoát bằng mũi tên `(140,50)`** và wander tiếp — qua được cổng. Thực tế đã kiểm chứng:
sau lần kẹt đó bot vẫn wander vào quầy Shaved Ice bình thường.

## Nhận diện màn hình (`classify` trong `bondfestival.py`)
| # | Dấu hiệu | Kết quả |
|---|---|---|
| 1 | Có nút cam (HSV H 12–28, S≥150, V≥200; w 240–460, h 50–100) trong dải y 500–1010 | popup có Confirm/Upgrade → OCR nhãn nút, tap tâm nút |
| 2 | OCR vùng `(700,1000)-(1220,1080)` ra chữ "continue" | "Tap to continue" → tap `(960,1045)` |
| 3 | Khớp `bf_stall_mgmt.png` (≥0.85) | Stall Management → tap Go của quầy chấm đỏ |
| 4 | OCR vùng `(870,885)-(1040,945)` ra chữ "Wander" | map → tap `(955,916)` |
| 4b | OCR vùng `(880,950)-(1040,1000)` ra chữ "Use" (dòng "Use ⚡1") | map → tap `(955,916)` — dự phòng khi nút Wander bị hiệu ứng che mờ |
| 5 | còn lại | chờ 1.5s, 20 lần liên tiếp thì dừng + lưu ảnh debug |

Dừng an toàn khi: hết thể lực, 12 lần tap nút liên tiếp không có wander nào, 20 khung hình
liên tiếp không nhận ra, hoặc nhãn nút cam chứa từ khoá mua/nạp.

Thể lực đọc bằng OCR, **chỉ đọc khi đã xác định là map** — khi có popup, cả màn bị làm tối
và OCR đọc ra số rác.

Vùng này đã chỉnh nhiều lần, `STAMINA_RECTS` giữ cả bốn ô và thử lần lượt. `(1700,100)-(1860,165)`
dính dải cây phía trên và vòng "+" bên phải → OCR trả `'行'`. Thu còn `(1710,118)-(1810,162)`
thì đọc đúng `'12'` nhưng **số một chữ số bị hụt**. Mở rộng ra `(1690,105)-(1830,170)` vẫn hỏng
vì dính tia sét ⚡ bên trái và vòng "+" bên phải.

Hai ô bù trừ nhau, và đây là chỗ dễ mất thời gian nhất:

| Ô | Đúng | Hỏng |
|---|---|---|
| `(1720,110)-(1815,172)` — chính | `12 / 9 / 8 / 1` | **`0` → `'。'`** |
| `(1740,112)-(1805,168)` — khít quanh chữ số | `0 / 1 / 8 / 12` | **`9` → `'g'`** |

**Ô chính xếp trước, ô khít xếp cuối**, lấy kết quả hợp lệ đầu tiên. Đã kiểm 9 khung map
(12, 12, 9, 8, 1, 1, 1, 1, 0) — **9/9 đúng**.

Lọc kèm: bỏ kết quả nhiều hơn 4 chữ số, vì khi đó OCR đã vơ luôn dòng đếm ngược `00:06:03`.

> **Bẫy chết người:** thể lực `0` hiển thị đúng một chữ số `0`, mà ô chính đọc thành `'。'`.
> Bản grinder đầu tiên vì thế **dừng sau 2 lần wander** với "đọc ⚡ hỏng liên tục" — hết thể lực
> chứ không phải lỗi màn hình. Gặp lại triệu chứng này thì kiểm `read_stamina` trước tiên.
> `classify` trả `'unknown'` đúng cho mọi màn không phải map (Quests, popup…) nên không có
> chuyện đọc nhầm ⚡ của màn khác rồi tap Wander bừa.

## Bẫy đã gặp
- Nút **Confirm không đồng nhất giữa các popup** (đồ hoạ khác nhau). Template `bf_confirm.png`
  khớp 0.90 ở popup này nhưng 0.853 ở popup "Upgrade your stall", và còn khớp nhầm banner Quests
  (0.815). → bỏ template, dùng **phát hiện theo màu cam**.
- `bf_wander.png` khớp 0.937–1.0 trên map nhưng chỉ 0.757 khi nút Wander có chấm đỏ/đổi glow.
  → bỏ template, dùng **OCR chữ "Wander"** + toạ độ cố định.
- Popup **"Festival Level Up / Tap the screen to continue"**: tap giữa màn `(960,540)` không ăn.
  Vị trí đúng là `(960,1045)`.
- Icon **Exchange** trên map ở `(140,765)` nằm trong `FORBIDDEN_RECTS` của `device.py`
  (vùng chặn nạp tiền) → `tap()` raise `ValueError`. Dùng `(140,805)` hoặc mở từ thanh trên.
- Quầy "Preparing" (đồng hồ đếm ngược, ~16 phút) chưa xong thì không wander vào được.
- Panel **My Stall** ở mép trái map (nút **+** xanh `(25,155)`): xuất hiện/lặn theo vị trí
  camera, không cần bấm.
- Wander vào quầy **Shaved Ice** cho buff hiện ở góc phải dưới map (ô **Buff:** 🍧).
- Mở Exchange / Stamp Book / Quests từ map rồi bấm **back ra là về map luôn**, không qua
  landing page — dễ nhầm là đang ở landing.
- Icon **Exchange** trên map ở `(140,765)` nằm trong `FORBIDDEN_RECTS` → dùng `(140,805)`
  (vẫn trúng đáy icon). Tab **Stamp Set** `(1478,62)` cũng bị chặn → bấm `(1478,88)`.
- Số tem trong Stamp Set hiện dạng **`đang có / cần`**. Một bộ **đổi được nhiều lần** chừng nào
  còn đủ tem, nên sau một lần đổi bộ đó **không biến mất** khỏi danh sách — vòng lặp "bấm Exchange
  ô trên cùng" sẽ tiêu liên tiếp vào cùng một bộ cho tới khi hết tem.
- **Tribute cần nhịp**: tap cách nhau 2s hay trượt (5 lần chỉ ăn 2), cách **4s** thì ăn đều.
- Bong bóng sake trên map hiện `×0` khi hết sake — đừng tưởng là vật phẩm đã mất.

## Quy tắc an toàn
Chỉ tap: Wander, Confirm/Upgrade màu cam trong popup, "Tap to continue", Go của quầy có chấm đỏ,
`Claim All` ở Stamp Collection, `Exchange` ở Stamp Set, `Post`/`Confirm`/`Exchange` ở Post Exchange,
`Tribute` và `Continue` ở màn Offer.
Không tap: nút **+** cạnh ⚡ (nạp thể lực), nút **+** cạnh số Divine Sake (nạp sake), Skip,
Fast Wander, `Ranking`, bất kỳ nút gem/$ nào.

Chốt chặn tiền tệ trong code (`BAD_LABELS` + `GOOD_LABELS`, cả hai file):

1. Mỗi nút cam phải **OCR nhãn trước khi tap**. Nhãn chứa
   `purchase / buy / recharge / top-up / topup / diamond / gem / gold / pay / $ / pack`
   → **không tap**, dừng ngay.
2. Nhãn **không** chứa từ nào trong danh sách trắng
   `confirm / upgrade / ok / claim / receive / collect / continue / exchange / post / go`
   → cũng **không tap**, dừng ngay.

Lý do cần cả hai: khi hết ⚡ mà bấm Wander, game có thể hiện popup mua thể lực. Nút của
popup đó rất có thể chỉ ghi "Confirm" (hoặc chỉ hiện giá gem — OCR ra một con số trần),
nên **danh sách đen một mình là không đủ**. Danh sách trắng biến "nhãn lạ" thành trạng thái
an toàn: thà kẹt lại còn hơn tiêu gem. Bot `bondfestival_grind.py` còn tránh hẳn tình huống
này bằng cách **ngủ chờ hồi ⚡ chứ không bao giờ tap Wander khi thể lực = 0**.

## Chạy lại
Vòng ngắn (dừng khi hết ⚡ hoặc gặp màn lạ):
```
python -u workflows/GirlWars/llm/bondfestival.py [số_lần_wander]
```

Cày đường dài, tự chờ hồi thể lực (`bondfestival_grind.py`):
```
python -u workflows/GirlWars/llm/bondfestival_grind.py [số_giờ] [đích_wander]
```
Khác biệt: hết ⚡ thì **ngủ chờ hồi chứ không tap Wander** (tap lúc 0⚡ sẽ mở popup mua
thể lực bằng gem); kẹt ở Stall Management thì thoát bằng mũi tên `(140,50)` rồi đi tiếp;
màn hình lạ thì thử mũi tên thoát ở khung 5 và 11 trước khi bỏ cuộc. Thể lực hồi
~**1 điểm / 16 phút**, nên cày dài phải chạy nền hàng giờ.

### Vòng sake (làm tay, chạy định kỳ sau mỗi đợt wander)
1. Map → `Stamp Book` `(140,655)` → tab `Stamp Collection` → `Claim All` `(1248,165)`
   → `Continue` `(960,1045)` → tab `Stamp Set` `(1478,88)`.
2. Ở `Stamp Set`, bấm `Exchange` của **ô trên cùng** `(1557,310)` → `Exchange` `(1162,880)`
   → `Continue` `(960,1045)`. Lặp tới khi hết nút xanh (nút xám = không đổi được).
3. Map → tap bong bóng sake `(420,340)` → màn Offer.
4. `Tribute` `(960,940)` → `Continue` `(960,1045)`, mỗi lần cách **4s**, lặp tới khi
   `Offer N Times` về `0`.

Không bấm nút `+` cạnh số sake, không bấm `Ranking`, `Rewards` chỉ để xem.

## Kết quả lần chạy này

### Đã nhận (miễn phí, không tiêu gem/vé)
- **Quests › Daily** — cả 5 mục đã Claim:
  Bond Parade-1 (20/20), Warm-Up Challenge (1/1), **Dance with God (1/1)**,
  **Joyful Rewards (1/1)**. Chỉ còn *Bond Parade-2* (Visit 50 Stalls) chạy tiếp theo wander.
- **Event quest God Words 1–5**: đang **6/10, 6/25, 6/50, 6/75, 6/100** (6 lần Tribute).
- **Stamp Book › Stamp Collection**: Claim All (trăng ×35, W tím ×8, pha lê ×6).
- **Stamp Set**: đổi **8 bộ** (1 vàng + 7 xanh) → tổng sake thu về **8**, đã dâng hết.
- Vé sự kiện: 7050 → **9550**; Popularity Lv3, **130/400**.

### Trạng thái còn dở
- Cổng **"Upgrade your stall before continuing your wander"** đã gặp và đã đi qua được
  (thoát bằng mũi tên, wander tiếp bình thường). Muốn nâng cấp quầy cho thật thì cần
  **1 Stall Upgrade Point** — hiện `0`, chỉ có khi **lên Popularity Lv.4** (mốc 400).
- Popularity lúc khởi động lại grind: **150/400**, còn **250 = 25 lần wander** nữa là Lv.4.
  Thể lực hồi ~16 phút/điểm → đích 40 lần wander cần ~10.7h, khớp ngân sách 12h của
  `bondfestival_grind.py 12 40` (đang chạy nền, log `_out/bf_grind.log`).
- **God Words-1 còn 4 cheer** nữa; sake tiếp tục rơi ra từ wander → tem → Stamp Set.
- *Bond Parade-2* (Visit 50 Stalls) đang 43/50 → grind xong thì vào **Quests › Daily** bấm
  **Claim** (nút xanh, không phải cam — bot không tự nhận).
- Hai quầy **Preparing** chưa mở (một quầy đếm ngược dài 119:xx:xx).
- Request trao tem đang treo ở Post Exchange ô 1 (Obtain *Unexpected Mistake* ↔ Use *Failed Bet*,
  hạn 24h) — nếu có ally nhận thì vào `My Exchanges` nhận tem.

### Việc phải làm tay sau khi grind xong (bot không tự làm)
Grind chỉ wander; mọi thứ dưới đây cần người:
1. **Quests › Daily** `(140,490)`: Claim *Bond Parade-2* khi đã đủ 50 (nút **xanh** — `classify`
   chỉ nhận nút cam nên bot bỏ qua), và xem lại 4 mục daily còn lại sau reset ngày.
2. **Vòng sake** ở trên (Stamp Book Claim All → đổi Stamp Set → Tribute cách 4s) — đây là
   cách duy nhất tiêu tem thành cheer.
3. **Festival Rewards** mốc *Wandered: 50* nếu có (chưa xác nhận lại vị trí màn này lần nào
   trong session) — tìm ở màn Quests hoặc icon thưởng góc phải trên map.
4. **My Exchanges**: kiểm tra request treo có ai nhận chưa.
