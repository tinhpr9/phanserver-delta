# Original User Request

## Initial Request — 2026-09-12T15:34:50Z

Xây dựng hệ thống kiểm tra ban tài khoản Roblox theo yêu cầu (On-Demand Ban Checker & Auto-Replacement) tiết kiệm hạn ngạch API (Quota-Guard), tự động cách ly tài khoản chết, nạp bù tài khoản từ kho dự trữ và đồng bộ dữ liệu song hành Local - Google Drive bảo toàn File ID tuyệt đối theo Rule 34.

Working directory: /root/phanserver-delta
Integrity mode: development

## Requirements

### R1. On-Demand Roblox Ban Detection with Quota-Guard
Hệ thống chỉ kích hoạt kiểm tra khi nhận được lệnh yêu cầu từ người dùng (qua Telegram Bot hoặc CLI), tuyệt đối không chạy quét ngầm tự động để tránh tiêu tốn hạn ngạch mạng và quota Roblox API. Cơ chế kiểm tra phải gộp nhóm truy vấn (Batch Lookup tối đa 100 usernames/request) qua Roblox API chính thức (`users.roblox.com/v1/usernames/users` và `/v1/users/{userId}`), có bộ đệm kết quả (Quota-Guard Cache) ngắn hạn để ngăn chặn việc gọi lặp lại cùng một tài khoản khi người dùng kiểm tra nhiều lần liên tiếp.

### R2. Strict Dual-Storage Account Isolation and Rule 34 Sync
Khi phát hiện tài khoản Roblox bị ban (`isBanned: true`), hệ thống phải thực hiện chu trình cô lập an toàn:
- Tự động tạo bản sao lưu cục bộ `.bak_<timestamp>` trước khi can thiệp tệp.
- Trích xuất toàn bộ cookie và thông tin liên quan sang tệp lưu trữ `acc_bi_ban.txt` và ghi nhật ký thời gian vào `nhat_ky_ban.txt`.
- Gỡ bỏ hoàn toàn dòng tài khoản khỏi `acc.txt` và `Data_Tong_Cookies.txt` tại cả bộ nhớ máy cục bộ (`/storage/emulated/0/Download/Shouko/`) và Google Drive (`gdrive:`).
- Thao tác đồng bộ lên Google Drive bắt buộc sử dụng cơ chế ghi đè tại chỗ (`rclone copyto`), bảo toàn 100% File ID gốc trên Google Drive (Rule 34) để không làm gãy các script phụ thuộc.

### R3. Automated Replacement from Reserve Account Pool
Hệ thống hỗ trợ cơ chế tự động nạp bù tài khoản thay thế khi có tài khoản trong dàn máy bị ban:
- Đọc từ kho tài khoản dự trữ (`acc_du_phong.txt` hoặc qua tham số lệnh).
- Chèn tài khoản hợp lệ mới vào đúng vị trí section dàn máy chỉ định (ví dụ `M77___(gag2)`), bổ sung cookie tương ứng vào `Data_Tong_Cookies.txt`.
- Đảm bảo regex nhận diện section không bao giờ nhầm lẫn với tên tài khoản có chữ `M` (ví dụ `Mega_Wiley623`).
- Tự động đồng bộ ngay lập tức lên Google Drive qua `rclone copyto`.

### R4. Telegram Bot Control & Interactive Delivery
Tích hợp giao diện điều khiển qua Telegram Bot (`Preiumbot`) trong Cloudflare Worker và Durable Objects:
- Lệnh `/checkban [m_code|all|users]`: Kích hoạt quy trình quét theo máy, toàn bộ máy hoặc danh sách username tùy ý.
- Lệnh `/addacc <m_code> <user1:pass1> [user2:pass2...]`: Thêm tài khoản mới trực tiếp qua chat Telegram.
- Báo cáo kết quả định dạng HTML chi tiết: Tổng số, Sống (Live), Bị ban, Danh sách tài khoản chết, trạng thái dọn dẹp và trạng thái đồng bộ Google Drive.

## Acceptance Criteria

### Ban Detection & Quota Protection
- [ ] Không có bất kỳ cron ngầm hoặc tiến trình nền nào tự động gọi Roblox API khi người dùng không yêu cầu.
- [ ] Truy vấn danh sách tài khoản được batch tối ưu (tối đa 100 usernames/call) và có cơ chế ngắt quãng chống HTTP 429 Too Many Requests.
- [ ] Phân loại chính xác 100% trạng thái `isBanned: true` (Banned) và `isBanned: false` (Live).

### Data Integrity & Dual-Storage Sync (Rule 34)
- [ ] Mọi tài khoản bị ban đều được di chuyển sang `acc_bi_ban.txt` và ghi log vào `nhat_ky_ban.txt`.
- [ ] `acc.txt` và `Data_Tong_Cookies.txt` được cập nhật đồng thời trên cả bộ nhớ cục bộ `/storage/emulated/0/Download/Shouko/` và `gdrive:`.
- [ ] File ID của `acc.txt` (`12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg`) và `Data_Tong_Cookies.txt` (`1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`) trên Google Drive được giữ nguyên 100%, không bị đổi ID sau khi cập nhật.

### Automated Testing Suite
- [ ] Toàn bộ bộ kiểm thử tự động `tests/run_all_tests.sh` vượt qua 100% (7/7 suites: tong_hop_link, telegram_phanserver, fleet_state_2pc, delta_updater, device_agent, account_manager, e2e_flow).
- [ ] Script kiểm chứng production `tests/verify_production_runtime.py` chạy thành công không có lỗi.

## 2026-09-13T14:19:22Z

Khắc phục lỗi bật Tailscale VPN trên máy ảo UgPhone (`m77`): Loại bỏ báo cáo thành công ảo (`TRIGGERED`), hỗ trợ tọa độ bấm thích ứng xoay màn hình ngang/dọc (Landscape/Portrait) trên UgPhone, và báo cáo trung thực địa chỉ IP Tailscale (`100.x.y.z`) qua bot Telegram. Tuyệt đối không thử nghiệm trực tiếp trên máy UgPhone thật mà kiểm chứng bằng unit test tự động.

Working directory: /root/phanserver-delta
Integrity mode: development

## Requirements

### R1. Loại bỏ báo cáo thành công ảo & Báo cáo trung thực IP Tailscale
- Tuyệt đối không trả về `status: OPENED` hoặc báo "ĐÃ BẬT THÀNH CÔNG" khi chưa có interface VPN (`tun0`) hoặc IP mạng nội bộ Tailscale (`100.x.y.z`).
- Khi bật thành công: Phản hồi rõ ràng kèm địa chỉ IP Tailscale (`100.x.y.z`).
- Khi không kết nối được sau thời gian chờ (12s): Trả về `status: FAILED` kèm lý do cụ thể để bot Telegram thông báo rõ ràng cho người dùng thay vì báo ảo `TRIGGERED`.

### R2. Tối ưu kích hoạt Tailscale tương thích máy ảo UgPhone (Landscape & Portrait)
- Hỗ trợ mở app Tailscale với tham số `--user 0` (`am start --user 0 -n com.tailscale.ipn/.MainActivity`) để tương thích Android multi-user.
- Tự động nhận diện hướng xoay màn hình UgPhone (xoay ngang 90°/270° hoặc dọc 0°/180°) để tính toán chính xác tọa độ bấm nút `Connect` (ở giữa màn hình) và công tắc Toggle Switch (ở góc trên bên phải).
- Bổ sung kiểm tra IP trên cả `tun0` và dải IP CGNAT Tailscale `100.x.y.z`.
- Sau khi kết nối thành công, tự động gửi phím `BACK` hoặc `HOME` để ẩn giao diện Tailscale, tránh che màn hình game.

### R3. Nâng cấp xử lý lệnh `/vpn` và `/tailscale` trên Worker & Telegram Bot
- Định dạng tin nhắn Telegram phân biệt rõ:
  * Thành công: `🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.x.y.z`.
  * Thất bại: `❌ BẬT TAILSCALE THẤT BẠI: <Lý do cụ thể>`.
  * Trạng thái `/vpn <device> status`: Hiển thị rõ đang CONNECTED (IP) hay DISCONNECTED.

### R4. An toàn thiết bị: Nghiêm cấm test trên máy UgPhone thật
- Toàn bộ quá trình phát triển và kiểm chứng phải được thực hiện bằng bộ mock unit test / integration test tự động trong thư mục `tests/`. Tuyệt đối không gửi lệnh test làm gián đoạn máy UgPhone thật.

## Acceptance Criteria

### VPN Real Status Enforcement
- [ ] Không còn bất kỳ trường hợp nào bot Telegram báo "ĐÃ BẬT THÀNH CÔNG" khi Tailscale chưa có IP.
- [ ] Khi chạy `CONTROL_TAILSCALE` ở chế độ `on` mà không có IP `tun0`/`100.x.y.z`, kết quả trả về `status: "FAILED"`.
- [ ] Khi có IP, kết quả trả về `status: "OPENED"` và chi tiết chứa tiền tố `CONNECTED: 100.`.

### Telegram Message Format
- [ ] Tin nhắn Telegram hiển thị chính xác địa chỉ IP Tailscale `100.x.y.z` khi kết nối thành công.
- [ ] Tin nhắn Telegram hiển thị lý do lỗi rõ ràng khi không kết nối được.

### Automated Test Suite
- [ ] Bộ kiểm thử `tests/test_device_agent.py` hoặc test chuyên biệt cho Tailscale kiểm chứng đầy đủ các kịch bản: Connect thành công có IP, Timeout không có IP (báo FAILED), Disconnect, Status check.
- [ ] Toàn bộ test suite `bash tests/run_all_tests.sh` vượt qua 100%.
