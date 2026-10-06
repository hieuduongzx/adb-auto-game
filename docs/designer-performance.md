Đã kiểm tra và tối ưu hiệu năng Node Designer ngày 2026-10-03.

Các nguyên nhân chính:

- Mỗi lần kéo node đều đo lại cổng của toàn đồ thị, xóa SVG và tạo lại mọi dây.
- Khi dựng node, mỗi cổng và badge cảnh báo quét lại danh sách cạnh; màu dây hội tụ cũng quét toàn bộ cạnh cho từng dây.
- Minimap, căn chỉnh và trạng thái chạy tìm từng node bằng truy vấn DOM; tô màu nhánh tìm lại toàn bộ dây cho từng node.
- Node ảnh vẫn gọi Python để tải thumbnail khi preview tắt.
- Mỗi sự kiện mousemove xử lý ngay; phím mũi tên dựng lại toàn bộ canvas.

Đã thêm chỉ mục node/cổng/cạnh cho mỗi lượt dựng, bộ tra cứu DOM theo ID và danh sách dây đi ra từng node. SVG được tái sử dụng, giữ focus và màu trạng thái chạy. Khi kéo, chỉ dịch tọa độ cổng của các node đã di chuyển và cập nhật dây liên quan; thứ tự vẽ theo độ dài dây vẫn được giữ. Kích thước phục vụ căn chỉnh được đo một lần khi bắt đầu kéo. Mousemove được gộp theo requestAnimationFrame và xử lý vị trí đang chờ trước mouseup. Undo lưu vị trí gốc trước lần di chuyển đầu tiên. Phím mũi tên cũng chỉ cập nhật vị trí và dây liên quan.

Thumbnail chỉ được tải khi bật preview; phản hồi ảnh đến muộn không thể ghi đè ảnh mới. Mỗi lần đổi cấu trúc canvas, các chỉ mục được dựng lại để phản ánh thêm/xóa cạnh, đổi cổng và undo. Canvas rỗng giải phóng bộ tra cứu.

Đo bằng Edge Chromium 154.0.4258.48, headless, viewport 1600×1000, đồ thị chuỗi với khoảng 20% node ảnh và preview tắt. Mỗi phép đo lấy trung vị của 9 mẫu sau 2 lượt làm nóng. Thời gian gồm JavaScript và layout bắt buộc, không đo FPS hoặc thời gian GPU paint. Python bridge được giả lập; số yêu cầu thumbnail vẫn được đếm. Kết quả phụ thuộc tải máy.

| Node | Kéo trước / sau (ms) | Dựng lại canvas trước / sau (ms) |
| ---: | ---: | ---: |
| 100 | 8,8 / 1,5 | 26,8 / 18,7 |
| 500 | 39,4 / 2,3 | 139,4 / 73,6 |
| 1.000 | 224,0 / 8,8 | 369,7 / 297,3 |

| Thao tác với 1.000 node | Trước (ms) | Sau (ms) |
| --- | ---: | ---: |
| Vẽ lại toàn bộ dây | 63,3 | 25,7 |
| Minimap | 49,3 | 2,7 |
| Áp lại trạng thái chạy toàn đồ thị | 505,4 | 28,1 |

Số yêu cầu thumbnail khi preview tắt giảm từ 199 xuống 0 với 1.000 node.

Kiểm chứng: 186 test JavaScript, 299 test Python, kiểm tra cú pháp và 11 kiểm tra trên DOM thật của Chromium đều đạt. Các kiểm tra trình duyệt bao gồm giữ focus dây, hình học dây khi di chuyển nhiều node, màu nhánh, bật/tắt preview, canvas ẩn, mouseup trước frame kế tiếp, undo/redo và giải phóng bộ tra cứu.

Đo lại từ thư mục dự án, với Python Playwright và Microsoft Edge đã cài:

```powershell
python tools/benchmark_designer.py --verify --output out/designer-performance.json
```

Dữ liệu đo trong phiên này: `out/designer-performance-before.json` và `out/designer-performance-after.json`. Các file trong `out/` là kết quả cục bộ và không được commit.

Dựng lại toàn bộ canvas vẫn tạo DOM cho mọi node, nên thay đổi cấu trúc hoặc mở đồ thị lớn còn có thể gây khựng ngắn. Tác vụ này chưa bổ sung render theo viewport, chưa đo bên trong pywebview đang kết nối thiết bị và chưa đo chi phí tải ảnh thật khi bật preview.
