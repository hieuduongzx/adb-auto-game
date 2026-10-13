# Task 2: Summon (lượt Free)

Chỉ quay lượt **Free** (hoặc Draw miễn phí có chấm đỏ). Không bấm Draw 1X/5X/8X/9X/10X khi có vé hoặc gem, trừ khi user nói rõ loại tiền.

## ⛔ KHÔNG BAO GIỜ nhận diện nút Free bằng màu

**Bài học 13/10/2026 — đã mất 5 vé vì lỗi này.** Nút "Free 1x" và nút "Draw 1x" **cùng
một pill xanh dương, cùng toạ độ, cùng kích thước**; chúng chỉ khác phần chữ và việc có
icon vé hay không. Một detector theo màu (`b>200 & r<150 & 120<g<215`) khớp **cả hai**, nên
vòng lặp "quét tab, bấm Free" đã bấm Draw 1x liên tiếp và tiêu **5 vé** (16 → 11) trên
banner Liu Bang. Ảnh `_out/daily_134_sum_exquisite.png` chụp đúng lúc đó cho thấy pill ghi
`1  Draw 1x` — tức là **sau khi hết Free, pill xanh vẫn còn nguyên hình dạng cũ**.

Bắt buộc trước khi bấm bất kỳ nút quay nào:

1. **Đọc chữ trên pill** (OCR / crop phóng to) và chỉ bấm khi chuỗi là `Free 1x`
   (hoặc đúng chữ `Free`). Có `Draw` trong chữ → **không bấm**.
2. **Kiểm tra icon vé**: pill `Draw 1x` mang icon vé + số `1`/`10`; pill `Free 1x` không có.
   Thấy số lượng vé trên pill → không bấm.
3. Nếu màn có dòng `Free in HH:MM:SS` → banner đó **đã hết lượt Free hôm nay**, dừng lại,
   đừng thử bấm thêm.
4. Đếm vé trước và sau mỗi lần bấm (ô vé trên thanh trên). Số vé giảm → đã tiêu vé, dừng ngay.

Quy tắc an toàn: **thà bỏ sót một lượt Free còn hơn tiêu một vé.** Nghi ngờ thì chụp ảnh
và dừng, báo user.

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
- **13/10/2026: tái phạm đúng lỗi trên, mất 5 vé.** Lần này là do bot tự động (detector màu)
  chứ không phải đọc nhầm bằng mắt — xem mục "KHÔNG BAO GIỜ nhận diện nút Free bằng màu" ở đầu file.
  Ban đầu tưởng các tab cột trái (Exquisite Summon / Encounter Redux / Beautiful Encounter /
  Beloved Promise / Lost Pearl) là banner khác nhau, nhưng các tap `(110, 232/400/570/740/915)`
  **không đổi banner** — vẫn đứng ở Liu Bang, nên vòng lặp bấm Draw 1x trên cùng một banner.
  Cột trái thật ra ở y≈150/330/500/670/840, không phải các mốc đã dùng.
- Nút Free trong Merlin / Summon cần chụp để kiểm tra vị trí, vị trí các tab thay đổi theo event.
