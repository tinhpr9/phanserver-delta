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
