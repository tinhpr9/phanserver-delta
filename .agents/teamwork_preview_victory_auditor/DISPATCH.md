## 2026-09-14T15:57:25Z
You are teamwork_preview_victory_auditor.
Your working directory is: /root/phanserver-delta/.agents/teamwork_preview_victory_auditor
Your project workspace is: /root/phanserver-delta

<original_task>
Khắc phục triệt để lỗi lệnh `/tablist` hiển thị `❓ (unknown)` trên M77. Nâng cấp cơ chế trích xuất tên tài khoản Roblox trong `agent/agent.py` theo kiến trúc nhiều tầng (multi-tier fallback):
1. Đọc chính xác file `appStorage.json` (`/data/data/{pkg}/files/appData/LocalStorage/appStorage.json` và `/data/user/*/{pkg}/files/appData/LocalStorage/appStorage.json`) bằng nhiều phương thức (`cat`, `su -c`, `/system/bin/su -c`, `/system/xbin/su -c`, `run-as {pkg}`).
2. Tìm kiếm trong shared preferences XML (`shared_prefs/*.xml`).
3. Phân tích `dumpsys activity`.
4. Fallback cấu hình (`acc.txt`): Nếu môi trường sandbox trên Android chặn hoàn toàn việc đọc `/data/data/`, fallback ánh xạ Tab N với tài khoản tương ứng trong phần cấu hình của thiết bị trong `acc.txt` (ví dụ `M77___(gag2)`: Tab 1 -> account 1, Tab 2 -> account 2...), hoặc file cấu hình Shouko (`server_links.txt`), hiển thị rõ ràng tài khoản (ví dụ `username (acc.txt)` hoặc `username` nếu tin cậy).

Requirements:
### R1. Multi-Tier Username Detection in `agent/agent.py`
Nâng cấp hàm `query_tab_list()` và `run_adb_shell()` trong `agent/agent.py`:
- Thêm đường dẫn Roblox chuẩn: `/data/data/{pkg}/files/appData/LocalStorage/appStorage.json` và `/data/user/*/{pkg}/files/appData/LocalStorage/appStorage.json`.
- Bổ sung các lệnh đọc thử: `cat`, `su -c`, `/system/bin/su -c`, `/system/xbin/su -c`, `run-as {pkg} cat files/appData/LocalStorage/appStorage.json`.
- Kiểm tra trực tiếp file qua Python `Path.read_text()` nếu tiến trình có quyền truy cập.

### R2. Deterministic Config Fallback (acc.txt Correlation)
Nếu không đọc được dữ liệu local app qua ADB/shell (do sandbox Android chặn):
- Đọc file `acc.txt` (ưu tiên `config.DEFAULT_ACC_TXT_PATH` hoặc `/storage/emulated/0/Download/Shouko/acc.txt`).
- Tìm section của thiết bị hiện tại (ví dụ `M77___...`), lấy tài khoản theo thứ tự Tab (Tab 1 -> acc 1, Tab 2 -> acc 2...).
- Hiển thị username kèm hậu tố nhận diện `(acc.txt)` hoặc username tương ứng thay vì để `❓ (unknown)`.
- Nếu trực tiếp đọc được từ app data thì ưu tiên hiển thị username thực tế đọc được.

### R3. Preserving Worker & Telegram Formatting
- Đảm bảo HTML output hiển thị đẹp trên Telegram:
  📱 <b>Tab List — M77</b>
  Tab 2: username_real
  Tab 3: username_acc (acc.txt)
  Tab 4: ❓ (unknown)
- Ký tự đặc biệt trong username phải được HTML-escaped an toàn.

Acceptance Criteria:
- Functional:
  - `query_tab_list()` trích xuất thành công username từ `appStorage.json` (cả direct JSON, XML, dumpsys, và fallback acc.txt)
  - Nếu app data bị chặn do permissions, fallback `acc.txt` trả về username tương ứng với Tab thay vì `None`
  - `/tablist` trên M77 hiển thị username cho các tab đang chạy
- Non-Regression & Safety:
  - `bash tests/run_all_tests.sh` pass 7/7 suites
  - `python3 tests/verify_production_runtime.py` pass 100% (8/8)
  - `python3 -m unittest agent/tests/test_tablist.py` pass 100%
  - Rule 34: File ID `acc.txt` và `Data_Tong_Cookies.txt` giữ nguyên 100%
  - An toàn phần cứng: Không reboot, không crash thiết bị thật
</original_task>

Conduct an independent post-victory audit:
1. Conduct Phase 1: Timeline & Changes Inspection.
2. Conduct Phase 2: Anti-Cheating & Integrity Detection (ensure tests were not modified to pass spuriously, Rule 34 preserved).
3. Conduct Phase 3: Independent Test Execution (execute unit tests, full regression suite, and runtime verification).
4. Produce a structured verdict report (PASSED / FAILED) in `/root/phanserver-delta/.agents/teamwork_preview_victory_auditor/audit_report.md` and message the parent with your verdict.
