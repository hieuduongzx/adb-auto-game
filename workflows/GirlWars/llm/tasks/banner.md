# Task 1: Banner (việc miễn phí trong danh sách banner)

Đầu vào: game đang ở lobby, không có popup. Tọa độ theo 1920x1080.
Chỉ làm: lượt Free, nhận thưởng có chấm đỏ, mốc đã đủ điều kiện (Claim).
Không làm: nút Draw trả phí, Diamonds Purchase, Top-up, gói $, Pass Deluxe, Shop đổi vé/gem, Confirm mua hàng, Transport Route (cướp), Team Join.

## Quy trình
1. Từ lobby, tap thẻ banner góc trái `(208, 325)` để mở danh sách.
2. **Luôn cuộn lên hết trước**: vuốt xuống 8 lần `swipe(1100,300 -> 1100,900)`.
3. Cuộn xuống từng đoạn `swipe(1100,800 -> 1100,350)`, chụp ảnh mỗi đoạn, ghi lại banner có chấm đỏ.
4. Mở từng banner có chấm đỏ, chụp, xử lý từng icon/nút con có chấm đỏ (xem bảng dưới).
5. Ra khỏi banner bằng mũi tên trong game (`back_btn.png` / `back_btn_dark.png`, góc trái trên khoảng `(75,50)`), **không** dùng Back hệ thống (sẽ hiện hộp "Confirm to exist the game?", luôn bấm Cancel).
6. Hết banner: báo cáo một lần ở cuối, không hỏi giữa chừng.

## Xử lý chấm đỏ thường gặp
| Màn | Việc làm |
|---|---|
| Nút xanh lá "Claim" có chấm đỏ | Bấm, đóng "Rewards obtained" bằng `(960,1045)` |
| Nút "Free" / "Free x1" | Bấm |
| Nút "Claimed" xám có dấu tích | Đã xong, bỏ qua |
| Nút "Start" xám | Không đủ điều kiện, bỏ qua |
| Gói $ / gem / Top-up / Diamonds | Bỏ qua, không bấm |
| Mini game ghép (Merlin) | Cần thể lực; hỏi trước khi chơi |
| Summon | Xem `summon.md` |

## Tọa độ đã biết (1920x1080)
- Thẻ banner lobby: `(208, 325)`
- Mở banner trong danh sách: tap thẻ ở giữa cột phải, toạ độ thay đổi theo lần cuộn — luôn chụp rồi tìm.
- Thoát về lobby từ banner: `(75, 50)` hoặc `(80, 52)`.
- Danh sách banner đổi thứ tự theo thời gian, không dựa vào vị trí cũ.

## Bẫy đã gặp
- Vùng chặn nạp `(0,660)-(300,800)` trong `device.py` chặn cả Eagle's Gift trong Mystic Journey.
- Splash có nút Confirm cam khớp ~0.84, đặt ngưỡng 0.8.
- Bấm nhầm sang Transport Route, 1st Top-up Special Gift (có giá $4.99): thoát ngay.
- Dragon's Bless có bóng nạp kim cương (Duration Limit), không được bấm Diamonds Purchase.

## Ghi chú cho lần sau
- Đừng kết luận chấm đỏ là dấu cũ; bấm thử một cái trước.
- Đừng bỏ qua icon con (Forge Pack, Pass, Tasks, Festival Deals...). Mở hết chấm đỏ trong mỗi banner.

## Kết quả lần chạy này
Danh sách banner xếp lại theo thời gian. Thứ tự sau khi cuộn lên hết:
Harvest Food Carnival → Liu bang UR·EX → Li Bai-Destined Bride → Blossom Bonding Bond Festival →
The Trapped Actress Destined Return → Sorceress of Avalon… (các banner còn lại đều là nạp/gói $).

### Harvest Food Carnival
- **Food Check-In** `(1440,797)` → mở thẳng màn **Warship Rush**: bấm **Board the warship** `(1808,918)` để điểm danh (miễn phí). Ở lobby Warship Rush còn hiện "Open today at 21:05 (EST)".
- **Festival Deals** `(480,437)` → 3 tab: *Festival Exclusive Sale* = Harvest Festival Top-up (**Go** → nạp tiền, bỏ qua),
  *2x Rewards Event* → **SPA Rewards 2x** có **Go** `(639,887)` mở **Spa Battle** (không có quà miễn phí, chỉ đổi quầy).
- Food Arcade / Food Marble Workshop / Guard Food Street / Ranking / Special Exchange Shop: không có chấm đỏ hoặc đang đếm ngược.

### Liu bang UR·EX
- HUB có: Poetry of Encounter / Graceful Warrior / Sincere Heart / Limited Offer / Summon the Bride / Exquisite Summon.
- **Exquisite Summon** Free 1x → EX Shard x3. (Trước đó bắn trúng Exquisite Summon còn ra Free 1x → gem x20.)
- **Hot Deals** (từ nút Claim Reward góc phải màn Summon `(1800,990)`): Daily Special có nút **Free** `(1785,598)` → nhận được; Weekly/Monthly Special đều bán bằng $ (bỏ qua).
- Echo of Love / Lucky Balls / Glorious Girl: chỉ là tiến độ nhiệm vụ, không có nút nhận.
- Poetry of Encounter / Graceful Warrior / Sincere Heart: chỉ hiện popup tooltip, không có quà.
- **Limited Offer** (chấm đỏ ở `(183,911)`) là gói nạp → bỏ qua.

### Li Bai – Destined Bride
- Summon the Bride: chỉ có Draw 1X/10X tốn vé, **không có Free**.
- Exchange → Collection/Echo of Love/Hot spring training/NuptialNight: không có nút Free; phần lớn là minigame tốn tài nguyên.
- Icon **Hero Collection/My Room** (từ banner Bride) mở **My Room**: có **Auto Date** `(1230,947)` — dùng **Vitality** (miễn phí, 10 điểm) → nhận quà (Tiger doll x1…). Hết vitality thì hiện nút **Restore x1 Vitality** — **không bấm** (tốn gem).

### Blossom Bonding Bond Festival
- Landing `(1745,700)` → Go Now → **Shizuka Gozen's Return Gift** Lv10 **Claim** `(1200,977)`.
- Vòng sake: Stamp Book `(140,655)` → Claim All `(1248,165)` → tab Stamp Set `(1478,88)` → Exchange từng ô (bấm `(1557,336)` rồi **MAX** `(1272,762)` → **Exchange** `(1162,880)`).
  Đổi được 6 bộ (1 vàng + 5 xanh) → sake. Tribute ở màn Offer `(960,940)` — **cách 4s** mới ăn.
- Quests › Daily: bấm **Claim** (cam) cho *Dance with God*, *Warm-Up Challenge*. *Bond Parade-2* (Visit 50 Stalls) còn 49/50 — cần wander thêm 1 lần.
- Wander bot `python -u bondfestival.py 40`: chạy 12 lượt với ⚡40 (bot đọc sai ⚡ thành 0 rồi tự dừng ở frame 34-35, nhưng vẫn lên **Popularity Lv4 370/800**).

### Celebration › Picnic Memories
- Picnic Quest → quest cần làm: **Quick Battle 1X** → Confirm → World → **Idle Incomes** `(960,950)`/`(660,862)` Claim → **Quick Battle** `(1260,860)` → popup **Quick Battle 2 Hrs** `(955,655)` dùng 2/2 lượt Free. Xong.
- *Challenge Dungeon 1X*, *Smelt Equipment 100X*, *Make a VIP Shop purchase* vẫn treo (VIP = tiền thật, bỏ qua).

### Lobby khác
- **Benefits › Daily Benefits** `(210,413)` → nút **Claim** `(1800,278)` = Free Supervalue Pack (SSR Mori Motonari) → đã nhận.
- **Mansion › Main City**: nút **Upgrade** `(960,945)` (vàng, 436/360) → Lv.51 → Lv.52. Tab **Skins**: chấm đỏ trên 2 skin SSR → chọn rồi **Equip** `(1508,826)` để tắt chấm.
- **Mansion › Marriage (My Room)**: Auto Date dùng vitality; hết vitality thì dừng, **không bấm Restore**.
- **Quest**: milestone Daily 100 vẫn còn chấm đỏ (bấm không nhận), tab **Rewards** `(88,352)` còn chấm đỏ — chưa rõ nội dung, cần soi lại lần sau.

### Bẫy mới
- Từ màn Summon, nút **Claim Reward** `(1800,990)` mở một HUB event khác (Event/Bag…) chứ không phải popup nhận quà.
- Trên map Bond Festival, sân khấu Kagura trôi theo camera: sau khi cuộn map phải quét lại chỗ có bong bóng sake (lần này ở `(820,400)` rồi `(610,370)`).
- Vuốt ở mép màn có thể kích **hộp thoại "exit the game?"** — luôn bấm **Cancel** `(682,721)`.
