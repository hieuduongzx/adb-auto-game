# Task 2: Summon (lượt Free)

Chỉ quay lượt **Free** (hoặc Draw miễn phí có chấm đỏ). Không bấm Draw 1X/5X/8X/9X/10X khi có vé hoặc gem, trừ khi user nói rõ loại tiền.

## Vào màn Summon
- Từ lobby: nút **Summon** trên thanh trên, khoảng `(1517, 150)`.
- Hoặc từ banner có trang Summon (ví dụ Morgan, Beautiful Encounter, Beloved Promise).

## Cấu trúc màn Summon
- **Cột trái** (các tab, thứ tự theo banner): Encounter Redux `(125,200)`, Beautiful Encounter `(125,390)`, Beloved Promise `(125,575)`, Lost Pearl `(125,760)`, Solomon `(125,950)`. Cột này có thể cuộn: vuốt `(125,800)->(125,300)` để thấy các tab phía dưới (Sweet Roulette, Artifact of gods, Unique, Fantastic Capsule, Lucky Restaurant...).
- **Cột phải** (bên phải màn): Rewards Preview `(1800,200)`, Collection `(1800,350)`, Lucky Ranking `(1800,490)`, UR Evolution `(1800,640)`, UR·EX Evolution `(1800,800)`. **Các mục này có thể có chấm đỏ và chứa lượt Free riêng** — phải kiểm tra, không được bỏ qua.
- **Nút quay** ở dưới: "Free 1X" (xanh dương, có chấm đỏ khi còn lượt) và "Draw" (vàng, tốn vé/gem — không bấm).

## Quy trình
1. Vào màn Summon, chụp ảnh.
2. Ở cột trái: tap từng tab có chấm đỏ, chụp, bấm **Free** nếu có. Nếu có "Free in HH:MM:SS" thì đã dùng hết hôm nay.
3. Cuộn cột trái xuống hết, lặp lại bước 2 với các tab còn lại.
4. Ở cột phải: tap từng mục có chấm đỏ, chụp; nếu có Free thì bấm Free, nếu chỉ có Draw có tốn tiền thì bỏ qua.
5. Sau mỗi lượt Free: đóng "Rewards obtained / Congratulations" bằng `(960,1045)`, kiểm tra màn Summon còn chấm đỏ không.
6. Ra khỏi Summon bằng mũi tên trong game `(75,50)`.

## Đã có kết quả
- Morgan (Sorceress of Avalon): Free 1X → Morgan EX Shard x3. Hết Free.
- Beautiful Encounter: Free 1X → Constantine x3. Hết Free.
- Beloved Promise: Free 1X. Hết Free (đếm ngược ~24h).
- Encounter Redux: Free đã dùng, đếm ngược.
- Artifact of gods: không có Free.
- Unique: Free 1X → Gem Shard x5.
- Fantastic Capsule: Draw 1X Free → Túi x1 (lần 2: đã dùng, đếm ngược 14:22).
- Artifact of gods: Free 1X (1/1) → vật phẩm x2. Hết Free.
- Unique: Free 1X (1/1) → Gem Shard x5. Hết Free. Draw X10 tốn vàng 800K, bỏ qua.
- Sweet Roulette: Free 1X → đã dùng (đếm ngược 14:21). Draw 1X tốn gem 100, bỏ qua.
- Lucky Restaurant: có 3 mục, phải mở từng biển bên phải: Advanced SR (Free đã dùng, đếm ngược 7H57M), Special SSR (Free 1X → nhận, đếm ngược 23H59M), Preview. Draw tốn gem, bỏ qua.
- Exquisite Summon (Liu Bang UR·EX): Free 1x → gem x20. Hết Free (đếm ngược 23:59:44).
- Lost Pearl: không có Free, chỉ Draw 1X/10X tốn ngọc trai. Bỏ qua.
- **Encounter Redux** (tab đầu, banner Morgan): Free 1X → Augustus x3. Hết Free (đếm ngược ~24h).
- **Charlemagne**: Free 1X → gem x20.
- **Date Masamune**: Free 1X → trăng xanh x20 (item xanh lá).
- **Takenaka Hanbei**: Free 1X → Hanbei x1.
- **Team Leader** (Toyotomi Hideyoshi): Free 1X → Hideyoshi x1.
- **Solomon**: Free 1X → Evolution Shard of Solomon x10.
- **Beloved Promise** (Tokugawa Ieyasu): Free 1X → Ieyasu x1.
- **Lost Pearl — Wish Power Rewards** (icon `(1700,415)`, hiện `N/100`): bấm → popup "Wish Power Rewards" → **Claim All** `(960,699)`. Đã nhận ở mốc 90/100 (đổi 50 ngọc trai lấy quà); Solomon mốc 50/100 cũng Claim All được.
- **Beautiful Encounter**: rương quà draw-count ở góc dưới phải `(1705,935)` — "Draw 5 times to automatically obtain rewards!" → Confirm `(960,721)` → +12 box. Vẫn còn chấm đỏ ở rương nhưng đã nhận.
- Cột phải: thay đổi theo banner (Preview, Gallery/Collection, Luck Ranking, UR Evolution, UR·EX Evolution, Claim Reward ở Liu Bang; Confirm, Fantasy Garden ở Lost Pearl). **Chưa kiểm tra đủ các mục này trên mọi banner.** Lần sau phải tap từng mục có chấm đỏ.

## Bẫy đã gặp
- Lucky Restaurant và các màn tương tự có nhiều biển/mục ẩn phía sau: phải tap từng biển, không đợi user nhắc. Mình đã bỏ qua SSR lần đầu nên bị sót lượt Free.
- Lần trước mình đã bấm Draw 10X (40 vé) khi user chỉ bảo "free". Không làm lại.
- Có "Draw 1X" hiện vé 1 — đừng nhầm với Free.
- Nút Free trong Merlin / Summon cần chụp để kiểm tra vị trí, vị trí các tab thay đổi theo event.
