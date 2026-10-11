# Index task GirlWars (lobby)

Lobby đã kiểm tra. Các task theo icon có chấm đỏ (tọa độ 1920x1080):

| # | Task | Icon | Tọa độ | Ghi chú |
|---|---|---|---|---|
| 1 | Quest | Quest | (1220,150) | Nhận thưởng nhiệm vụ, Claim All nếu có |
| 2 | Mail | Thư (6) | (378,150) | Nhận đính kèm miễn phí |
| 3 | Celebration | Trống | (920,150) | Sự kiện lễ hội |
| 4 | Event | Quạt | (1070,150) | Sự kiện chung |
| 5 | Arena | Trống Arena | (1745,415) | 5 mode, xem `arena.md` — lần chạy 11/10 đã dọn |
| 6 | Adventure | Torii | (1345,400) | Phiêu lưu, nhận thưởng |
| 7 | Bond Festival | Đang diễn ra | (1745,700) | Sự kiện — xem `bondfestival.md` |
| 8 | Guild | Guild | (1795,940) | Nhiệm vụ/điểm guild |
| 9 | Hero | Hero | (810,990) | Nhận thưởng |
| 10 | Bag | Túi | (980,990) | Nhận thưởng |
| 11 | Mansion | Mansion | (1135,990) | Nhận thưởng |
| 12 | Shikigami | Shikigami | (1300,990) | Nhận thưởng |
| 13 | Rune | Rune | (1470,990) | Nhận thưởng |
| 14 | Downtown | Downtown | (1625,990) | Nhận thưởng |
| 15 | Starchaser Isle | Banner cột phải | chưa chốt | Sự kiện — xem `starchaser.md` |

Quy tắc chung: chỉ bấm Claim/Free/nhận miễn phí. Bỏ qua nút giá $, gem, vàng mua, Top-up, Mall, Recharge, Confirm mua hàng, và các trận PvP cần thể lực/vé nếu không được yêu cầu.
Thoát về lobby: `(75,50)`.

## Bond Festival — đã làm, tách sang `bondfestival.md`
Đã dựng bot tự động wander (`bondfestival.py`, `bondfestival_grind.py`) và dọn sạch reward
miễn phí của event. Cấu trúc màn hình, kinh tế Festival Popularity, các bẫy đã gặp và quy
tắc an toàn tiền tệ nằm hết trong `bondfestival.md`.

## Trạng thái mới nhất (11/10/2026)
- [x] **Arena** — dọn xong cả 5 mode, chi tiết trong `arena.md`: Dawnstar Cup Path of Champions
  Claim All (35/60), Martial Arts Cup Achiv + 5 trận thắng (rank 29), Spa Battle Exclusive SPA.
  Còn dở: Dimensional Arena còn 9 lượt nhưng nút Challenge không phản hồi; Arena thường hết lượt.
- [x] Quest: Claim All daily, Rewards Standard Lv.3 (battle pass). Tránh gói Fantasy Skin $14.99.
- [x] Mail: Read All (không Delete All). System Mail: Claim All (gem x300 + rương).
- [ ] Event, Adventure, Guild, Hero, Bag, Mansion, Shikigami, Rune, Downtown, World: CHƯA làm.
- [ ] Benefits: Weekly Pass, Monthly Pass, mục cuối menu trái (chưa xác nhận).

Bài học: không tap liên tiếp khi chưa xem ảnh giữa các bước; tap vào vùng Claim có thể mở màn khác (Dungeon).
