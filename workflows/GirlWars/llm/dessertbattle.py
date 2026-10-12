"""Dessert Battle (Food Arcade, Harvest Food Carnival): chơi tự động để đạt 500 điểm.

  python -u workflows/GirlWars/llm/dessertbattle.py [số_giây]

Luật game (popup "About [Pet Cafe]"):
  - Bánh rơi ngẫu nhiên, mình chọn chỗ rơi (kéo/thả trong khung).
  - Hai bánh giống nhau chạm nhau -> gộp thành bánh cấp cao hơn + điểm.
  - Ba bánh vượt mép khung -> thua.
  - Battle Tasks: 500 / 800 / 1500 điểm -> Claim (dice x1).

Chiến thuật: quét khung chơi, đo đỉnh đống bánh ở từng cột, thả vào cột
đang thấp nhất. Rải đều như vậy thì đống lâu đầy, được nhiều lượt thả hơn,
nên nhiều lần gộp hơn là thả bừa một cột.

Thả bằng `swipe` (kéo từ trên xuống rồi nhả) — `input tap` KHÔNG làm bánh rơi.
"""
import sys
import time

import cv2
import numpy as np

import gw

# Khung chơi (đo trên ảnh 1920x1080): lòng khung trong viền vàng.
X0, X1 = 700, 1460
TOP, BOT = 300, 990
STEP = 40
FALL_MS = 140          # thời gian kéo-thả
SETTLE = 1.25          # chờ bánh rơi + gộp xong


def pile_top(img, x):
    """y của ĐỈNH đống bánh tại cột x (BOT nếu cột trống).

    Phải lấy hàng đậm-màu NHỎ NHẤT (rows.min()): bánh xếp từ đỉnh đống xuống
    sàn nên hàng lớn nhất luôn là sàn, lấy rows.max() thì mọi cột đều trả ~BOT
    và chiến thuật "thả vào cột thấp nhất" mất tác dụng (đã dính một lần).
    """
    col = img[TOP:BOT, max(0, x - 12):x + 12]
    hsv = cv2.cvtColor(col, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] > 95) & (hsv[:, :, 2] > 70)
    rows = np.where(mask.sum(axis=1) > 8)[0]
    if len(rows) == 0:
        return BOT
    return TOP + int(rows.min())


# Bánh đang chờ thả nằm giữa trên khung, ngay trên mép khung.
NOW = (1065, 95)
NOW_R = 30


def hue_at(img, x, y, r=16):
    """Hue trung bình (0-179) của vùng đậm màu quanh (x, y), None nếu không có bánh."""
    z = img[max(0, y - r):y + r, max(0, x - r):x + r]
    if z.size == 0:
        return None
    hsv = cv2.cvtColor(z, cv2.COLOR_BGR2HSV)
    m = (hsv[:, :, 1] > 95) & (hsv[:, :, 2] > 70)
    if m.sum() < 40:
        return None
    h = hsv[:, :, 0][m].astype(np.int16)
    # trung bình vòng (hue là vòng tròn) để đỏ 0/179 không bị lệch
    ang = np.deg2rad(h * 2.0)
    return float(np.rad2deg(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) / 2.0 % 180)


def hue_dist(a, b):
    d = abs(a - b)
    return min(d, 180 - d)


def drop(x):
    gw.swipe(x, TOP - 40, x, BOT - 120, FALL_MS)
    time.sleep(SETTLE)


def play(seconds=240):
    t0 = time.time()
    drops = 0
    blank = 0
    while time.time() - t0 < seconds:
        img = gw.cap()
        cols = list(range(X0, X1, STEP))
        tops = {x: pile_top(img, x) for x in cols}
        cur = hue_at(img, *NOW, r=NOW_R)
        if cur is None:
            # Popup "About [Pet Cafe]" ("Game on!") che mất bánh đang chờ thả.
            # Không dùng gw.modal(): dải bàn gỗ đáy màn tối nên bottom(img) < 12
            # báo nhầm là popup và vòng chơi tự dừng sau ~10 lần thả.
            blank += 1
            if blank >= 2:
                print('ván kết thúc (không còn bánh chờ thả)', flush=True)
                break
            time.sleep(0.6)
            continue
        blank = 0

        best, best_key = None, None
        for x in cols:
            top = tops[x]
            if top >= BOT - 5:
                top = BOT          # cột trống tính là "đầy cao" để ưu tiên rải chỗ khác
            # bánh trên cùng của cột: mẫu ngay dưới đỉnh đống
            h = hue_at(img, x, min(BOT - 6, top + 16), r=14)
            match = 0.0
            if cur is not None and h is not None:
                d = hue_dist(cur, h)
                match = max(0.0, 1.0 - d / 22.0)   # cùng loại bánh -> hue gần trùng
            # ưu tiên: cùng màu trước, rồi tới cột thấp (đống lâu đầy)
            key = (match, top)
            if best_key is None or key > best_key:
                best, best_key = x, key
        if best is None:
            best = max(cols, key=lambda x: tops[x])
        drop(best)
        drops += 1
    print('đã thả %d lần' % drops, flush=True)
    return drops


if __name__ == '__main__':
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    play(secs)
    gw.save(gw.cap(), 'db_auto_end.png')
