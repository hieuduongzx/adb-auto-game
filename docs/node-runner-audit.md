# Audit node và Runner — 2026-10-03

Audit trên working tree hiện tại, gồm thay đổi chưa commit đã có trước lượt này. Phạm vi: catalog Designer, registry/dispatch/traversal của engine, Runner Python/JavaScript, và 6 workflow nguồn. Không tính `workflows/_run/` vì đó là bản tạm do Designer tạo.

## Kết quả chính

- Catalog và registry khớp **105 loại node**; **99 loại chưa bị ẩn**, 6 alias cũ đã ẩn. Con số 99 bao gồm cả node đặc biệt như Start, không phải số mục thực sự xuất hiện trong mọi palette.
- Bộ workflow có **927 node**, dùng **41 loại**. 64 loại chưa xuất hiện trong bộ này; đây là thống kê sử dụng, không đủ căn cứ để xoá tính năng.
- Có **32 node không có đường đi từ Start** và **1 function không được gọi**, chứa thêm 3 node. Không có node type lạ, ID trùng trong cùng graph, dây tới ID không tồn tại, nhiều dây trên cùng cổng ra, hoặc lời gọi tới function thiếu trong phần có thể chạy.
- Đã sửa các lỗi Runner/engine trong bảng bên dưới. Workflow nguồn và node type được giữ nguyên trong lượt audit này.
- Điểm giật Runner đo được khi nhận dồn log: 1.000 dòng giảm từ khoảng **452 ms xuống 33 ms** sau sửa. Log đã được gom theo frame, giới hạn cả hàng đợi lẫn DOM ở 500 dòng mới nhất.

## Danh mục nên gộp

| Ưu tiên | Nhóm hiện tại | Đề xuất cụ thể | Điều kiện giữ đúng hành vi |
|---|---|---|---|
| 1 | `send_text`, `win_send_text` | Một node Type text dùng chung controller | Hai loại hiện có cùng trường `text`, cùng cổng `out` và **cùng handler `_a_send_text`**. Chuyển mục chung sang category hiển thị ở cả hai platform; giữ alias Win32 khi đọc file cũ. |
| 1 | `win_minimize`, `win_maximize`, `win_restore` | Một node Window state với `operation=minimize/maximize/restore` | Ba node đều không có trường tham số, cùng cổng `out`, khác phương thức controller được gọi. Giữ `win_activate` riêng vì đưa cửa sổ ra trước khác thao tác thay đổi trạng thái. |
| 2 | `tap_image` / `tap_image_any` | Một node Tap image hỗ trợ một hoặc nhiều template | Giữ thứ tự ưu tiên, chế độ sequential/parallel, timeout, threshold, vùng tìm, số tap, offset và delay sau khi tìm. Chuyển `template` thành một phần tử `templates` khi migrate. |
| 2 | `if_image` / `if_image_any` | Một node If image hỗ trợ một hoặc nhiều template | Giữ hai cổng true/false và negate. Khi negate danh sách, phải định nghĩa rõ “không có ảnh nào” theo kết quả OR của toàn danh sách. |
| 2 | `wait_image` / `wait_image_any` | Một node Wait image hỗ trợ một hoặc nhiều template | `wait_image` có negate/chờ biến mất; `wait_image_any` hiện chưa có tính năng đó. Không được bỏ negate khi gộp. |
| 3 | `tap` / `win_click` | Một node Tap/Click, thêm lựa chọn button cho Win32 | Giữ mặc định left của Tap, right của Mouse click, `taps`/`clicks`, target và offset. Android chỉ hiện các lựa chọn được backend hỗ trợ. |
| 3 | `win_key` / `win_hotkey` | Một node Press key có modifier Ctrl/Shift/Alt/Win | Giữ Press/Hold down/Release và thời gian hold. Phím Android dùng keycode khác virtual key Windows, nên không gộp trực tiếp với `key`. |
| Có điều kiện | `read_var` / `parse_var` | Một editor Read/Parse text có nguồn OCR/variable và chính sách khi không khớp | Hai node đã gần trùng sau khi Read text có regex. Tuy nhiên `read_var` ghi chuỗi rỗng rồi trả True khi không khớp; `parse_var` trả False. Pattern của Read còn được resolve qua biến, Parse đang dùng chuỗi trực tiếp. Phải giữ các khác biệt này trong migration. |

Hai nhóm ưu tiên 1 giảm số loại hiện trên catalog từ 99 xuống 96. Ba cặp image giảm thêm 3. Nếu thực hiện cả Tap/Click và Key/Hotkey thì còn khoảng 91 loại chưa bị ẩn. Đây là thiết kế đề xuất; chưa đổi catalog hoặc migrate file trong lượt audit.

Việc gộp catalog giúp palette và mã editor gọn hơn. Nó không tự làm canvas nhanh hơn: số node instance, dây và cách cập nhật DOM mới quyết định phần lớn chi phí Designer; xem [đo hiệu năng Designer](designer-performance.md).

### Alias đã được xử lý từ trước

| Alias ẩn | Loại thay thế |
|---|---|
| `double_tap` | `tap`, `taps=2` |
| `swipe_dir` | `swipe`, `mode=direction` |
| `wait_random` | `wait`, `mode=random` |
| `back`, `home` | `key`, keycode 4/3 |
| `win_escape` | `win_key`, keycode 27, press |

Giữ handler/registry cho các alias này để Runner vẫn chạy được file cũ chưa từng mở qua Designer. Không có lợi ích đủ lớn để xoá hỗ trợ chỉ vì palette đã ẩn.

### Các nhóm cần giữ riêng

- **`multi_tap` và `sequence_tap`:** multi-point là nhiều điểm đồng thời, còn sequence tap chạy từng điểm theo thứ tự, có delay và sequence ID để huỷ. `sequence_tap_image` tìm ảnh ở từng bước; `stop_sequence` huỷ sequence có tên. Không phải các alias của Tap.
- **`parallel`, `sequence`, `try_chain`:** chạy đồng thời, chạy tất cả nhánh lần lượt, và thử tới nhánh thành công đầu tiên có luồng điều khiển khác nhau. `try_next` chỉ có nghĩa trong Try chain.
- **`join` và `and`:** Join cho nhánh cuối của một fork tiếp tục; And kiểm tra số nhánh kỳ vọng và trạng thái thất bại. Chuyển đổi trực tiếp làm thay đổi kết quả.
- **If / Wait / Loop until:** kiểm tra một lần, chờ điều kiện đạt trong timeout, và chạy một thân vòng lặp là ba cơ chế khác nhau. Nên dùng chung field/probe code, giữ node riêng cho thao tác đọc graph.
- **`find_image_pos`, `tap_all_images`, `scroll_find`, `wait_stable`:** lưu vị trí, tap mọi match, cuộn tìm và kiểm tra màn hình ổn định có mục đích riêng. Không thay bằng một Tap image chung.
- **App/emulator/window lifecycle:** force-stop, đóng cửa sổ, kill process, uninstall, restart emulator và đổi resolution có phạm vi tác động khác nhau. Giữ riêng hoặc nhóm UI theo thao tác; không xem chúng là node thừa.
- **`if_app` / `win_if_window` và các cặp Wait:** app/title matcher khác kiểm tra trạng thái cụ thể của target window (foreground/minimized/size...). Không gộp chỉ dựa vào tên “đang mở”.
- **Biến, clock, device/window info, screenshot, log, note, notify:** có dữ liệu đầu ra hoặc vai trò hiển thị khác nhau. Chưa dùng trong corpus không đồng nghĩa không cần thiết.

## Node thừa trong workflow hiện tại

Reachability lấy Start đầu tiên, đi theo dây đầu tiên của mỗi cổng ra như engine, dừng tại End/Stop, và xét mọi nhánh có thể chọn. Đây là phân tích cấu trúc: không chứng minh một điều kiện sẽ true/false lúc chạy hoặc một vòng lặp chắc chắn kết thúc. Function được tính là dùng nếu có thể tới nó từ bất kỳ activity nào, kể cả activity hiện tắt.

| Workflow | Tổng node | Node không có đường đi từ Start | Function không được gọi |
|---|---:|---:|---|
| `BrownDust2/workflow.json` | 285 | 0 | 0 |
| `Cherry_Tale/Cherry_Tale.json` | 231 | 4 | 0 |
| `GirlWars/GirlWars.json` | 407 | 28 | `IsInDungeon` (`fn_gx1pv`), 3 node |
| `1/workflow.json` | 1 | 0 | 0 |
| `z/workflow.json` | 1 | 0 | 0 |
| `ZZZ/workflow.json` | 2 | 0 | 0 |

Hai file `1` và `z` chỉ có Start, chưa phải activity hoàn chỉnh có thể kết thúc thành công.

Những node có thể bỏ khỏi canvas nếu không còn là phần đang soạn:

| Graph | Node ID không được chạy từ Start |
|---|---|
| Cherry Tale → **Bang Hội**, `sequence_vf95` | `nul2tpw9`, `nr5siouv`, `nnvdmfi8`, `nydtxtlg` |
| GirlWars → **Guild**, `sequence_xn71` | `nvey2g6g`, `nwy9ir8c`, `nogvabv8`, `nc8i8mzw`, `n5zbt1pa`, `na71tdxd`, `n6kgb00j`, `nny3hu1e`, `n5bh3rk6`, `nd7ptd2y`, `ncr6dj72`, `nfxdfdrc`, `n1g8k6ar`, `nbkz4xkc`, `nc3eo44z` |
| GirlWars → **Event + MIni Games**, `sequence_y0b1` | `nu8inydu`, `n3nzmojq`, `njg8tzwr`, `nwwjgny2`, `n38psnj7`, `nenls77z`, `ni4by1eq`, `nk7wx35h`, `n7cwnirb`, `nza1jbdd`, `nitlz1x2`, `nouwb8xm`, `n6nknbsz` |

`IsInDungeon` có Start/If image/End và không có lời gọi từ phần có thể chạy. Có thể giữ như function thư viện hoặc bỏ khỏi workflow nếu không còn dùng. Những node rời không tốn chi phí handler trong lúc Runner đi qua graph, nhưng vẫn tốn bộ nhớ, dựng graph và vẽ canvas.

## Lỗi Runner/engine đã sửa

| ID | Mức | Trước sửa / cách tái hiện | Sau sửa |
|---|---|---|---|
| R01 | Cao | Giả lập `os.replace` lỗi khi lưu: API vẫn báo True/ok, flow đã đổi, lần lưu sau có thể ghi luôn thay đổi từng bị lỗi | Ghi config trước khi áp dụng giá trị chạy; rollback config khi ghi lỗi; trả False/ok=False. Áp dụng cho checkbox, interval, retries, vars, runtime path, game/emulator path, order, capture và speed setting. File cũ và temp cleanup có kiểm thử. |
| R02 | Cao | Hai API Start/Solo cùng vượt kiểm tra running trong lúc readiness chậm; request mới còn reset trạng thái của run đang kết thúc | Khoá request ở Runner và cả ba entry point engine Start/Solo/Debug; frontend có trạng thái pending. Run đang active từ chối request trước preflight/reset. Stop vẫn dùng được khi engine đã bắt đầu. |
| R03 | Vừa | Node Launch program không nối dây, hoặc nằm trong function không được gọi, vẫn chặn Start vì thiếu path | Preflight chỉ quét đường có thể tới từ Start; scan function dùng stack, không gây recursion error với chuỗi function sâu. Settings vẫn xem được node rời. |
| R04 | Cao | `reorder_activities(['b','b','a'])` nhân đôi activity; frontend bỏ qua kết quả lưu | Dedupe ID, giữ activity bị bỏ sót, chỉ đổi order khi ghi thành công; frontend chờ kết quả và phục hồi order khi lỗi. |
| R05 | Vừa | Infinity gây OverflowError khi đổi retry/index; interval vô hạn và NaN được nhận | Từ chối giá trị không hữu hạn, speed không dương; config ghi JSON chuẩn, không ghi NaN/Infinity. |
| R06 | Vừa | Ctrl+Enter được xử lý trước kiểm tra ô nhập, có thể Start/Stop khi đang gõ; key repeat có thể lặp thao tác | Kiểm tra input/select/textarea/contenteditable và repeat trước shortcut. |
| R07 | Vừa | Reload giao diện mất status từng activity, solo scope, outcome và timer; snapshot cũ ghi đè event sau khi chờ modal | Payload có status/scope/startedAt; dùng chung xử lý snapshot và running event; apply snapshot trước khi chờ changelog/update. |
| R08 | Vừa | Checkbox và Select all đổi UI trước khi API xác nhận; khi lưu lỗi, trạng thái UI khác backend | Chờ API, chống thao tác checkbox trùng, giữ giá trị cũ khi lỗi. |
| R09 | Vừa | Mỗi yêu cầu capture tạo thread riêng, dù capture trước vẫn đang chờ lock | Chỉ có một yêu cầu capture thủ công đang chờ; giải phóng reservation khi worker kết thúc hoặc lỗi. |
| R10 | Cao | Background lỗi lượt đầu giữ `_branch_failed`/Try state sang lượt sau, dù lần sau đã thành công | Reset context mỗi lượt polling. |
| R11 | Cao | Background graph chạy vào dead-end vẫn phát completion=True vì không kiểm tra End | Chỉ báo thành công khi graph đã tới End, tương tự sequence activity. Workflow background dựa vào đường cụt để “thành công” cần nối End rõ ràng. |
| R12 | Cao | Exception trong seed/retry/activity chỉ được log; Runner không nhận failed completion nên có thể báo Completed | Activity/background exception phát completion=False để outcome phản ánh thất bại. |
| R13 | Cao | Disable background xoá worker khỏi registry sau join 0,5s dù worker còn sống; bật lại tạo worker thứ hai; worker cũ tiếp tục node sau | Giữ worker đang kết thúc; truyền cancellation vào walker/parallel branch và delay; từ chối bật lại khi action cũ chưa trả về; Start kiểm tra cả worker cũ. Run kết thúc khi worker cuối đã dọn xong. |
| R14 | Vừa / hiệu năng | Append từng log đọc/ghi scroll layout mỗi dòng; burst 1.000 dòng khoảng 452 ms trên Edge tại máy này | Hàng đợi tối đa 500 dòng, vẽ một fragment theo frame, cập nhật scroll/count một lần mỗi batch; cùng burst còn khoảng 33 ms. Giữ tổng số log, filter, escape HTML, và Clear huỷ batch đang chờ. |

## Phần còn cần lưu ý khi phát triển tiếp

1. **Huỷ giữa một handler đang chạy:** cancellation hiện dừng giữa các node và trong delay của walker. Không ngắt cưỡng bức một lệnh ADB/Win32/OCR đang chặn; một số vòng Wait còn kiểm tra stop chung. Worker đang kết thúc được giữ lại để không tạo run chồng, nhưng có thể phải đợi handler trả về hoặc timeout. Đây là giới hạn của cancellation, không phải xác nhận mọi node có thể huỷ tức thì.
2. **Crash context chung:** `_crash` là record chung được thiết kế để nhánh parallel báo lỗi, nhưng background và sequence cũng dùng chung record/reset. Có nguy cơ gán screenshot/crash point nhầm activity khi chúng chạy đồng thời. Cần chuyển thành context theo activity/fork; audit mã xác định nguy cơ, chưa tái hiện trên thiết bị thật.
3. **Retarget thiết bị khi đang chạy:** API `select_device` vẫn cho đổi ADB handle trong lúc chạy, frontend cập nhật serial trước xác nhận. Cần một quy tắc sản phẩm rõ cho việc đổi target giữa run; audit này chưa thay đổi hành vi này.
4. **Snapshot/event đồng thời:** đã bỏ việc chờ modal trước hydration. Backend/UI chưa có revision number chung để sắp thứ tự snapshot và event trong mọi trường hợp cạnh tranh. Reload có event tới đúng lúc `get_state` vẫn cần kiểm thử mở rộng với native bridge.
5. **Config theo tên workflow:** thư mục override lấy slug/hash từ tên; hai file khác nhau nhưng cùng tên dùng chung config. Hash hiện tránh va chạm do sanitize tên, không phân biệt hai workflow cùng tên. Muốn tách hoàn toàn cần ID workflow ổn định và migration config.

## Kiểm chứng và cách chạy lại

```powershell
python tools/audit_workflows.py --output out/workflow-audit.json
python tools/verify_runner_ui.py --log-benchmark --output out/runner-audit-browser.json
python -m pytest tests -q
$testFiles = @(rg --files tests -g '*.cjs')
node --test $testFiles
```

Kiểm thử Python gồm cả unittest lẫn pytest function. Không dùng riêng `unittest discover` vì nó bỏ qua một phần test Runner.

- Python toàn bộ: **371 passed, 2 failed**, 66 subtests passed. Hai failure đã có sẵn trong file không thay đổi ở lượt này: `test_scope_docked_regions_are_flat_and_page_does_not_scroll_sideways` yêu cầu CSS bo góc 0; `test_shared_tokens_expose_primitive_semantic_and_component_layers` yêu cầu radius 0–2px. CSS/token hiện không đáp ứng các snapshot đó. Không sửa DevScope/theme để ép bộ test xanh trong audit Runner.
- JavaScript: **193 tests passed**. Edge smoke test: **14 checks passed**, không có page error, kiểm tra layout 440px/1280px, log/filter/Clear, shortcut, Start/Stop và checkbox.
- Benchmark log là burst đồng bộ với bridge mock, đo thời gian enqueue + dựng DOM + layout, không tính thời gian mạng/ADB hoặc round trip pywebview. Trước/sau đều giữ tối đa 500 dòng: 100 dòng 37,4 → 6,7 ms; 500 dòng 190,6 → 27,2 ms; 1.000 dòng 452,4 → 32,8 ms. Đây là một lần đo trên máy hiện tại, không phải cam kết mọi tốc độ log.
- Native ADB, emulator, OCR và game window được mock trong regression tests; chưa chạy macro điều khiển thiết bị/game thật. Edge smoke test dùng trang Runner thật với bridge mock.

## Inventory đủ 105 loại

Bảng dưới được tạo từ catalog hiện tại và corpus 6 workflow. “Lượt dùng” tính instance trong JSON, gồm cả node rời và function thư viện.

| Type | Nhóm | Controller | Lượt dùng | Quyết định |
|---|---|---|---:|---|
| `start` | special | both | 58 | Giữ |
| `end` | flow | both | 51 | Giữ |
| `tap` | basic | both | 118 | Gộp Tap/Click (P3) |
| `multi_tap` | basic | both | 0 | Giữ |
| `sequence_tap` | basic | both | 3 | Giữ |
| `sequence_tap_image` | image | both | 0 | Giữ |
| `stop_sequence` | flow | both | 0 | Giữ |
| `double_tap` | basic | both | 0 | Alias ẩn; giữ tương thích |
| `tap_random` | basic | both | 10 | Giữ |
| `long_press` | basic | both | 0 | Giữ |
| `swipe` | basic | both | 12 | Giữ |
| `swipe_dir` | basic | both | 0 | Alias ẩn; giữ tương thích |
| `wait` | basic | both | 7 | Giữ |
| `wait_random` | basic | both | 0 | Alias ẩn; giữ tương thích |
| `send_text` | input | adb | 0 | Gộp Type text (P1) |
| `key` | input | adb | 0 | Giữ |
| `back` | input | adb | 0 | Alias ẩn; giữ tương thích |
| `home` | input | adb | 0 | Alias ẩn; giữ tương thích |
| `tap_image` | image | both | 287 | Gộp Tap image (P2) |
| `wait_image` | image | both | 24 | Gộp Wait image (P2) |
| `if_image` | image | both | 71 | Gộp If image (P2) |
| `tap_image_any` | image | both | 9 | Gộp Tap image (P2) |
| `wait_image_any` | image | both | 1 | Gộp Wait image (P2) |
| `if_image_any` | image | both | 1 | Gộp If image (P2) |
| `tap_text` | ocr | both | 0 | Giữ |
| `wait_text` | ocr | both | 0 | Giữ |
| `if_text` | ocr | both | 3 | Giữ |
| `read_var` | ocr | both | 1 | Gộp có điều kiện; giữ policy lỗi |
| `parse_var` | ocr | both | 8 | Gộp có điều kiện; giữ policy lỗi |
| `tap_color` | color | both | 0 | Giữ |
| `wait_color` | color | both | 0 | Giữ |
| `if_color` | color | both | 1 | Giữ |
| `read_color` | color | both | 0 | Giữ |
| `loop` | flow | both | 29 | Giữ |
| `parallel` | flow | both | 2 | Giữ |
| `sequence` | flow | both | 6 | Giữ |
| `try_chain` | flow | both | 4 | Giữ |
| `try_next` | flow | both | 0 | Giữ |
| `join` | flow | both | 1 | Giữ |
| `and` | flow | both | 0 | Giữ |
| `break` | flow | both | 1 | Giữ |
| `stop` | flow | both | 0 | Giữ |
| `set_var` | logic | both | 8 | Giữ |
| `calc_var` | logic | both | 8 | Giữ |
| `if_var` | logic | both | 51 | Giữ |
| `switch` | logic | both | 1 | Giữ |
| `launch_app` | app | adb | 1 | Giữ |
| `app_stop` | app | adb | 0 | Giữ |
| `app_exit` | app | both | 0 | Giữ |
| `app_uninstall` | app | adb | 0 | Giữ |
| `app_install` | app | adb | 0 | Giữ |
| `if_app` | app | both | 3 | Giữ |
| `wait_app` | app | both | 0 | Giữ |
| `screenshot` | basic | both | 0 | Giữ |
| `log` | misc | both | 2 | Giữ |
| `note` | misc | both | 0 | Giữ |
| `notify` | misc | both | 0 | Giữ |
| `call` | special | both | 121 | Giữ |
| `scroll_find` | image | both | 0 | Giữ |
| `loop_until_image` | image | both | 4 | Giữ |
| `loop_until_color` | color | both | 0 | Giữ |
| `loop_until_text` | ocr | both | 0 | Giữ |
| `loop_until_var` | logic | both | 1 | Giữ |
| `find_image_pos` | image | both | 0 | Giữ |
| `wait_stable` | basic | both | 0 | Giữ |
| `tap_all_images` | image | both | 0 | Giữ |
| `random_branch` | flow | both | 0 | Giữ |
| `format_var` | logic | both | 0 | Giữ |
| `get_time` | time | both | 0 | Giữ |
| `wait_until` | time | both | 0 | Giữ |
| `if_time` | time | both | 0 | Giữ |
| `device_info` | device | adb | 0 | Giữ |
| `screen_power` | device | adb | 0 | Giữ |
| `if_screen_on` | device | adb | 0 | Giữ |
| `if_device_size` | device | adb | 0 | Giữ |
| `adb_shell` | device | adb | 0 | Giữ |
| `launch_emulator` | device | adb | 1 | Giữ |
| `if_emulator` | device | adb | 1 | Giữ |
| `wait_emulator` | device | adb | 0 | Giữ |
| `resize_emulator` | device | adb | 1 | Giữ |
| `kill_emulator` | device | adb | 0 | Giữ |
| `restart_emulator` | device | adb | 0 | Giữ |
| `emulator_resolution` | device | adb | 0 | Giữ |
| `win_send_text` | win32 | win32 | 0 | Gộp Type text (P1) |
| `win_key` | win32 | win32 | 5 | Gộp Key/Hotkey (P3) |
| `win_hotkey` | win32 | win32 | 0 | Gộp Key/Hotkey (P3) |
| `win_escape` | win32 | win32 | 0 | Alias ẩn; giữ tương thích |
| `win_click` | win32 | win32 | 0 | Gộp Tap/Click (P3) |
| `win_scroll` | win32 | win32 | 0 | Giữ |
| `win_mouse_move` | win32 | win32 | 0 | Giữ |
| `win_launch` | window | win32 | 3 | Giữ |
| `win_activate` | window | win32 | 0 | Giữ |
| `win_close` | window | win32 | 0 | Giữ |
| `win_kill` | window | win32 | 0 | Giữ |
| `win_resize` | window | win32 | 4 | Giữ |
| `win_move` | window | win32 | 0 | Giữ |
| `win_minimize` | window | win32 | 0 | Gộp Window state (P1) |
| `win_maximize` | window | win32 | 0 | Gộp Window state (P1) |
| `win_restore` | window | win32 | 0 | Gộp Window state (P1) |
| `win_always_on_top` | window | win32 | 0 | Giữ |
| `win_set_title` | window | win32 | 0 | Giữ |
| `win_style` | window | win32 | 0 | Giữ |
| `win_if_window` | window | win32 | 3 | Giữ |
| `win_wait_window` | window | win32 | 1 | Giữ |
| `win_info` | window | win32 | 0 | Giữ |
