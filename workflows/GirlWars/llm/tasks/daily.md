# Daily routine (chạy mỗi ngày mới)

Quy trình cố định cho một ngày mới. Thứ tự dưới đây là thứ tự đã kiểm chứng.

## Bước 0 — Auto daily của game

Lobby có icon **chibi** ở trên cùng, tâm **`(790, 45)`** (không phải `(960,30)` — toạ độ đó
trúng thẻ banner, làm banner tự đổi và không mở gì). Bấm vào → panel **Nene the Assistant**.

Đợi bằng `gw.wait_auto_done()` — nó template-match panel **"Complete"**
(`templates/auto_complete.png`, 269×70; panel thật khớp **0.916**, màn idle chỉ ~0.20,
ngưỡng `COMPLETE_MIN = 0.60`). **Không** đoán bằng màu nút hay độ sáng màn hình: auto pass
chạy qua rất nhiều màn khác nhau nên heuristic màu báo sai liên tục.

Xong thì `gw.dismiss_auto_panel()` để bấm nút Complete rồi đi tiếp.

**⚠️ Sau khi bấm Complete, panel Nene vẫn còn nguyên** — nó KHÔNG tự đóng và KHÔNG trả về
lobby. Tệ hơn: Nene là panel sáng, không dim, không có card trắng, nên `gw.modal()` trả
`False` và `gw.has_back()` cũng `False` → `gw.to_lobby()` tưởng đã ở lobby rồi và trả về
`True` ngay. Mọi tap sau đó rơi vào panel Nene và không làm gì.

Thoát Nene: **bấm lại chính icon chibi `(790, 45)`** — nó nằm trên panel và toggle đóng/mở.
(Không dùng Back hệ thống: chỉ bật hộp thoại "Confirm to exit the game?".) Nhận biết Nene:
template `templates/nene_title.png` (crop `img[28:96, 560:1360]`), score 1.0 khi đang mở,
~0.3 khi đã đóng.

Thời gian thực tế: **~57 s** một lượt khi ít việc; **13/10/2026 mất 437 s** vì auto pass
phải chạy qua nhiều mục hơn. `wait_auto_done(timeout=900)` là an toàn; đừng đặt timeout 60 s.

## Bước 1 — Dọn popup & xác định màn

- `gw.clear_modals()` — đóng reward dialog (nút vàng `Claim` `(960,758)`) và popup
  `Tap to continue` `(960,1045)`.
- `gw.modal(img)` phải **không** báo nhầm trên màn danh sách trắng (Quest list trung bình
  ~169, Main Quest ~188). Vì vậy `bright_panel` chỉ được tính khi cả khung đã tối
  (`img.mean() < 110`).
- Về lobby: `gw.to_lobby()`. Về hub banner hiện tại: `gw.to_hub()`.

## Bước 2 — Thứ tự dọn (theo lobby)

1. **Quest** `(1220,150)` → Daily Quests: `Claim All`. Rồi tab Main Quests: bấm từng dòng
   đang có nút cam `Confirm`.
2. **Mail** `(378,150)` → `Read All` (KHÔNG `Delete All`) → System Mail `Claim All`.
3. **Celebration** `(920,150)` → xem `celebration.md`.
4. **Event** `(1070,150)` → xem mục Event dưới.
5. **Benefits** (menu trái) → xem `benefits.md`.
6. **Arena** `(1745,415)` → 5 mode, xem `arena.md`.
7. **Adventure** `(1345,400)` → torii, nhận thưởng.
8. **Bond Festival** `(1745,700)` → xem `bondfestival.md`.
9. **Idle Incomes** (World map, rương `(910,940)`) — claim lại được sau ~30 phút.
10. **Trials → Elite Stage**: mỗi stage có hạn mức riêng trong ngày
    (`Today Elite Stage raid chances left: N/5`), tốn thể lực. Xem `starchaser.md`.
11. **Bottom bar**: Hero `(805,1010)`, Bag `(970,1010)`, Mansion `(1120,1010)`,
    Shikigami `(1290,1010)`, Rune `(1460,1010)`, Downtown `(1640,1010)`, Guild `(1795,1010)`.
12. **Summon** — chỉ quay lượt **Free** (xem `summon.md`). Hết Free thì thôi, không vé/gem.

## Bẫy đã gặp

| Bẫy | Xử lý |
|---|---|
| Nút Back hệ thống (`keyevent 4`) trên màn con bật **"Confirm to exit the game?"** | Cancel là pill **cam** ở `(724,711)` (box `548,672,328,84`); Confirm là pill **xanh** `(1214,713)` — **không bao giờ** bấm Confirm. |
| Cutscene đối thoại (Anecdote, thương nhân Kamiya) chặn màn | Nút tua nhanh `>>` ở `(1640,100)`. Trên màn khác toạ độ này là icon `?` trợ giúp — phải xem màn trước khi bấm. |
| Popup **BIG WIN** (Lucky Ball pinball) | Đóng bằng `Tap to continue` `(960,1045)`. Nút `Confirm` `(963,855)` mở trang **Top-up** (tiền thật). |
| Bag FULL → popup "Bag is full! Go smelt" | Từ chối smelt (auto-select chọn cả đồ **tốt hơn đồ đang mặc** — không đảo ngược được). Game tự bán đồ thừa (`Auto Sell`), claim vẫn chạy. |
| Smelting tự chọn nhầm đồ tốt | Thoát: back → Cancel `(724,711)` → mũi tên `(81,50)`. |
| Bấm nhầm avatar ở lobby | Mở **Account Information** → đóng bằng `Tap to continue` `(960,1045)`. |
| Điểm D-Arena tụt sau reset ngày | Popup **Pts Change** ở đầu ngày báo `Points N (-M)` = điểm bị trừ theo hạng. Bấm `Tap to continue`. |
| Panel **Nene the Assistant** chặn màn sau auto daily | Bấm lại chibi `(790,45)`. Panel này lừa cả `modal()` lẫn `has_back()` — xem Bước 0. |
| Bag FULL khi Claim Idle Incomes | Hộp thoại `Bag is full! Confirm to smelt Equipment?` — hai nút: **Go smelt** (xanh, `(712,669)`) và **Claim Rewards** (vàng, `(1214,669)`). Bấm **Claim Rewards**; smelt tự chọn cả đồ tốt hơn đồ đang mặc và không đảo ngược được. |
| Bấm `(1128,105)` ở màn Guild lại mở **Event** | Panel Guild dùng chung toạ độ với thanh trên của lobby; kiểm tra ảnh trước khi tin màn đã đổi. |

## Quy tắc tiền tệ (không đổi)

Không tiêu: **vé summon banner**, **ngọc đỏ**, **lượt đấu mua bằng gem** (`+` cạnh
`Today chances` / `Today Challenge Chances` / `Attempts`), mọi gói `$`, `Top-up`,
`Deluxe`, `Unlock Power of god`.

Được tiêu: thể lực (stamina) cho raid/daily, và tiền trong game khi luật task cho phép.

---

## Trạng thái lượt chạy 13/10/2026

### Đã nhận (miễn phí)
- **Auto daily** (chibi → Auto Perform → Complete): vàng ×5000, vé ×1, gem ×30, item ×2.
- **Quest → Daily Quests**: Claim All, tiến độ Ngày **0 → 130** (vàng ×250K, xúc xắc ×1,
  kẹo ×1, hộp quà ×1, gem xanh ×100, item). Tab **Main Quests**: toàn bộ dòng đang là
  `Confirm` xanh (chưa xong) hoặc `Claimed` — **không có gì để nhận**, kể cả sau khi cuộn hết.
- **Mail**: Common Mail **Claim All** → vé ×5, thể lực ×5, torii ×5, xúc xắc ×3, quà ×120,
  item ×75, rương ×1. Social Mail: 6 thư, **không có đính kèm**. System Mail: 3 thư đã nhận từ trước.
- **Celebration → Picnic Memories** (2D 00:10 còn lại):
  - Picnic Quest: Claim ×3 (Sign-in daily → vàng ×90K, Join Guild Trials → ×30K, Win Campaign → ×30K).
    Ba claim này **cho 150 Vitality** của event (trước đó 0).
  - Picnic Shop → Shopping District: ô **Daily Free** → vàng ×100K.
  - Picnic Anecdote: **dispatch** tốn 30 Vitality/lần, mỗi lần +vàng ×80K và **+30 Travel Points**,
    kèm một đoạn đối thoại (chọn ô trên = spar, được vàng ×80000). Đã chạy ~6 lượt, tiêu hết Vitality.
  - Picnic Treasured: Travel Points đạt 250 → mở **Treasured Vault**; các ô ở đây **đổi bằng
    tiền event**, không phải Claim/Free → **không mua**.
  - Còn Confirm: `Quick Battle 1X during the Campaign`, `Smelt Equipment 100X` (90/100),
    `Challenge Arena or Dimensional Arena 1X`, `Challenge Dungeon 1X`, `Make a VIP Shop purchase` (bỏ).
- **Event → Hot Deals → Daily Special**: ô **Daily Free** claim được **2 lần** (điểm 0 → 2),
  mỗi lần item ×5. Echo of Love (cần draw), Glorious Girl (chỉ xem), Weekly/Monthly Special
  (không có ô Free) — không nhận được gì.
- **Benefits**: Celestial Vanguard **Claim**; Daily Benefits **Claim**; Privilege Weekly Pass
  **Claim ×2**; Weekly Fund → hàng Standard **Claim All** (gem xanh ×10 + item). Monthly Pass /
  Deluxe Fund / Weekly Pass: chỉ có gói $, không có ô Free.
- **Adventure**:
  - **Labyrinth**: popup Fast Battle → Confirm (miễn phí) → qua 16 tầng → chọn 9/9 loot.
  - **Atlantis**: Poseidon Astrolabe 100 điểm → gem xanh ×50; **Achievements Claim ~15 mốc**
    (tổng cộng tới mốc "Total temple divinations 100 times"). Còn 3 mốc dở (19/20, 63/65, 83/85).
  - **Magical Orchard**: `CLAIM ALL` **không phản hồi**; Order List cả 4 đơn đều **chưa đủ nguyên
    liệu** (0/200, 0/120, 50/40+10/40) → không nhận được gì. Cần quay lại sau.
- **Arena** (lượt đã hồi: Arena 5/5, Martial Arts 5/5):
  - Arena base: Rewards cả 3 tab **không có gì nhận** (Points 0, ACHV `Unachieved`, Daily Rewards
    không có nút). Chấm đỏ vẫn còn — là badge tổng.
  - **World Conquest** (mode mới thay Dawnstar Cup): Rewards → **Weekly Progress Rewards →
    Claim All** (4 mốc ×500/×1000/×1500). Weekly Ranking/Season chỉ xem.
  - **Spa Battle → Exclusive SPA → Common → Claim**: token SPA **×23616**.
  - **Martial Arts Cup**: Achiv **1089/1090 — thiếu đúng 1 điểm** nên vẫn `Not Achieved`, không
    có ô pickup. Participate **5/5 thắng** (đối thủ **Robots_1 / Robots_2, BP 1218K, team thật
    227K** — dễ nhất bảng), merit 1007 → ~1040, rank 22 → 19. **Đối thủ thật trong bảng yếu nhất
    là 121M team power** (mình 80M) → bỏ, chỉ đánh bot.
  - **Dimensional Arena: CHƯA chạy trận nào** (10 lượt còn nguyên).
- **World → Idle Incomes** (rương giữa bản đồ): Idle Time 01:00:03 → **Claim** → vàng ×316K,
  EXP ×85387, Sakura Gloves ×3. Gặp hộp thoại Bag-full, chọn **Claim Rewards** (không smelt).

### ⚠️ Lỗi đã gây ra: tiêu mất 5 vé summon
Bước 12 (Summon) bị hỏng. Trên banner **UR·EX Liu Bang** đã bấm đúng **Free 1x** (vé giữ
nguyên 16). Sau đó một vòng lặp tự động "quét tab cột trái, bấm nút Free" dùng **detector
theo màu xanh dương**; detector này khớp luôn pill **`Draw 1x` (tốn 1 vé)** vì hai pill
giống hệt nhau về màu/kích thước/vị trí. Kết quả: **vé 16 → 11 (mất 5 vé)**, pity 36 → 42/300.
Ngoài ra các tap cột trái `(110, 232/400/570/740/915)` **không đổi banner** (cột trái thật ở
y≈150/330/500/670/840) nên vòng lặp bấm lặp trên cùng một banner.

Đã dừng ngay khi phát hiện. Chi tiết + quy tắc chống tái phạm: **`summon.md`, mục
"KHÔNG BAO GIỜ nhận diện nút Free bằng màu"**.

### Chưa làm
- **Trials → Elite Stage** (bước 10).
- **Dimensional Arena** 10 lượt, **Arena base** 5 lượt.
- **Bond Festival**: chỉ mở xem; Quests toàn 0/N (Visit Stalls, Cheers to Kagura Dance, Exchange
  Stamp Sets, Submit Stamp Exchange), nút `Rewards` trên màn chính **không phản hồi tap**.
- **Guild**: Guild Office, Warship Rush (đăng ký mở), Guild Territory (Bounty Refresh),
  Guild Trials `Attempts 0`. Chỉ mở xem, chưa nhận gì.
- **Summon**: các banner khác (Exquisite Summon, Encounter Redux, Beautiful Encounter,
  Beloved Promise, Lost Pearl) **chưa kiểm tra lượt Free** — cố ý bỏ vì lỗi trên.
