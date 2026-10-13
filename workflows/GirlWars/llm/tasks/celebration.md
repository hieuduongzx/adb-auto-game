# Task 4: Celebration (nút Celebration ở lobby)

Vào: lobby, tap **Celebration** `(920, 150)`. Thoát: mũi tên `(75, 50)`.

## Cấu trúc
- Màn chọn có 3 sự kiện: Sacred Tree `(500,600)`, Fantasy Garden `(960,600)`, Picnic Memories `(1420,600)`.
- Chỉ mở sự kiện có chấm đỏ (hiện tại: Picnic Memories).

## Picnic Memories
Vào `(1420,600)`. Menu trái: Picnic Anecdote, Picnic Shop, Picnic Quest, Picnic Treasured, Overview.
- **Picnic Quest** `(265,468)`: danh sách nhiệm vụ, nút bên phải:
  - **Claim** (vàng): bấm, đóng "Rewards Obtained" bằng `(960,1045)`.
  - **Confirm** (xanh): là nhiệm vụ cần làm. **Phải làm quest luôn để nhận thưởng**, không bỏ qua.
  - Đã Claimed thì danh sách tự đẩy lên, chụp lại trước khi bấm tiếp.
- **Picnic Shop** (chấm đỏ): chưa kiểm tra.
- Mục **Make a VIP Shop purchase** cần mua tiền thật: bỏ qua.

## Quest đã biết cách làm
- **Smelt Equipment 100X**: Claim (đã xong).
- **Join Guild Trials 1X**: Claim (đã xong).
- **Quick Battle 1X during the Campaign**: Confirm → World → rương Idle Incomes `(960,950)` → Claim idle → bấm **Quick Battle** `(1260,860)` → popup **Quick Battle 2 Hrs** `(955,655)` dùng lượt Free (2/2). Sau đó Claim nhiệm vụ.
- **Challenge Dungeon 1X**: Confirm đưa vào Dungeon. Chưa chạy được Battle (bấm `(1535,940)` và `(1540,960)` không mở trận). **Chưa giải quyết.** Lần sau: chụp, tìm nút Battle đúng, hoặc hỏi user.
- **Sign-in daily**: đã Claimed.

## Bẫy
- Tap liên tiếp không chụp: vào nhầm Dungeon hoặc World. Luôn chụp giữa các bước.
- Chuyển cảnh mất 3-5 giây, chụp sau khi chờ.
