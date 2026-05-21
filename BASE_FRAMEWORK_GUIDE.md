# Base Game Automation Framework

Framework này giúp dễ dàng phát triển các tool automation cho nhiều game khác nhau với hỗ trợ GUI dựa trên Webview.

## Cấu trúc

```
src/
├── games/
│   ├── base_game.py          # Base class chính
│   ├── bd2/
│   │   └── bd2.py            # Ví dụ: BD2 automation
│   └── template.py           # Template cho game mới
├── gui/
│   ├── __init__.py
│   ├── webview_gui.py        # GUI sử dụng pywebview
│   └── static/
│       └── index.html        # Frontend HTML/CSS/JS
└── core/
    └── adb/
        └── auto/
            └── automation.py # ADBGameAutomation gốc
```

## Công nghệ GUI

GUI sử dụng **pywebview** - cho phép tạo desktop app với công nghệ web (HTML/CSS/JS) mà không cần bundler phức tạp như Electron.

### Ưu điểm của pywebview:
- Nhẹ, không cần bundle Chromium
- Sử dụng web engine của OS (Edge/WebKit)
- Giao tiếp Python ↔ JS qua API đơn giản
- Dễ dàng tùy chỉnh UI với HTML/CSS

## Tạo Game Mới

### 1. Kế thừa từ BaseGameAutomation

```python
from src.games.base_game import BaseGameAutomation, Activity
from typing import List

class MyGame(BaseGameAutomation):
    def __init__(self):
        super().__init__()
        self.assets_path = "assets/mygame"
        self.templates_dir = f"{self.assets_path}/templates"
    
    def define_activities(self) -> List[Activity]:
        """Định nghĩa các activity cho game"""
        return [
            Activity(
                id="login",
                name="Auto Login",
                description="Login vào game",
                enabled=True,
            ),
            Activity(
                id="daily",
                name="Daily Quests",
                description="Làm nhiệm vụ hàng ngày",
                enabled=True,
            ),
        ]
    
    # Activity handlers - đặt tên theo pattern: handle_activity_<id>
    def handle_activity_login(self) -> bool:
        """Xử lý login"""
        if self.find_and_tap(f"{self.templates_dir}/login_button.png"):
            return True
        return False
    
    def handle_activity_daily(self) -> bool:
        """Xử lý daily quests"""
        # Implement logic here
        return True
```

### 2. Các Activity Status

- `PENDING` - Chờ chạy
- `RUNNING` - Đang chạy
- `COMPLETED` - Hoàn thành
- `FAILED` - Thất bại
- `SKIPPED` - Bỏ qua

### 3. Các phương thức hữu ích

#### Template Matching
```python
# Tìm và tap
self.find_and_tap(template_path, threshold=0.8)

# Chờ và tap
self.wait_and_tap(template_path, timeout=10)

# Chờ template xuất hiện
self.wait_for_template(template_path, timeout=10)

# Tìm template (trả về tọa độ)
result = self.find_template(template_path)
if result:
    x, y, confidence = result
```

#### Progress Updates (cho GUI)
```python
def handle_activity_daily(self) -> bool:
    self.update_activity_progress(0.0)   # Bắt đầu
    
    # Step 1
    self.update_activity_progress(25.0)
    
    # Step 2
    self.update_activity_progress(50.0)
    
    # Step 3
    self.update_activity_progress(75.0)
    
    # Hoàn thành
    self.update_activity_progress(100.0)
    return True
```

#### Pause/Resume
```python
# Trong activity handler, kiểm tra pause
self.wait_and_check_pause(timeout=0.1)

# Hoặc sleep có thể bị interrupt
self.safe_sleep(2.0)  # Sleep 2 giây, có thể bị dừng
```

## Chạy với GUI (Webview)

### Cách 1: Sử dụng launcher.py

```bash
# Chạy CLI
python launcher.py bd2

# Chạy với Webview GUI
python launcher.py bd2 --gui

# Liệt kê các game có sẵn
python launcher.py --list
```

### Cách 2: Import trực tiếp

```python
from src.gui.webview_gui import run_with_webview, run_cli
from src.games.bd2.bd2 import BD2

# Chạy CLI
run_cli(BD2)

# Chạy với Webview GUI
run_with_webview(BD2, "BD2 Automation")
```

### Cách 3: Tạo GUI tùy chỉnh

```python
from src.gui.webview_gui import WebviewGUI
from src.games.bd2.bd2 import BD2

game = BD2()
gui = WebviewGUI(game, "My Custom Title", width=1200, height=800)
gui.start()
```

### Cách 4: Tùy chỉnh HTML/CSS/JS

File HTML mặc định được tạo tại `src/gui/static/index.html`. Bạn có thể:
1. Sửa file này trực tiếp để tùy chỉnh UI
2. Hoặc tạo file HTML riêng và truyền vào `WebviewGUI`

Ví dụ tùy chỉnh:
```python
# Sử dụng HTML tùy chỉnh
gui = WebviewGUI(
    game,
    title="My Game",
    html_path="path/to/custom.html"
)
```

## Cách hoạt động của Webview GUI

### Python Backend → JavaScript Frontend

Python gọi JavaScript qua `window.evaluate_js()`:
```python
# Trong Python (webview_gui.py)
self.window.evaluate_js(f"window.handleBackendEvent('{event}', {json.dumps(data)})")
```

JavaScript nhận event:
```javascript
// Trong HTML
window.handleBackendEvent = function(event, data) {
    switch(event) {
        case 'activity_start':
            console.log('Activity started:', data.name);
            break;
        case 'progress':
            updateProgress(data.activity_id, data.progress);
            break;
    }
};
```

### JavaScript Frontend → Python Backend

JavaScript gọi Python API qua `pywebview.api`:
```javascript
// Trong HTML
const result = await pywebview.api.start_automation();
const data = JSON.parse(result);
```

Python expose method qua decorator:
```python
# Trong Python (webview_gui.py)
@webview.expose
def start_automation(self) -> str:
    # ... logic here
    return json.dumps({'success': True})
```

## Callbacks cho GUI

Bạn có thể đăng ký callbacks để nhận thông báo:

```python
def on_activity_start(activity):
    print(f"Activity {activity.name} started")

def on_progress(activity_id, progress):
    print(f"{activity_id}: {progress}%")

game = MyGame()
game.register_callback('on_activity_start', on_activity_start)
game.register_callback('on_progress', on_progress)
```

Các events có sẵn:
- `on_start` - Automation bắt đầu
- `on_stop` - Automation dừng
- `on_activity_start` - Activity bắt đầu
- `on_activity_complete` - Activity hoàn thành
- `on_activity_failed` - Activity thất bại
- `on_progress` - Progress cập nhật
- `on_error` - Có lỗi xảy ra
- `on_status_change` - Trạng thái thay đổi (pause/resume)

## Tùy chỉnh Activity Order

```python
game = MyGame()

# Thay đổi thứ tự
game.set_activity_order(['daily', 'login', 'farm'])

# Bật/tắt activity
game.set_activity_enabled('farm', False)
```

## Lấy Status

```python
status = game.get_status()
print(status)
# {
#     'running': True,
#     'paused': False,
#     'current_activity': 'daily',
#     'activities': [...],
#     'performance': {...}
# }
```

## Ví dụ: BD2 Refactored

Xem file `src/games/bd2/bd2.py` để thấy ví dụ đầy đủ về cách refactor từ ADBGameAutomation sang BaseGameAutomation.

## Lưu ý

1. **Template paths**: Luôn sử dụng `self.get_template_path(filename)` để lấy đường dẫn đầy đủ
2. **Activity handlers**: Phải đặt tên theo pattern `handle_activity_<id>`
3. **Return values**: Activity handler phải trả về `True` (thành công) hoặc `False` (thất bại)
4. **Progress**: Gọi `self.update_activity_progress()` để cập nhật tiến độ cho GUI
