# Task 5: Harvest Food Carnival (banner đầu danh sách)

Vào: danh sách banner (cuộn lên đầu), tap banner Harvest `(1135,230)`.
Thoát: mũi tên `(75,50)`.

## Các mục trong hub (tọa độ 1920x1080)
- Festival Deals `(540,440)`: chỉ có gói nạp $. Bỏ qua (chấm đỏ là quà nạp).
- Food Arcade `(1250,575)`: có Dessert Battle (còn hạn) và Cake March (đã kết thúc).
  - Dessert Battle `(590,600)`: mini game xếp bánh. Nút **Battle Tasks** `(425,960)`: mốc 500/800/1500, tính **cộng dồn**.
- Food Marble Workshop `(270,700)`: mini game thả bi (đã xử lý hết, xem dưới).
- Guard Food Street `(780,900)`: bàn cờ Monopoly (đã xử lý, xem dưới).
- Food Check-In `(1590,850)`: nhận quà theo ngày, kiểm tra.
- Special Exchange Shop `(870,250)`: đổi đồ, chưa xem.
- Ranking `(1640,190)`: chỉ xem.

## Lưu ý chung
- Chấm đỏ trên hub không luôn là quà miễn phí. Phải mở từng mục và xem nút.
- Popup "REWARDS OBTAINED" / "Tap to continue" làm dải đáy tối (`img[1040:1080].mean()` ≈ 12–40) trong khi màn chơi thường sáng (>60). Ngoại lệ: popup "Game on!" ở Dessert Battle.
- Nút `+` cạnh mọi bộ đếm là **mua**, không bấm.
- Chấm đỏ trên nhãn hub có thể chỉ là **biểu tượng** của nhãn (Food Marble Workshop = viên bi đỏ, Food Arcade = ghim đỏ), không phải badge. Chỉ Guard Food Street có badge thật.

## Food Marble Workshop (270,700)
- Màn chơi: 5 nhân vật trên mép hồ, mỗi người giữ 1 viên bi, `x ≈ 640, 795, 955, 1115, 1270`, **tap vào người ở `y ≈ 130`** để thả bi của người đó.
- Hồ **không tự thả**: 16 giây không chạm thì khung hình đổi 0,3–0,5% (chỉ là nước gợn).
- **Mỗi lượt thả tốn 3 bi** (bộ đếm bên trái dưới nút `+`); thả xong trả pudding (bộ đếm thứ hai). Không tốn gem.
- Thang "Amount Used" bên trái: mốc 15/20/25/30. Bấm **một** mốc đã mở là nhận **tất cả** mốc đã mở cùng lúc (1 popup gộp). Mốc có chấm đỏ là mốc đã mở; mốc 30 khoá khi mới 28.
- Popup "REWARDS OBTAINED" ở đây tối (đáy ≈ 21) → đóng bằng `(960,1045)`.
- Pass `(1610,170)`: nhánh Standard đủ 6 mốc đã Claimed; nhánh Deluxe là trả tiền, bỏ qua.
- Rankings `(1610,320)`: chỉ xem.
- Marble Pack `(1610,480)`: gói free đã "Claimed", còn lại toàn gem/$.
- Exchange Shop `(1610,630)`: cuộn lên để thấy đủ. **Nút giá** nằm ở `x = 692 / 1140 / 1588`; sau khi cuộn hết, 3 hàng ở `y = 350 / 662 / 974`. Dialog mua: Confirm `(1190,766)`, Cancel `(710,766)`, mặc định số lượng 1. **Danh sách tự nhảy về đầu sau mỗi lần mua** nên phải dò lại toạ độ.
- Đã tiêu hết 1360 pudding (hết hạn theo event): Legendary Stardust 560, Golden Tiles 250, MA Hall Blueprint 150, Luxury Coins 120, Epic EXP Scroll 100, Epic Stardust 90, Basalt 65, Thunderstruck Wood 25. Legend Crystal 1800 không đủ.
- Bi đã hết (0) nên hồ không chơi được nữa; mốc 30 của thang coi như bỏ.

## Guard Food Street (780,900)
- Bàn cờ có "Auto on"; bộ đếm góc phải trên là **hai loại xúc xắc**: xúc xắc trắng (Gourmet Dice) và xúc xắc xanh.
  - Góc phải dưới có 2 widget xúc xắc, mỗi cái ghi `×1`: xúc xắc hồng nhỏ "GO 1" ở `(1612,945)` (lucky die) và xúc xắc vàng lớn ở `(1830,935)` (Gourmet die). Mũi tên xanh giữa hai cái là **đổi loại xúc xắc**.
  - **Tap xúc xắc vàng `(1830,935)` = gieo 1 xúc xắc**: tốn 1 Gourmet die, trả thưởng (lần này ×100 vé vàng) + đi thêm ô, cộng Fullness (1300 → 1500).
  - Khi bộ đếm về 0 (lần này cả hai về 0), tap xúc xắc vàng mở dialog **"Source"**: "Gourmet Dice Owned: 0" + 3 link Guard Pack / Pass / Price Pack (đều là nơi mua). **Không mua gì**, đóng bằng `(960,1045)`. Dialog này cũng tối nên `bottom<70` vẫn bắt được.
- **Troublemaking Taotie** `(160,950)` — mặt Taotie tròn ở góc trái dưới đường phố (nhãn `1500/2000`). Mở ra bảng:
  - "Fullness gained from feeding Taotie: 1500/5000".
  - Hàng mốc ở `y ≈ 985`, `x` = 185 (200) · 445 (1000) · 743 (2000) · 1043 (3000) · 1345 (4000) · 1645 (5000). Mốc 200 và 1000 đã **Claimed** (dấu tick xanh); các mốc 2000 trở lên hiện nút xanh "Claim" nhưng **còn khoá** — tap không có gì xảy ra.
  - Ô bonus góc phải "0/300" Claim ở `(1451,368)` đang xám: "After claiming all rewards, every 300 Fullness increased grants 1 extra rewards".
  - Fullness đến từ xúc xắc + đồng đội (Partner). Hết xúc xắc thì đứng ở 1500/2000.
- **Team** (bảng bên trái đường phố, chân dung ở `(160,325)`): mở ra bảng **Partner** — Team Leader Amri (Lv.132, Fullness +1300, BP 107M) và Bird (Lv.31, Fullness +1000, BP 1843K); ô thứ 3 "Waiting for Players". Không có nút nhận; "Help Record" `(1720,950)`. Chấm đỏ trên chân dung ngoài đường phố là thông báo partner, **không có gì để nhận**.
- **Jigsaw Puzzle** `(140,790)`: tap vào ô → hiện dialog "Reward" → bấm **Claim ở `(960,758)`**. Bấm "Tap to continue" `(960,1045)` là **mất quà**. Ô theo COL `{1:583,2:925,3:1245,4:1552}` × ROW `{1:205,2:430,3:655,4:880}`. Màn jigsaw này dải đáy vốn đã tối (≈38) nên **phải nhận dialog bằng nút Claim vàng** `img[728:792, 850:1075]` (>3000 pixel vàng), đừng dùng ngưỡng đáy. Nền không có dialog cho ra ~43 pixel vàng nên ngưỡng 3000 an toàn.
  - **Tim (heart) quanh viền lưới**: cột phải `(1765, y = 215/390/590/800)` = 4 hàng lưới; hàng dưới `(x = 585/900/1225/1550, y = 945)` = 4 cột lưới. Tim chỉ **mở được khi hàng/cột tương ứng đã xong**; tim mở cũng dùng dialog "Reward" → Claim `(960,758)`. Lần này nhận `(1765,590)` và `(1225,945)`. Sau đó cả 16 ô đều không còn Claim → **chấm đỏ của nút Jigsaw Puzzle mất**.
  - Còn lại 3 ô vĩnh viễn không xong: ô 1 "Participate in Dessert Battle for 3 day(s) (1/3)", ô 5 "…7 day(s) (1/7)", ô 16 "Total top up to obtain VIP EXP 900x during the event (0/900)".
- **Guard Pack** `(1810,370)`: toàn bộ gói trả tiền ($/gem); gói free đã "Claimed".
- **Exchange Shop** `(1815,510)`: tiền là vé vàng.
  - Nút giá hàng trên ở `y ≈ 630`, `x` ≈ **731 / 1140 / 1600**; hàng dưới (Judgement) ở `y ≈ 918`, `x ≈ 731`.
  - Dialog "Items Purchase": Cancel `(716,766)`, Confirm `(1177,766)`; số lượng −100 `(645,544)` · − `(805,544)` · +10 `(1119,544)` · MAX `(1217,544)`.
  - Lần này: 2470 vé → mua **Guild gold Phantasm chest 2000** (limit 10→9; nội dung "1 random quality Phantasm: 75% purple / 20% orange / 5% red") và **Guild bronze Phantasm chest 400** (limit 20→19) → còn **70**, không mua được gì thêm (silver 800, Judgement 1000). **Judgement đã "Sold out" (0 x per period)** nên ô `(731,918)` chỉ còn chữ Sold out, tap không mở gì.
- **Special Exchange Shop** `(1815,660)`.

## Kết quả lần này
- Food Check-In: Day 1–7 đã nhận, không còn gì. Track Treasure Rewards bên phải khoá $9.99.
- Festival Deals: chỉ có gói nạp $ (bỏ qua).
- Festival Deals > 2x Rewards Event > SPA Rewards 2x (chấm đỏ): Spa Producing Fund Lv.1 và Lv.2 đã Claim (`(992,688)`, `(1225,688)`, đóng `(960,1045)`). Lv.3+ cần "Unlock Lv".
- Spa Battle: không chơi, không mua.
- Dessert Battle: Battle Tasks đã claim đủ 3 mốc (500/800/1500) sau khi bot chơi được run 353 điểm. Điều khiển: **swipe vừa di chuyển vừa thả** viên bánh, tap không có tác dụng. Popup kết thúc lượt là "About [Pet Cafe]" + nút "Game on!" — dải đáy **không** tối nên `bottom<60` không bắt được, phải template-match.
- Special Exchange Shop: đã đổi 1 "0-Star Limited Mythic Love Select Chest" (5600 token). Còn 2100 token, món UR-EX 21000 không đủ.
- Guard Food Street > Pass (Standard): claim đủ 6 card tại y=645. Card 5 và 6 thật ra ở x=1435 và x=1665, y≈660.
- Food Marble Workshop: đã thả hết bi, nhận gộp 3 mốc thang, tiêu hết 1360 pudding ở Exchange Shop. Hết việc.
- Guard Food Street: đã nhận mốc Taotie 200/1000; Guard Pack free đã hết.
- **Lần chốt (bản này)**:
  - Jigsaw Puzzle **xong**: ô 14 ("Roll the dice 40 times in Guard Food Street", 40/40) đã Claim trước đó (GO trên đường phố 1 → 2), lần này nhận nốt 2 tim hàng 3 + cột 3. Toàn bộ 16 ô không còn Claim; chấm đỏ nút Jigsaw mất.
  - Guard Food Street **Exchange Shop xong**: 2470 vé → mua gold chest 2000 + bronze chest 400, còn 70 (không đủ món rẻ nhất 400). Judgement sold out.
  - Gieo **2 xúc xắc GO** ở `(1830,935)`: mỗi lần ×100 vé vàng + Fullness 1300 → 1500. Hai bộ đếm xúc xắc về 0, tap tiếp chỉ mở dialog "Source" (chỗ mua) — không mua.
  - Taotie `(160,950)`: 200/1000 Claimed, mốc 2000 **khoá** (đang 1500/5000), bonus 0/300 xám. Đứng máy vì hết xúc xắc.
  - Special Exchange Shop (hub `870,250`): số dư **370** (×100 của xúc xắc vào đây); món rẻ nhất 5600 → không mua được.
  - Food Arcade: Dessert Battle tasks 500/800/1500 đều **Claimed**; Cake March "Event Ended". Chấm đỏ ở hub chỉ là "còn chơi được", không có gì nhận.
  - Food Marble Workshop: bi 0, pudding 0; thang chỉ còn mốc 30/35/40/45 (Amount Used 28) → mốc 30 cần thêm 6 bi, không có. Hết việc.
  - **Chấm đỏ còn lại trong banner**: Guard Food Street trên hub (Taotie chờ 2000) và Food Arcade (còn chơi được) — banner Harvest ngoài danh sách lobby vì thế vẫn còn chấm. Không có gì nhận miễn phí thêm ở thời điểm này.
