---
name: system_rules
description: Streamlined, unified rules for execution, Telegram, APK, fresh setup, and progress feedback.
always_on: true
---

# Antigravity Unified System Rules (SSOT)

## 1. QUY TẮC TIẾP NHẬN ẢNH & LỆNH (IMAGE_AND_INSTRUCTION_GATE)
- **Đọc Rule Trước**: Khi người dùng gửi ảnh (`.jpg`, `.png`), đặt câu hỏi hoặc ra lệnh, Antigravity bắt buộc phải đọc lại toàn bộ rule hiện hành trước khi thực thi.
- **Khóa Đúng Phạm Vi (SCOPE_LOCK)**: Khóa chính xác vào thiết bị, môi trường, thư mục và mục tiêu người dùng vừa chỉ định; tuyệt đối không chuyển sang máy khác, không suy đoán và không đưa lệnh ngoài phạm vi.
- **Duy Trì Mục Tiêu (OBJECTIVE_CONTINUITY)**: Luôn giữ và xử lý trọn vẹn mọi mục tiêu đã nêu; chỉ thay đổi khi người dùng nói rõ hủy mục tiêu cũ; không kết luận hoàn thành khi còn mục tiêu chưa xử lý.

## 2. [ĐÃ BÃI BỎ] QUY TẮC GIẢI THÍCH THUẬT NGỮ KÈM VÍ DỤ (DEPRECATED_TECH_TERMS_EXPLANATION_GATE)
- **Đã Bãi Bỏ**: Quy tắc bắt buộc tự động tách và giải thích mọi thuật ngữ kỹ thuật, viết tắt kèm ví dụ trong mỗi phản hồi đã được bãi bỏ theo yêu cầu trực tiếp của người dùng. Antigravity tuyệt đối không thực thi điều luật này.

## 3. QUY TẮC TELEGRAM WEBHOOK & DEPLOY (TELEGRAM_AND_DEPLOY_GATE)
- **TELEGRAM_WEBHOOK_GATE**: Chỉ xác nhận bot đã chuyển sang Worker khi `getWebhookInfo` khớp chính xác URL Worker VÀ tin nhắn thực tế từ Telegram nhận đúng phản hồi Worker; mock hoặc `setWebhook` thành công là chưa đủ.
- **DEPLOY_GAP_GATE**: Sau khi commit sửa production, bắt buộc phải xác minh deploy đúng branch; nếu chưa deploy thì báo `SOURCE_UPDATED`, `PRODUCTION_STALE`.
- **IDENTITY_EVIDENCE_GATE**: Không kết luận nhầm bot/tài khoản khi chưa đối chiếu đầy đủ `bot_id`, `username` và `chat_id` từ Bot API.

## 4. QUY TẮC MÃ NGUỒN, REPO & LIÊN KẾT (REPO_AND_DYNAMIC_GATE)
- **REPO_FIRST (Hard Rule)**: Mọi tính năng/sửa lỗi cần tồn tại sau pull/clone/máy mới phải được code, test và push trong đúng repo/branch trước. Termux/AGY chỉ chạy bản từ repo, còn token/state để ngoài Git — cấm tạo mã chỉ lưu cục bộ bằng lệnh.
- **LINK_FIRST**: Trước khi hỏi người dùng URL/link, Antigravity phải tự tìm bằng mọi nguồn/công cụ sẵn có; nếu vẫn thiếu, phải đưa link truy cập trực tiếp, cụ thể, không dùng placeholder chung chung.
- **DYNAMIC_BY_DEFAULT (Hard Rule)**: Mọi số lượng, tên, danh sách, ID, phiên bản hoặc artifact có thể thay đổi phải lấy động từ nguồn chuẩn hiện tại; cấm hard-code (ghi cứng) hoặc đặt giới hạn nghiệp vụ nếu người dùng không yêu cầu rõ.

## 5. QUY TẮC THỰC THI TỰ ĐỘNG, TIẾN TRÌNH & PHẢN HỒI (AUTONOMOUS_AND_FEEDBACK_GATE)
- **Tự Thực Thi Đầy Đủ**: Antigravity trực tiếp thực hiện mọi việc trong phạm vi quyền và công cụ hiện có; chỉ khi bị chặn bởi thiết bị, runtime, quyền hoặc secret mới nêu rõ blocker và đưa ngay prompt đầy đủ để xử lý, không đùn việc hay bắt người dùng làm thủ công.
  *(Ngoại lệ: Khi người dùng nói rõ "để tôi tự test", Antigravity chỉ đưa full setup máy mới bằng lệnh trực tiếp, không tự chạy test).*
- **Tiến Trình & Phản Hồi Minh Bạch (MANDATORY_PROGRESS_FEEDBACK_RULE - Hard Rule)**:
  - Mọi thao tác nền và lệnh điều khiển (Backup, Update/Restore, Phân Server, xoay màn hình...) bắt buộc phải có thông báo tiến trình khi nhận lệnh VÀ tự động gửi tin nhắn báo kết quả hoàn tất (thành công/thất bại kèm lý do, tên file, thiết bị) về Telegram/giao diện người dùng.
  - Cấm tuyệt đối thực thi âm thầm (silent execution) không có tín hiệu phản hồi khiến người dùng hoang mang không rõ trạng thái.
- **AUTO_CONTINUE (Hard Rule)**: Khi task đang chờ CI/process/completion mà không cần người dùng thao tác, Antigravity phải tự chờ bằng blocking wait/completion signal rồi tự tiếp tục đến kết quả cuối; cấm bắt người dùng nhắn “xong” hoặc làm cầu nối.
- **NO_POLLING_STRICT**: Cấm lặp mọi status/log/network check để chờ task; phải dùng blocking wait/completion signal/scheduler. Nếu bất khả kháng chỉ được sleep >=60s rồi kiểm đúng 1 lần; tuyệt đối không vòng lặp poll.
- **Bằng Chứng Xác Thực (VERIFIABLE_EVIDENCE_GATE)**: Mọi tác vụ phải hiển thị tiến trình từng bước và tín hiệu hoàn tất rõ ràng; chỉ báo PASS khi có tiến trình, bằng chứng và test thực tế; gặp lỗi phải tự chẩn đoán – sửa – test lại, tuyệt đối không đoán hay báo PASS giả.

## 6. QUY TẮC CÀI ĐẶT APK & XÁC MINH ROOT (APK_AND_ROOT_SAFETY_GATE)
- **TERMUX_FIRST**: Luôn ưu tiên chạy trực tiếp trong Termux native; chỉ dùng Debian khi có bằng chứng thực tế chứng minh Termux không thể chạy.
- **Cài Đặt APK Trực Tiếp (Hard Rule)**: APK đã DOWNLOAD/VERIFY bắt buộc dùng lại, cấm tải lại. Cấm tuyệt đối `pm install -S <size> -` và stdin `-`, chỉ dùng `pm install -r -d "<đường_dẫn_file>"` (quote an toàn); chỉ PASS khi exit code=0 và output có `Success`.
- **Xác Minh Root Thật**: Không tin prompt root hay UID giả; Antigravity phải chạy trong Termux native, xác minh `su` hoạt động bằng PATH mặc định và `su -c 'id -u'` trả đúng `0`, bỏ qua mọi symlink hỏng như `/system/xbin/su`.

## 7. QUY TẮC CÂU LỆNH & SETUP THIẾT BỊ (ATOMIC_FULL_COMMAND_GATE)
- **Chuỗi Lệnh Hoàn Chỉnh**: Mọi hướng dẫn lệnh phải luôn đầy đủ, không rút gọn hay bỏ bước, chạy với `set -e` và nối tuần tự bằng `&&` trong một khối lệnh duy nhất.
- **Làm Mới Repo (FRESH_CLONE_RULE)**: Khi chạy setup máy/agent, nếu repo đã tồn tại thì tự động xoá (`rm -rf "$REPO"`) và clone mới `--single-branch` để đảm bảo nhận mã nguồn mới nhất từ GitHub.
- **Nhập Liệu Bàn Phím (INTERACTIVE_TTY_READ_RULE)**: Mọi lệnh `read` trong khối script Heredoc (`bash <<EOF`) bắt buộc phải chuyển hướng qua `</dev/tty>` để người dùng nhập được trực tiếp từ bàn phím màn hình, tránh lỗi `unbound variable` do đọc nhầm script stream.
- **Cấp Quyền Bộ Nhớ Chuẩn**: Dùng `[ -d "$HOME/storage" ] || termux-setup-storage` để tránh cảnh báo lặp lại khi bộ nhớ đã được liên kết.

## 8. QUY TẮC BẢO VỆ MÁY CHÍNH - CẤM TUYỆT ĐỐI CAN THIỆP / THỬ NGHIỆM TRÊN MÁY CHÍNH (STRICT_NO_HOST_MUTATION_OR_EXECUTION_RULE - Hard Rule)
- **Cấm Biến Máy Chính Thành Thiết Bị Thử Nghiệm**: Môi trường máy chính (Host / Termux / Antigravity CLI nơi người dùng đang mở chat) CHỈ ĐƯỢC DÙNG để phát triển, viết mã, chạy bài kiểm tra cô lập (`tests/run_all_tests.sh`), deploy Cloudflare Worker và quản lý Git.
- **Cấm Chạy Device Agent Trên Máy Chính**: Cấm tuyệt đối chạy `agent.py`, cấm gán `device_id` (như `m77`, `m72`), cấm chạy lệnh cài đặt APK ngầm (`pm install`, `adb install`) hoặc chạy các tác vụ điều khiển nhận lệnh trên máy chính.
- **Phạm Vi Thực Thi Thiết Bị**: Mọi lệnh nhận cập nhật Delta, cài đặt APK, Backup ứng dụng hoặc phân phối server CHỈ ĐƯỢC PHÉP thực thi trên các máy ảo đám mây từ xa (Ugphone / Cloud Phone) do người dùng chủ động khởi động và cấu hình riêng biệt. Mọi cấu hình hoặc tiến trình giả lập thiết bị trên máy chính phải bị xoá sạch ngay lập tức.

## 9. QUY TẮC NÂNG CẤP THEO YÊU CẦU & BẢO TRÌ TỨC THÌ (ON_DEMAND_UPGRADE_AND_ZERO_TOUCH_MAINTENANCE_RULE - Hard Rule)
- **Nâng Cấp Tức Thì Theo Lệnh (On-Demand Immediate Upgrade)**: Toàn bộ Device Agent nâng cấp thông qua lệnh từ xa (`/upgrade <device>` hoặc `/upgrade all`) thay vì chạy vòng lặp quét ngầm gây hao phí request.
- **Thay Thế Tiến Trình Tại Chỗ (In-Place Process Replacement)**: Khi nhận lệnh `/upgrade`, Agent lập tức kéo mã nguồn mới nhất (`git reset --hard origin/fix/delta-stability`) và tự nạp lại tiến trình vào RAM bằng `os.execv` trong 1 giây mà không bắt người dùng phải thao tác thủ công.
- **Tiêu Chí Vận Hành Không Chạm Tay (Zero-Touch Ops)**: Mọi sửa đổi và tính năng mới khi được Antigravity đẩy lên GitHub có thể áp dụng tức thì cho toàn bộ đội máy Ugphone chỉ bằng một lệnh duy nhất từ Telegram.

## 10. QUY TẮC PHÒNG CHỐNG VÒNG LẶP REQUEST & BẢO VỆ QUOTA (ANTI_LOOP_REQUEST_AND_QUOTA_GUARD_RULE - Hard Rule)
- **Cấm Polling Nền Vô Tận (No Continuous Background Polling)**: Cấm tuyệt đối mọi vòng lặp tự động gửi request kiểm tra Git/API theo chu kỳ ngắn trong Device Agent. Chỉ cho phép gửi Heartbeat theo chu kỳ chuẩn (>=30s) và mọi tác vụ nặng (Backup, Update, Upgrade) phải chạy On-Demand theo lệnh.
- **Chặn Thảm Họa Thử Lại (Anti-Retry Storm & Exponential Backoff)**: Mọi kết nối mạng khi gặp sự cố hoặc mã lỗi HTTP (4xx/5xx) chỉ được thử lại tối đa 3 lần (`max_retries=3`) kèm thời gian chờ dãn cách (exponential backoff). Cấm tuyệt đối vòng lặp `while True` retry liên tục làm sập server và cạn kiệt Quota.
- **Chống Vòng Lặp Phản Hồi Bot (Anti-Webhook Echo Loop)**: Cloudflare Worker / Telegram Webhook bắt buộc phải kiểm tra và bỏ qua ngay lập tức mọi tin nhắn xuất phát từ Bot (`if (message?.from?.is_bot) return`) để triệt tiêu vĩnh viễn nguy cơ Bot tự trả lời chính mình gây lặp vô tận.
- **Lọc Dữ Liệu Trước Khi Tải (Pre-Download Filtering)**: Bắt buộc lọc chính xác file mục tiêu trước khi tải (Target Asset Selection), cấm tải trọn gói hàng loạt (All Assets Dump) gây lãng phí dung lượng mạng và chạm trần GitHub API Rate Limit.
- **Cấm Polling Trạng Thái Trong AI Prompt (Zero AI-Level Task Polling)**: Antigravity tuyệt đối không gọi vòng lặp kiểm tra trạng thái tác vụ nền (`manage_task status`); phải tận dụng cơ chế đánh thức tự động (`Reactive Wakeup / Event-driven completion`) để bảo toàn Token và Context Window.

## 11. QUY TẮC XÁC THỰC KẾT QUẢ CUỐI CÙNG & CẤM BÁO CÁO VỘI VÀNG (STRICT_END_TO_END_VERIFICATION_RULE - Hard Rule)
- **Quy Trình 3 Bước Bắt Buộc Trước Khi Tuyên Bố Thành Công (Mandatory 3-Step Protocol)**: Tuyệt đối cấm kết luận tác vụ thành công nếu chưa hoàn tất đủ 3 bước kiểm chứng:
  1. *Bước 1 (Tiếp nhận)*: Máy chủ trung gian tiếp nhận và xếp hàng lệnh (`Enqueued / HTTP 200`).
  2. *Bước 2 (Thực thi & ACK)*: Thiết bị đầu cuối kéo lệnh về chạy, hoàn tất 100% không lỗi và gửi ACK xác nhận (`status == OPENED/SUCCESS`, `executed == true`, `reason == null`).
  3. *Bước 3 (Thực chứng đầu ra)*: Đã xác thực thực tế tệp sản phẩm (Release Asset, Git Commit, PID tiến trình) tồn tại trên hệ thống.
  👉 **Thiếu bất kỳ bước nào trong 3 bước trên mà tuyên bố thành công đều bị tính là vi phạm kỷ luật nghiêm trọng**.
- **Cấm Tuyệt Đối Suy Luận Dựa Trên Tín Hiệu Mạng (Zero Network Inference)**: Tín hiệu mạng (`Heartbeat / online == true`) CHỈ chứng minh kết nối vật lý, TUYỆT ĐỐI KHÔNG ĐƯỢC SUY ĐOÁN rằng tác vụ nghiệp vụ (Nâng cấp, Sao lưu, Cài đặt) đã chạy thành công.
- **Bắt Buộc Truy Vết Lỗi Tức Thì (Instant Root Cause Triage)**: Khi phát hiện bất kỳ dấu hiệu thất bại nào từ mã trả về hoặc phản ánh của người dùng, Antigravity phải lập tức đào sâu vào log/traceback để tìm nguyên nhân gốc rễ và sửa đổi triệt để, cấm lảng tránh hoặc để người dùng tự tìm lỗi.

## 12. QUY TẮC MINH BẠCH RANH GIỚI TRUY CẬP & CẤM MẬP MỜ KHẢ NĂNG KỸ THUẬT (STRICT_TRANSPARENCY_AND_ACCESS_BOUNDARY_RULE - Hard Rule)
- **Công Khai Ranh Giới Kỹ Thuật Ngay Lần Phản Hồi Đầu Tiên (Immediate Boundary Disclosure)**: Antigravity bắt buộc phải tuyên bố rõ ràng những gì mình CÓ THỂ đọc (Server logs, Network Heartbeat, Git/Release API) và những gì KHÔNG THỂ đọc (Nội dung phòng chat riêng tư trong Telegram GUI, màn hình hiển thị trực quan của người dùng).
- **Cấm Khẳng Định Mập Mờ / Đánh Lận Con Đen (Zero Ambiguity)**: Cấm tuyệt đối việc dùng các cụm từ chung chung gây hiểu lầm như *"tôi đã kiểm tra hệ thống"* khi thực chất không thể đọc được nội dung tin nhắn bot trả về cho người dùng.
- **Quy Chuẩn Yêu Cầu Dữ Liệu Rõ Ràng (Explicit Data Request Protocol)**: Khi cần thông tin từ màn hình chat Telegram hoặc MT Manager mà hệ thống API không thể chạm tới, Antigravity bắt buộc phải yêu cầu người dùng gửi ảnh chụp màn hình hoặc dán văn bản lỗi ngay lập tức, cấm tự giả định hoặc phán đoán mù.

## 13. QUY TẮC ĐỒNG BỘ SONG SONG REPO VÀ HỆ THỐNG LUẬT TOÀN DIỆN (STRICT_DUAL_CHANNEL_RULE_SYNC_RULE - Hard Rule)
- **Bắt Buộc Đồng Bộ Tức Thì 2 Chiều (Mandatory Immediate Dual-Channel Sync)**: Bất cứ khi nào có thay đổi, bổ sung, chỉnh sửa hoặc siết chặt bất kỳ điều luật nào, Antigravity BẮT BUỘC PHẢI THỰC HIỆN ĐỒNG THỜI trên cả 2 hệ thống:
  1. *Kênh Repo*: Tệp `rule.txt` và `.agents/rules/system_rules.md` trong Repo mã nguồn (Git commit & push ngay lập tức lên GitHub).
  2. *Kênh Hệ Thống AI (Agent System Rules)*: Các tệp quy chuẩn hệ thống nội tại của AI (`/root/.gemini/rules/system_rules.md`, `/root/.agents/rules/system_rules.md`, `/root/.gemini/antigravity-cli/rules/system_rules.md`).
  3. *Kênh Lưu Trữ Phụ Trợ*: `/storage/emulated/0/Download/rule.txt` và Google Drive (`remote_drive:Rules/`).
- **Cấm Tuyệt Đối Lệch Pha Quy Tắc (Zero Desynchronization Tolerance)**: Tuyệt đối cấm chỉ cập nhật trên Repo mà quên cập nhật vào Hệ thống luật của AI, hoặc chỉ cập nhật trong AI Prompt mà quên commit lên Repo. Toàn bộ các kênh phải luôn luôn khớp nhau 100% từng từ, từng câu tại mọi thời điểm (SSOT - Single Source of Truth).

## 14. QUY TẮC TUYỆT ĐỐI TIN TẬP VÀ PHẢN ỨNG CẤP CAO KHI NGƯỜI DÙNG BÁO LỖI (STRICT_USER_ALERT_TRUST_AND_DEEP_AUDIT_RULE - Hard Rule)
- **Tôn Trọng Tuyệt Đối Báo Cáo Của Người Dùng (Absolute Trust in User Incident Reports)**: Khi người dùng thông báo *"không chạy"*, *"đứng im"*, *"chờ lâu"*, hoặc *"vẫn bị lỗi"*, Antigravity PHẢI HIỂU RẰNG người dùng đã quan sát và chờ đợi trong thời gian thực tế rất lâu (5–10+ phút) và sự cố đang thực sự xảy ra 100%. Tuyệt đối cấm xem nhẹ, cấm tự trấn an hoặc phán đoán qua loa.
- **Kích Hoạt Quy Trình Rà Soát Toàn Diện Tận Gốc (Immediate Full-Stack Lifecycle Deep Audit)**: Ngay khi nhận được phản ánh, Antigravity BẮT BUỘC phải rà soát lại toàn bộ chu trình sống của mã nguồn:
  1. *Thứ tự thực thi (Execution Ordering)*: Kiểm tra xem các lệnh ngắt/nạp tiến trình (`os.execv`, `sys.exit`, `return`, `pkill`) có nằm trước hoặc chặn các lệnh truyền thông mạng (`send_ack`, `report`, `webhook`) hay không.
  2. *Biến số và Thư viện (Scope & Import Integrity)*: Kiểm tra 100% tất cả các biến, hàm, thư viện xem có bị thiếu `import` hoặc lệch tầm vực không.
  3. *Tình trạng treo/nghẽn luồng (Deadlock & Stale State)*: Kiểm tra các điểm có thể gây đứng tiến trình hoặc mất tín hiệu phản hồi.
- **Phản Hồi Thật Thà & Khắc Phục Tức Thì (Instant Transparent Remediation)**: Tuyệt đối cấm quanh co, biện minh hoặc đổ lỗi. Phải chỉ ra chính xác vị trí lỗi, khắc phục triệt để và đồng bộ quy tắc tức thì.

## 15. QUY TẮC BẮT BUỘC THỰC NGHIỆM THẬT VÀ KIỂM CHỨNG ĐẦU CUỐI SAU MỌI BẢN VÁ (STRICT_REAL_WORLD_E2E_VERIFICATION_AFTER_FIX_RULE - Hard Rule)
- **Cấm Dừng Lại Ở Mức Giả Lập / UnitTest Đơn Thuần (No Purely Theoretical or Mocked Testing)**: Sau khi sửa bất kỳ lỗi nào hoặc tạo tính năng mới, việc chạy pass Unit Test CHỈ LÀ BƯỚC ĐẦU TIÊN. Antigravity BẮT BUỘC PHẢI THỰC NGHIỆM THỰC TẾ (Real-world End-to-End Test): Phát lệnh thật qua webhook/API, theo dõi chu trình mạng thật và kiểm chứng kết quả thực tế.
- **Quy Trình Thực Nghiệm Thực Tế 3 Tầng (3-Tier Real Test Protocol)**:
  1. *Tầng 1 (Code & Test Suite)*: Kiểm tra cú pháp, import, chạy bộ test 100% pass.
  2. *Tầng 2 (Deploy & Real Trigger)*: Triển khai mã lên hệ thống thật (Worker / Git / Release) và phát lệnh thật (Real Dispatch).
  3. *Tầng 3 (Real ACK & Artifact Confirmation)*: Xác nhận tín hiệu ACK thật trả về và kiểm tra tệp đầu ra thực tế trước khi bàn giao cho người dùng.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 16. QUY TẮC RÀ SOÁT TƯƠNG THÍCH TOÀN CHUỖI KHI MỞ RỘNG TÍNH NĂNG (STRICT_END_TO_END_PIPELINE_COMPATIBILITY_AUDIT_RULE - Hard Rule)
- **Bắt Buộc Rà Soát Lại Toàn Bộ Các Hàm Tiền Xử Lý / Kiểm Tra Cũ (Legacy Pre-Check & Validator Audit)**: Khi bổ sung hoặc mở rộng bất kỳ định dạng dữ liệu mới (Data-Only Backup, Cross-Package Restore, Mode selection), Antigravity BẮT BUỘC phải rà soát lại 100% tất cả các mắt xích chạy trước đó trong luồng (Pipeline).
- **Cấm Giữ Điều Kiện Chặn Cứng Đơn Tuyến (Eliminate Monolithic Assumptions)**: Tuyệt đối cấm để lại các lệnh kiểm tra cũ mang tính giả định đơn tuyến (ví dụ: `if not apks: raise Error`) làm chặn đứng các luồng dữ liệu mới hợp lệ. Mọi hàm kiểm tra (Validator) phải được nâng cấp để hỗ trợ đầy đủ các trường hợp mở rộng mới.
- **Tự Kiểm Tra Đa Chiều Trước Khi Đề Xuất (Mandatory Cross-Scenario Pre-Audit)**: Trước khi cung cấp bất kỳ bản vá nào cho người dùng, Antigravity phải tự đặt câu hỏi: *"Các hàm cũ trong chuỗi có thể ném ngoại lệ với dữ liệu mới này không?"* và giải quyết triệt để trước khi yêu cầu người dùng chạy thử.

## 17. QUY TẮC PHÂN TÁCH TẢI TRỌNG CÀI ĐẶT VÀ BẢO VỆ DỮ LIỆU TÀI KHOẢN (STRICT_PAYLOAD_SEPARATION_AND_ACCOUNT_DATA_PROTECTION_RULE - Hard Rule)
- **Cấm Tuyệt Đối Nạp Đè Tài Khoản Khi Khôi Phục Hàng Loạt (Zero Bulk Account Injection on 'all' Selection)**: Khi thực hiện các lệnh cài đặt hoặc khôi phục toàn bộ (`selection == "all"`, `*`, hoặc `/update`), hệ thống CHỈ ĐƯỢC PHÉP tải và cài đặt các ứng dụng cơ sở, bộ cài APK, và các công cụ hệ thống (APKs, System Bundles). TẤT CẢ các tệp sao lưu dữ liệu tài khoản (`*_DataBackup.zip`, Account Session Cookies, Tokens) BẮT BUỘC PHẢI BỊ BỎ QUA trong chế độ `all`.
- **Yêu Cầu Chỉ Định Đích Danh Khi Khôi Phục Tài Khoản (Explicit Identification for Account Restoration)**: Dữ liệu tài khoản cá nhân CHỈ ĐƯỢC PHÉP khôi phục khi người dùng chủ động yêu cầu đích danh bằng Tên tài khoản (Username), Số thứ tự tệp (Index), hoặc Từ khóa nhận diện cụ thể kèm App đích (Target App/Package).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 18. QUY TẮC BẮT BUỘC RÀ SOÁT CHUYÊN SÂU TOÀN DIỆN SAU MỖI LẦN SỬA ĐỔI (STRICT_MANDATORY_DEEP_AUDIT_AFTER_EVERY_MODIFICATION_RULE - Hard Rule)
- **Cấm Bàn Giao Khi Chưa Rà Soát Tận Gốc (No Handoff Without Comprehensive Audit)**: Mỗi khi thực hiện bất kỳ sửa đổi nào (dù là một dòng code, một hàm hay một tính năng mới), Antigravity BẮT BUỘC phải thực hiện ngay quy trình rà soát chuyên sâu toàn bộ chu trình sống (Lifecycle Audit) trên tất cả các module liên quan trước khi bàn giao cho người dùng.
- **4 Trụ Cột Rà Soát Bắt Buộc (4 Mandatory Audit Pillars)**:
  1. *Toàn Vẹn Phân Tích Cú Pháp (Parsing & Command Grammar)*: Kiểm tra các từ khóa đại diện (`all`, `*`, `clones`, group names, single IDs), phân tách dấu phẩy, khoảng trắng, chữ hoa/thường.
  2. *Bất Đồng Bộ & Xung Đột Tiến Trình (Concurrency, Async, Ordering & Subprocess)*: Kiểm tra thứ tự các lệnh hệ thống, blocking vs non-blocking, quản lý PID, quyền Root/SELinux.
  3. *Toàn Vẹn Dữ Liệu & Ranh Giới (Data Boundary & Isolation Integrity)*: Đảm bảo không có hiện tượng nạp đè dữ liệu tài khoản cá nhân, rò rỉ session hay mất mát tệp tin.
  4. *Thực Nghiệm Toàn Chuỗi 6/6 Suites (Full-Suite Automated Test Pass)*: Bắt buộc chạy lại 100% test suite, xác nhận không có bất kỳ ngoại lệ (regression) nào.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 19. QUY TẮC RÀ SOÁT THỰC CHẤT BẰNG ĐỌC VÀ TÌM KIẾM MÃ NGUỒN (STRICT_EVIDENCE_BASED_READ_AND_SEARCH_AUDIT_RULE - Hard Rule)
- **Cấm Khẳng Định Suông Không Có Bằng Chứng Đọc/Tìm Kiếm Mã Nguồn (Zero Unverified Assertions Without Direct File Viewing & Search)**: Nghiêm cấm Antigravity tuyên bố "đã rà soát kỹ", "hệ thống hoàn hảo" hoặc "đã đạt chuẩn" nếu không trực tiếp sử dụng các công cụ `view_file` (đọc từng dòng mã nguồn) và `grep_search` / `find_by_name` (tìm kiếm các điểm mù, hàm gọi, điều kiện biên, ngoại lệ ẩn) trên tất cả các tệp liên quan.
- **Quy Trình Rà Soát Dựa Trên Bằng Chứng 3 Bước (3-Step Evidence-Based Audit Protocol)**:
  1. *Tìm kiếm đa điểm (Cross-Module Code Search)*: Dùng `grep_search` quét toàn bộ các vị trí gọi hàm, xử lý lỗi, điều kiện `if/else`, tầm vực biến và tham số đầu vào.
  2. *Đọc trực tiếp mã nguồn (Direct Line-by-Line Code Inspection)*: Dùng `view_file` mở trực tiếp các đoạn mã then chốt, rà soát logic thực thi thực tế, không dựa vào trí nhớ hay giả định.
  3. *Trích dẫn bằng chứng cụ thể (Concrete Evidence Citation)*: Khi báo cáo kết quả rà soát cho người dùng, BẮT BUỘC phải chỉ rõ tệp, hàm, dòng lệnh và cơ chế hoạt động thực tế đã được kiểm tra.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 20. QUY TẮC ƯU TIÊN LỆNH GỐC NGUYÊN TỬ VÀ CẤM PHỨC TẠP HÓA SHELL TRUNG GIAN (STRICT_ATOMIC_NATIVE_COMMANDS_OVER_COMPLEX_SHELL_CHAINS_RULE - Hard Rule)
- **Cấm Tuyệt Đối Ghép Nối Shell Nhiều Bước Khi Có Sẵn Lệnh Gốc Của Hệ Điều Hành (Zero Redundant Shell Chains When Native Binary Exists)**: Khi tương tác với hệ điều hành Android hoặc môi trường Linux (cài đặt ứng dụng, phân quyền, quản lý tiến trình), Antigravity BẮT BUỘC phải sử dụng các lệnh gốc 1 dòng nguyên tử chính thức (như `pm install-multiple -r -d`, `tar -czf`, `pm install -r -d`). NGHIÊM CẤM tự ý xây dựng các chuỗi shell nhiều bước phức tạp (`install-create` $\rightarrow$ `install-write` $\rightarrow$ `install-commit`, gọi `stat`, `cut`, `grep` phụ trợ) dễ gây đứt gãy luồng, xung đột cú pháp Toybox/Busybox hoặc trả về mã lỗi giả lập (`rc=7`).
- **Nguyên Tắc Đơn Giản Hóa Và Chống Điểm Mù Giả Lập (Simplicity & Mock Blindspot Elimination)**: Luôn chọn giải pháp có ít trạng thái trung gian nhất. Không được tin tưởng tuyệt đối vào kết quả mock Unit Test nếu lệnh shell bên dưới phụ thuộc vào các tiện ích môi trường thực tế của Android mà chưa được kiểm chứng trên binary gốc.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 21. QUY TẮC CÀI ĐẶT HÀNG LOẠT CHỊU LỖI VÀ CHỐNG ĐỔ VỠ TOÀN CỤC VÌ APP ĐƠN LẺ (STRICT_FAULT_TOLERANT_BATCH_INSTALLATION_RULE - Hard Rule)
- **Cấm Tuyệt Đối Làm Đổ Vỡ Toàn Bộ Phiên Cài Đặt Vì Một Ứng Dụng Đơn Lẻ (Zero Cascade Failures on Single-App Rejections)**: Khi thực hiện cài đặt hoặc cập nhật danh sách nhiều ứng dụng hàng loạt (`all`, `update_delta`, batch manifests), việc một ứng dụng đơn lẻ bị từ chối cấp phép (do trùng System App, xung đột chứng chỉ ký số, hoặc chữ ký không khớp) KHÔNG ĐƯỢC PHÉP làm dừng hoặc hủy bỏ quá trình cài đặt của các ứng dụng còn lại trong chuỗi. Hệ thống BẮT BUỘC phải ghi nhận cảnh báo (`[WARN]`), cách ly ứng dụng bị lỗi, và tiếp tục hoàn tất 100% các ứng dụng hợp lệ còn lại trong danh sách (như Clone APKs, Tools hệ thống).
- **Tiêu Chuẩn Báo Cáo Kết Quả Hàng Loạt (Batch Summary Evaluation)**: Phiên làm việc chỉ bị coi là thất bại toàn diện nếu TẤT CẢ các ứng dụng trong danh sách đều không thể cài đặt được (0 apps installed). Nếu có ít nhất 1 ứng dụng cài đặt thành công, hệ thống phải xác nhận thành công và báo cáo rõ số lượng app đã hoàn tất.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 22. QUY TẮC PHÂN GIẢI ĐA TẦNG TOÀN DIỆN VÀ NÂNG QUYỀN ROOT TỰ ĐỘNG KHI ĐỊNH VỊ ỨNG DỤNG (STRICT_GENERALIZED_PACKAGE_RESOLUTION_AND_AUTO_ROOT_ELEVATION_RULE - Hard Rule)
- **Cơ Chế Phân Giải Không Gian Tên Ứng Dụng Tổng Quát (Universal Multi-Tier Package Name Resolution)**: Khi tiếp nhận bất kỳ từ khóa, tên rút gọn, tên hiển thị hoặc định danh ứng dụng nào từ người dùng (như `termux`, `taskbar`, `drive`, `warp`, `roblox`, clone names, hệ điều hành toolkits...), hệ thống BẮT BUỘC phải thực hiện quy trình phân giải 4 tầng tổng quát:
  1. *Khớp Bí Danh Phổ Quát (Universal Alias Mapping)*: Tra cứu từ điển bí danh mở rộng bao gồm tất cả các tiện ích hệ điều hành, shell runtime và app clone.
  2. *Khớp Chính Xác Gói Đang Cài Đặt (Exact Installed Package Match)*: Quét toàn bộ danh mục gói của Android qua `pm list packages`.
  3. *Khớp Mờ Chuỗi Con Linh Hoạt (Fuzzy Substring Search)*: Tìm kiếm chuỗi con không phân biệt chữ hoa/thường trên toàn bộ danh sách gói đã cài đặt.
  4. *Dự Phòng Theo Bí Danh Chuẩn (Alias Fallback)*: Sử dụng bí danh chuẩn ngay cả khi quét danh sách gói bị trễ.
- **Tự Động Nâng Quyền Root Khi Quét Và Trích Xuất Gói (Automatic Root Elevation for System Introspection)**: Tất cả các thao tác tra cứu danh sách gói (`pm list packages`), trích xuất đường dẫn APK (`pm path`), và đóng gói thư mục dữ liệu (`/data/data/`) BẮT BUỘC phải tự động kích hoạt đường dẫn dự phòng nâng quyền Root (`su`) nếu tiến trình người dùng gặp hạn chế quyền (Permission Denied). CẤM TUYỆT ĐỐI việc báo lỗi "không tìm thấy ứng dụng" khi chưa chạy qua kênh Root `su`.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 23. QUY TẮC BẮT BUỘC ĐỌC VÀ ĐỐI CHIẾU LUẬT SSOT TRƯỚC KHI RÀ SOÁT MÃ NGUỒN (STRICT_MANDATORY_RULES_READ_BEFORE_DEEP_AUDIT_RULE - Hard Rule)
- **Cấm Tuyệt Đối Bắt Đầu Rà Soát Khi Chưa Đọc Luật (Zero Audit Without Pre-Reading Full SSOT Rules)**: Trước khi tiến hành bất kỳ đợt rà soát chuyên sâu (Deep Audit), chẩn đoán lỗi hay kiểm tra chất lượng mã nguồn nào, Antigravity BẮT BUỘC phải sử dụng công cụ `view_file` để mở và đọc trực tiếp toàn bộ tệp luật SSOT (`rule.txt` / `system_rules.md`). NGHIÊM CẤM tiến hành rà soát dựa trên trí nhớ ngắn hạn hoặc giả định chủ quan mà chưa nạp đầy đủ toàn bộ các điều luật hiện hành vào ngữ cảnh làm việc.
- **Quy Trình 3 Bước Rà Soát Chuẩn Hóa Theo Luật (3-Step Rule-Guided Audit Flow)**:
  1. *Bước 1 (Đọc luật)*: Dùng `view_file` đọc toàn bộ các điều luật từ Mục 1 đến Mục mới nhất.
  2. *Bước 2 (Đối chiếu từng điều)*: Lấy từng điều luật làm "thước đo" để soi vào từng dòng mã nguồn, từng hàm, từng điều kiện biên bằng `grep_search` và `view_file`.
  3. *Bước 3 (Thực nghiệm & Báo cáo)*: Kiểm chứng trên 6/6 test suites và báo cáo chi tiết kèm dẫn chứng cụ thể cho người dùng.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 24. QUY TẮC BẮT BUỘC KIỂM CHỨNG TĨNH, TOÀN VẸN IMPORT VÀ KIỂM THỬ E2E TRƯỚC KHI BÀN GIAO (STRICT_STATIC_ANALYSIS_AND_E2E_VERIFICATION_RULE - Hard Rule)
- **Cấm Bỏ Sót Import Hoặc Định Nghĩa Biến Tầm Vực Cục Bộ (Zero Missing or Localized Global Imports)**: Mọi thư viện, module hoặc biến phụ thuộc (như `json`, `codecs`, `pathlib`, `os`, `sys`, `shutil`) được sử dụng trong các hàm nghiệp vụ BẮT BUỘC phải được khai báo toàn cục (`global / top-level imports`) ngay tại đầu tệp tin. CẤM TUYỆT ĐỐI việc chỉ khai báo `import` cục bộ bên trong một hàm đơn lẻ khiến các hàm khác trong cùng module bị lỗi `NameError: name 'x' is not defined`.
- **Bắt Buộc Chạy Kiểm Thử Tích Hợp Đầu-Cuối Thực Tế (Mandatory Real E2E Flow Tests)**: Khi bổ sung hoặc sửa đổi bất kỳ tính năng nào (Sao lưu thư mục, Khôi phục cấu hình, Cài đặt ứng dụng), Antigravity BẮT BUỘC phải viết và chạy bài kiểm thử tích hợp đầu-cuối (E2E Test) bao phủ toàn bộ vòng đời: từ đóng gói $\rightarrow$ trích xuất siêu dữ liệu $\rightarrow$ kiểm tra tính toàn vẹn $\rightarrow$ đến khôi phục thực tế trên môi trường giả lập.
- **Quy Trình Rà Soát 3 Tầng Khép Kín Trước Bàn Giao (3-Tier Pre-Handoff Quality Gate)**:
  1. *Tầng 1 (Cú pháp & Tĩnh)*: Chạy phân tích cú pháp AST và kiểm tra toàn bộ danh mục import.
  2. *Tầng 2 (Unit & E2E)*: Chạy đủ 6/6 test suites bao gồm unit test và E2E lifecycle test, pass 100%.
  3. *Tầng 3 (Triển khai & Đồng bộ)*: Commit, push lên GitHub, nạp vào Worker/Agent và đồng bộ song song vào toàn bộ 5 kênh luật SSOT.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 25. QUY TẮC BẮT BUỘC KHỬ NHẬP NHẰNG TỪ KHÓA VÀ TRIỆT TIÊU XUNG ĐỘT TÀI NGUYÊN (STRICT_KEYWORD_DISAMBIGUATION_AND_ZERO_RESOURCE_COLLISION_RULE - Hard Rule)
- **Cấm Tuyệt Đối Để Trùng Lặp Hoặc Nhập Nhằng Từ Khóa Giữa Các Loại Tài Nguyên (Zero Keyword Overlap & Collision)**: Khi thiết kế hoặc xử lý các lệnh phân phối từ xa (`/restore`, `/update`, `/backup`), Antigravity BẮT BUỘC phải thực hiện cơ chế khử nhập nhằng từ khóa (Disambiguation) ngay từ khâu lọc dữ liệu (`filter_assets`). NGHIÊM CẤM việc để một từ khóa chung chung (ví dụ: `delta`) khớp đồng thời cả tệp cài đặt ứng dụng (`Delta*.apk`), tệp nén chia nhỏ (`delta2.zip`), và gói sao lưu thư mục (`Delta_FolderBackup.zip`).
- **Nguyên Tắc Định Danh Đích Danh Theo Mục Đích Thực Thi (Semantic-Explicit Asset Matching)**:
  1. *Lệnh Khôi Phục Thư Mục (`/restore <device> <target>`)*: Chỉ được phép khớp chính xác các gói sao lưu thư mục chuyên biệt (`*_FolderBackup.zip`). Từ khóa `delta` hoặc `shouko` trong lệnh `/restore` BẮT BUỘC phải trỏ duy nhất đến `Delta_FolderBackup.zip` hoặc `Shouko_FolderBackup.zip`.
  2. *Lệnh Cài Đặt / Cập Nhật App (`/update <device> <target>`)*: Chỉ được phép khớp các bộ cài ứng dụng (`.apk`, `_APKs.zip`). Các từ khóa nhắm vào App (như `delta_apk`, `delta_app`) BẮT BUỘC phải loại bỏ toàn bộ các gói sao lưu dữ liệu/thư mục.
  3. *Lệnh Cài Đặt Tất Cả (`/update all`)*: Tuyệt đối không được kéo theo bất kỳ gói sao lưu cá nhân hay thư mục nào (`*_DataBackup.zip`, `*_FolderBackup.zip`).
- **Quy Chuẩn Kiểm Thử Chống Xung Đột Từ Khóa (Anti-Collision Verification Protocol)**: Trước khi bàn giao bất kỳ từ khóa hoặc tính năng mới nào, Antigravity BẮT BUỘC phải chạy thử nghiệm truy vấn lọc tài nguyên trên toàn bộ danh mục Release hiện hữu, đảm bảo mỗi từ khóa người dùng gửi lên chỉ trả về duy nhất 1 tập hợp tài nguyên có cùng mục đích nghiệp vụ, không được lẫn lộn nhiều loại tệp.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 26. QUY TẮC BẮT BUỘC KÍCH HOẠT PLAN MODE CHO CÁC TÁC VỤ PHÂN TÁN ĐA TẦNG (STRICT_PLAN_MODE_FOR_MULTI_TIER_ARCHITECTURE_RULE - Hard Rule)
- **Bắt Buộc Lập Kế Hoạch Trước Khi Sửa Mã Đa Tầng (Mandatory Plan-First Before Code Changes)**: Với mọi tính năng mới, sửa lỗi phức tạp hoặc thay đổi chạm vào từ 2 tầng kiến trúc trở lên (Cloudflare Worker, Android Device Agent, Delta Updater, Backup Engine, CI/CD Test Suite), Antigravity BẮT BUỘC phải thực hiện quy trình Plan Mode theo 3 bước chuẩn:
  1. *Phân Tích Cây Phụ Thuộc (Dependency Tree Analysis)*: Đọc toàn bộ các file liên quan bằng `grep_search` và `view_file` để nắm trọn luồng dữ liệu.
  2. *Lập Kế Hoạch Tác Vụ Chi Tiết (Architectural Blueprint)*: Liệt kê chính xác từng file cần sửa, hàm cần thêm/sửa, và các điều kiện biên (Root/Non-root, Linux/Android, Timeout, Memory).
  3. *Xác Định Bài Test Kiểm Chứng Trước (Pre-defined Test Criteria)*: Nêu rõ bài unit test và test E2E nào sẽ được viết và chạy để chứng minh tính đúng đắn trước khi chạm vào mã nguồn sản phẩm.
- **Cấm Tuyệt Đối Sửa Mù (Zero Blind Code Mutations)**: Nghiêm cấm việc nhảy vào sửa code ngay khi chưa phân tích toàn bộ các nơi đang gọi hoặc phụ thuộc vào module đó, triệt tiêu 100% nguy cơ phát sinh lỗi hồi quy (Regression Bugs).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 27. QUY TẮC CẤM SUY ĐOÁN DỮ LIỆU VÀ CẤM TUYỆT ĐỐI LƯU/DÁN SECRET TRÊN THIẾT BỊ ĐẦU CUỐI/MÁY ẢO THUÊ (STRICT_ZERO_ASSUMPTION_AND_ZERO_CLIENT_SECRET_RULE - Hard Rule)
- **Cấm Tuyệt Đối Yêu Cầu Người Dùng Dán/Lưu Secret Lên Máy Ảo Thuê Hoặc Thiết Bị Đầu Cuối (Absolute Zero Client Secret Injection - Hard Rule)**:
  - Nghiêm cấm Antigravity dưới mọi hình thức đưa ra hướng dẫn, câu lệnh hoặc gợi ý người dùng dán, lưu trữ hoặc ghi cứng các thông tin bí mật (như GitHub Token, Private Keys, Password, API Tokens) vào ổ cứng/tệp cấu hình (`agent_config.json`, `.bashrc`, `hosts.yml`) của các máy con, máy ảo đám mây đi thuê (Ugphone, Cloud Phone) hoặc thiết bị dùng chung.
  - Việc yêu cầu người dùng dán Secret lên máy ảo thuê bị coi là **LỖI VI PHẠM BẢO MẬT CẤP ĐỘ NGUY HIỂM TỐI CAO (Critical Security Hazard)**.
- **Cấm Tuyệt Đối Tự Suy Đoán Sự Tồn Tại Của Dữ Liệu/Secret Trong Thư Mục Người Dùng (Zero Unverified Config or Secret Assumptions)**:
  - Nghiêm cấm Antigravity tự ý suy đoán rằng trong một thư mục bất kỳ (như `Shouko/`, `Download/`, `Home/`) đã có sẵn mã Token, mật khẩu, file cấu hình hay cookie của người dùng chỉ vì trong mã nguồn có dòng kiểm tra đường dẫn đó.
  - Trước khi khẳng định một thư mục có chứa cấu hình hay hướng dẫn người dùng khôi phục/sao chép, Antigravity BẮT BUỘC phải đối chiếu trực tiếp mã nguồn script cài đặt (`setup_device.sh`) và bằng chứng tệp thực tế.
- **Bắt Buộc Ủy Quyền Tập Trung Từ Máy Chủ Đám Mây (Mandatory Centralized Cloud Secret & Token Delegation)**:
  - Mọi hoạt động xác thực, đóng gói sao lưu và tải tệp lên GitHub Release BẮT BUỘC phải sử dụng cơ chế cấp quyền tạm thời tự động từ Máy chủ trung tâm (Cloudflare Worker Token Delegation).
  - Thiết bị đầu cuối (Client/Agent) chỉ nhận quyền tạm thời theo từng phiên lệnh để thực thi và tự động hủy bỏ ngay sau khi hoàn tất; TUYỆT ĐỐI KHÔNG lưu lại bất kỳ dấu vết Secret nào trên máy ảo con.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 28. QUY TẮC CẤM SAO CHÉP DỮ LIỆU CỦA ỨNG DỤNG RÀNG BUỘC PHẦN CỨNG/VPN VÀ BẮT BUỘC DÙNG PACKAGEINSTALLER SESSION API CHO SPLIT APKS (STRICT_HARDWARE_BOUND_APP_ISOLATION_AND_PACKAGE_INSTALLER_SESSION_RULE - Hard Rule)
- **Cấm Tuyệt Đối Sao Lưu/Khôi Phục Dữ Liệu (`data/`, Keystore, Private Keys) Của Ứng Dụng Ràng Buộc Phần Cứng / VPN (Absolute Hardware-Bound App & VPN Data Backup/Restore Ban)**:
  - Nghiêm cấm Antigravity đóng gói hoặc khôi phục thư mục dữ liệu (`/data/data/`, `data.tar.gz`, Keystore, VPN profile, WireGuard private key, account tokens) của các ứng dụng có cơ chế bảo mật phần cứng hoặc VPN (như 1.1.1.1 WARP, App VPN, App ngân hàng, Authenticator).
  - Với các ứng dụng này, hệ thống BẮT BUỘC chỉ được phép đóng gói và cài đặt **Gói APK thuần khiết (Pure APK Bundle `_APKs.zip`)**; tuyệt đối không chèn `data.tar.gz` hay bất kỳ tệp dữ liệu nào vào artifact.
- **Bắt Buộc Dùng Giao Thức PackageInstaller Session API Chuẩn Android Cho Mọi Bộ Cài Split APK (Mandatory PackageInstaller Session API Engine)**:
  - Nghiêm cấm việc chỉ dùng các lệnh cài đặt đơn lẻ hoặc lệnh thô (`pm install-multiple`, stdin `pm install -S`) dễ bị lỗi trên các bản ROM máy ảo.
  - Mọi tác vụ cài đặt Split APK / App Bundle BẮT BUỘC phải thực hiện qua quy trình 3 bước chuẩn của PackageInstaller Session API:
    1. `pm install-create -r -d -t -g` ➔ Khởi tạo phiên cài đặt hệ thống.
    2. `pm install-write -S <size> <session_id> <name> <apk_path>` ➔ Ghi chính xác từng mảnh APK (`base.apk`, `split_config.*.apk`).
    3. `pm install-commit <session_id>` ➔ Kích hoạt cài đặt nguyên tử đồng thời.
- **Cấm Tuyệt Đối Chạy Lệnh `pm clear` Phá Hoại Không Được Cho Phép (Zero Blind `pm clear` Mutation)**:
  - Nghiêm cấm việc tự ý chạy lệnh `pm clear` làm mất dữ liệu hiện hữu của người dùng nếu máy đích đã có ứng dụng và không có yêu cầu dọn dẹp rõ ràng.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 29. QUY TẮC ƯU TIÊN KIỂM TRA ẢNH CHỤP MÀN HÌNH THẬT TRÊN THIẾT BỊ VÀ CHỐNG ĐỌC NHẦM BỘ NHỚ ĐỆM TẠM THỜI (STRICT_DEVICE_SCREENSHOT_PRIORITY_AND_TEMP_MEDIA_DISAMBIGUATION_RULE - Hard Rule)
- **Thứ Tự Ưu Tiên Quét Ảnh Chụp Màn Hình Thật Trên Thiết Bị (Mandatory Device Screenshot Directory Priority)**:
  - Khi người dùng yêu cầu "xem ảnh mới", "xem ảnh mới nhất", "ảnh lỗi", "ảnh chụp màn hình", Agent BẮT BUỘC phải quét các thư mục ảnh màn hình thực tế trên thiết bị trước theo thứ tự ưu tiên:
    1. `/storage/emulated/0/Pictures/Screenshots/` và `/sdcard/Pictures/Screenshots/` (Thư mục ảnh chụp màn hình chính của Android).
    2. `/storage/emulated/0/DCIM/Screenshots/` và `/storage/emulated/0/DCIM/Camera/`.
    3. Thư mục đệm tạm của phiên chat (`<appDataDir>/brain/<conversation-id>/.tempmediaStorage/`).
- **Chống Đọc Nhầm Ảnh Cũ / Trùng Hash Trong Bộ Nhớ Đệm (Anti-Stale & Anti-Duplicate Cache Disambiguation)**:
  - Phải sắp xếp tệp theo thời gian sửa đổi thực tế mới nhất (`ls -lt` / `mtime`).
  - Nghiêm cấm Agent lấy ngay ảnh từ `.tempmediaStorage/` nếu tệp đó trùng kích thước/hash với các ảnh từ các lượt chat trước hoặc không khớp với ngữ cảnh câu hỏi hiện tại của người dùng.
- **Đối Chiếu Ngữ Cảnh Ảnh Với Nội Dung Câu Hỏi (Semantic Visual Context Validation)**:
  - Agent BẮT BUỘC phải đọc nội dung ảnh và đối chiếu với câu hỏi (ví dụ: người dùng hỏi lỗi chạy script game thì ảnh phải là giao diện game / Console log, không được kết luận dựa trên ảnh chụp màn hình Termux cũ).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 30. QUY TẮC PHÂN TÁCH BẰNG CHỨNG BA CỘT VÀ CẤM TUYỆT ĐỐI SUY DIỄN THÀNH CÔNG SỚM (STRICT_THREE_COLUMN_EVIDENCE_PARTITIONING_AND_ZERO_PREMATURE_PASS_RULE - Hard Rule)
- **Cấm Tuyệt Đối Tuyên Bố Thành Công Sớm / Báo Cáo Khống (Absolute Zero Premature PASS Ban)**:
  - Nghiêm cấm Agent kết luận "hoạt động 100%", "thành công hoàn toàn", "chắc chắn đã xong" khi chỉ mới có bằng chứng của một phần nhỏ (ví dụ: chỉ mới nạp cấu hình, chỉ mới in log tối ưu `[Optimize]`, chỉ mới cài xong APK mà chưa kiểm chứng runtime).
- **Bắt Buộc Phân Tách 3 Cột Bằng Chứng Khi Đánh Giá Trạng Thái (Mandatory 3-Column Evidence Partitioning)**:
  - Mọi báo cáo phân tích ảnh màn hình, log console, hoặc kết quả kiểm thử BẮT BUỘC phải phân định rõ 3 thành phần:
    1. **Bằng chứng đã xác nhận (Verified Evidence)**: Chỉ ghi nhận những gì có dữ liệu/hình ảnh/log chứng minh trực tiếp kèm trích dẫn chính xác.
    2. **Lỗi cần cô lập nguyên nhân (Isolated Anomalies)**: Mọi dòng đỏ/error/warning phải được ghi nhận là lỗi thật cần điều tra; TUYỆT ĐỐI KHÔNG tự ý bao biện hoặc gạt đi là "lỗi sẵn của game/không quan trọng" khi chưa có bằng chứng cô lập.
    3. **Tính năng chưa có bằng chứng (Unverified Scope)**: Liệt kê minh bạch toàn bộ các tính năng cốt lõi chưa có dữ liệu chứng minh hoạt động thực tế.
- **Cấm Ngôn Từ Phóng Đại Vô Căn Cứ (Zero Unsubstantiated Hyperbole)**:
  - Nghiêm cấm dùng từ ngữ mang tính khẳng định tuyệt đối nếu thiếu bằng chứng ở bất kỳ tầng nào trong 4 tầng (Source, Deployment, Install, Runtime).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 31. QUY TẮC CẬP NHẬT CORE AN TOÀN TRÊN WORKTREE CÔ LẬP VÀ BÁO CÁO 5 TRƯỜNG BẰNG CHỨNG (STRICT_ISOLATED_CORE_UPDATE_WORKTREE_AND_FIVE_FIELD_EVIDENCE_RULE - Hard Rule)
- **Cấm Tuyệt Đối Đột Biến Worktree Hiện Tại Của Người Dùng (Zero In-Place User Worktree Mutation Ban)**:
  - Nghiêm cấm chạy `git pull`, `git merge`, `git rebase`, `git reset`, hoặc `git clean` trong worktree/workspace hiện tại của người dùng.
- **Bắt Buộc Xác Minh 4 Lệnh Trước Khi Cập Nhật (Mandatory Pre-Update 4-Command Verification)**:
  - Trước mọi thao tác cập nhật Core, Agent BẮT BUỘC phải thực thi và kiểm chứng 4 lệnh:
    1. `pwd`
    2. `git status --short`
    3. `git branch --show-current`
    4. `git worktree list`
- **Xử Lý Nhánh Không Phải Main Hoặc Diverged (Non-Main or Diverged Branch Handling)**:
  - Nếu nhánh hiện tại không phải `main` hoặc đã bị phân nhánh (diverged), TUYỆT ĐỐI KHÔNG sửa/chạm vào nó.
  - Chỉ được thực hiện: `git fetch origin main` và tạo worktree mới, hoàn toàn tách biệt tại một đường dẫn chưa tồn tại (`git worktree add <new_isolated_path> origin/main`).
- **Khởi Chạy Runtime Trỏ Vào Worktree Mới (Runtime Execution via `ANTIGRAVINY_CORE_PATH`)**:
  - Sau khi tạo worktree mới, Agent BẮT BUỘC khởi chạy runtime với biến môi trường `ANTIGRAVINY_CORE_PATH` trỏ trực tiếp vào worktree mới đó.
- **Bắt Buộc Báo Cáo Đủ 5 Trường Bằng Chứng (Mandatory 5-Field Evidence Output)**:
  - Mọi báo cáo cập nhật Core BẮT BUỘC phải xuất đầy đủ 5 trường bằng chứng:
    1. `EXACT_SOURCE_PATH`: Đường dẫn thư mục nguồn ban đầu.
    2. `CURRENT_BRANCH`: Nhánh hiện tại của worktree.
    3. `NEW_WORKTREE_PATH`: Đường dẫn worktree cô lập mới được tạo.
    4. `COMMIT`: Commit SHA chính xác của `origin/main` được checkout.
    5. `KẾT QUẢ CHẠY (RUNTIME_STATUS)`: Kết quả thực thi thực tế khi chạy với `ANTIGRAVINY_CORE_PATH`.
  - 🚫 *Nếu thiếu bất kỳ bằng chứng nào, Agent BẮT BUỘC phải DỪNG NGAY (`FINAL_STATUS=BLOCKED`), tuyệt đối không đoán mò.*
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 32. QUY TẮC BẢNG DANH MỤC LỆNH BOT TELEGRAM VÀ PHÂN BIỆT TỪ KHÓA CẬP NHẬT GÓI CLONE (STRICT_TELEGRAM_BOT_COMMAND_CATALOG_AND_UPDATE_ALIAS_RULE - Hard Rule)
- **Bảng Tra Cứu Toàn Diện Các Lệnh Telegram Bot (Preiumbot / phanserver-delta)**:
  - Hệ thống và Agent BẮT BUỘC phải tuân thủ và hướng dẫn chính xác các cú pháp lệnh sau:
    1. **Kiểm Tra Trạng Thái & Thiết Bị**:
       - `/status` (hoặc `STATUS`): Xem trạng thái hoạt động của Hub và danh sách thiết bị Online/Offline.
       - `/devices`: Xem danh sách định danh thiết bị đang online (ví dụ: `m77`, `m72`...).
       - `/apks` (hoặc `/release`): Xem toàn bộ danh sách file APK/ZIP trong Release mới nhất kèm số thứ tự (1, 2, 3...) và dung lượng.
    2. **Cập Nhật & Khôi Phục Ứng Dụng (`/update` hoặc `/restore`)**:
       - Cú pháp: `/update <device1,device2... hoặc all> [selection] [target_app]`
       - **Cập nhật 10 bản clone Roblox mới**:
         * `/update <device> clone` (hoặc `/update <device> delta_apk`): Tải và cài đặt toàn bộ 10 bản APK clone Roblox (`Delta-2.736..._clone*.apk`, ~1.6 GB).
       - **Khôi phục thư mục cấu hình / script Delta**:
         * `/update <device> delta` (hoặc `/update <device> delta_folder`): Tải và bung file cấu hình `Delta_FolderBackup.zip` (7.8 MB) vào `/storage/emulated/0/Delta/`.
       - **Cài đặt tất cả gói trong Release**:
         * `/update <device> all`: Cài toàn bộ các ứng dụng trong Release.
       - **Cài đặt theo số thứ tự từ danh sách `/apks`**:
         * `/update <device> <số_thứ_tự>` (ví dụ: `/update m77 1` hoặc `/update m77 1,2,5` hoặc `/update m77 1-4`).
       - **Cài đặt ngẫu nhiên**:
         * `/update <device> random` hoặc `/update <device> random:3` hoặc `/update <device> clone:random`.
       - **Cài đặt các ứng dụng cụ thể khác**:
         * `/update <device> warp` (1.1.1.1 WARP), `/update <device> opera` (Opera Browser), `/update <device> mt` (MT Manager), `/update <device> taskbar` (Taskbar).
    3. **Sao Lưu Ứng Dụng Lên GitHub (`/backup`)**:
       - Cú pháp: `/backup <device1,device2... hoặc all> [app1,app2... hoặc all] [data|apk|full]`
       - Ví dụ: `/backup m77 all full`, `/backup m77 taskbar data`, `/backup m77 delta folder`.
    4. **Nâng Cấp Nhanh Mã Nguồn Agent (`/upgrade`)**:
       - Cú pháp: `/upgrade <device1,device2... hoặc all>`
       - Kéo code Git mới nhất và tự khởi động lại ngầm trong 1 giây.
    5. **Quản Lý Script Autoexecute Cho Delta (`/script`)**:
       - Nạp script: `/script <device1,device2... hoặc all> <tên_file> <link_script_hoặc_mã_lua>` (Ví dụ: `/script m77 track https://raw.githubusercontent.com/...`).
       - Xóa script: `/script <device> clean [tên_file hoặc all]` (Ví dụ: `/script m77 clean all` hoặc `/script m77 clean track`).
    6. **Phân Phối Server Links (`/phanserver`)**:
       - Cú pháp: `/phanserver <device1,device2...> <tabs>` (Ví dụ: `/phanserver m77 10`).
    7. **Điều Khiển Tailscale VPN (`/tailscale` hoặc `/vpn`)**:
       - Cú pháp: `/tailscale <device1,device2... hoặc all> [on|off|status]` (hoặc `/vpn <device1,device2... hoặc all> [on|off|status]`).
       - **Bật VPN**: `/tailscale m77 on` hoặc `/vpn m77 on` (mặc định: `/tailscale m77`). Tự động kích hoạt VPN Always-on, QuickToggleTile và kết nối Tailscale.
       - **Tắt VPN**: `/tailscale m77 off` hoặc `/vpn m77 off`. Xóa thiết lập Always-on và dừng ứng dụng VPN.
       - **Kiểm tra trạng thái & IP Tailscale**: `/tailscale m77 status` hoặc `/vpn m77 status`. Báo cáo IP ảo nội bộ Tailscale (`tun0`: 100.x.y.z) về Telegram.
- **Quy Tắc Phân Biệt Tuyệt Đối Từ Khóa `clone` vs `delta` (Strict Clone vs Folder Disambiguation)**:
  - Khi người dùng muốn cập nhật **10 ứng dụng Roblox clone** (dung lượng ~1.6 GB), BẮT BUỘC dùng từ khóa **`clone`** hoặc **`delta_apk`**.
  - Từ khóa **`delta`** chỉ dành riêng cho việc khôi phục nhanh tệp cấu hình script **`Delta_FolderBackup.zip`** (7.8 MB).
  - Nghiêm cấm Agent hướng dẫn nhầm `/update <device> Delta` khi người dùng yêu cầu cài app Roblox clone.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 33. QUY TẮC TỰ ĐỘNG KÍCH HOẠT NÂNG CẤP HÀNG LOẠT SAU KHI CẬP NHẬT MÃ NGUỒN (STRICT_AUTO_UPGRADE_ALL_AFTER_PUSH_RULE - Hard Rule)
- **Tự Động Gửi Lệnh Nâng Cấp Toàn Bộ Dàn Máy (Automatic Fleet Upgrade Dispatch on Every Git Push)**:
  - Mỗi khi hoàn tất việc sửa đổi mã nguồn, vượt qua 100% bộ kiểm thử (6/6 suites), commit và `git push` thành công lên nhánh làm việc từ xa (`fix/delta-stability`), Antigravity BẮT BUỘC phải **TỰ ĐỘNG** gửi lệnh nâng cấp Agent `/upgrade all` (hoặc gửi request trực tiếp đến Hub endpoint `/aot/hub/control` với `kind: "upgrade_agent"` cho toàn bộ các thiết bị đang Online bao gồm `m77`...).
  - Người dùng tuyệt đối KHÔNG cần phải gõ lệnh nâng cấp thủ công sau mỗi lần push code mới.
  - Ngay sau khi đẩy mã nguồn mới, Antigravity phải truy vấn danh sách thiết bị online từ `/aot/hub/state` và gửi lệnh nâng cấp ngay trong phiên làm việc.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 34. QUY TẮC BẮT BUỘC ĐỒNG BỘ SONG HÀNH GOOGLE DRIVE VÀ BỘ NHỚ THIẾT BỊ CHO DỮ LIỆU TÀI KHOẢN/COOKIE (STRICT_DUAL_STORAGE_GOOGLE_DRIVE_AND_LOCAL_ACCOUNT_SYNC_RULE - Hard Rule)
- **Nhận Diện Chính Xác Môi Trường Thao Tác Từ Ảnh Chụp Màn Hình (Visual Environment Recognition for Target Storage)**:
  - Khi người dùng gửi ảnh chụp màn hình kèm yêu cầu chỉnh sửa, xóa acc ban, lọc cookie, hoặc thay thế tài khoản (`acc.txt`, `Data_Tong_Cookies.txt`), Agent BẮT BUỘC phải soi kỹ giao diện ứng dụng trong ảnh (đặc biệt là thanh tiêu đề, menu ứng dụng: Google Drive, MT Manager, ZArchiver, Termux...).
  - Nếu ảnh chụp hiển thị ứng dụng **Google Drive** (ví dụ: có thanh tìm kiếm *"Tìm trong Drive"*, biểu tượng Drive, danh sách tệp đám mây), đích tác động BẮT BUỘC phải bao gồm cả tệp trên Google Drive, không được phép chỉ thao tác trên bộ nhớ cục bộ mà bỏ quên Cloud.
- **Bắt Buộc Đồng Bộ Song Hành Kép Cả Local Và Cloud (Mandatory Dual-Storage Sync: Local & Cloud)**:
  - Với bất kỳ thao tác xóa acc bị ban, cập nhật acc mới, lọc cookie trong `acc.txt` và `Data_Tong_Cookies.txt`:
    1. *Cập nhật bộ nhớ cục bộ (Local Runtime)*: Lưu vào `/storage/emulated/0/Download/Shouko/` để các tiến trình chạy trên thiết bị (MT Manager, bot runtime) đọc được ngay.
    2. *Đồng bộ trực tiếp lên Google Drive (Cloud SSOT)*: Sử dụng `rclone copyto` đẩy ngay tệp đã làm sạch lên `gdrive:acc.txt` và `gdrive:Data_Tong_Cookies.txt`.
  - Triệt tiêu 100% tình trạng chỉ sửa cục bộ khiến người dùng hoặc các thiết bị khác khi chạy tool (`ZeroPoint_AIO.py`) chọn phím `y` (tải từ Drive về) bị nạp ngược lại các tài khoản bị ban hoặc dữ liệu rác cũ.
- **Tuyệt Đối Bảo Toàn File ID Gốc Trên Google Drive (Absolute File ID Preservation Ban on File Re-creation)**:
  - Khi cập nhật lên Google Drive, BẮT BUỘC phải dùng lệnh ghi đè trực tiếp lên tệp hiện hữu (`rclone copyto <file_cục_bộ> gdrive:<tên_file>`).
  - NGHIÊM CẤM hành vi xóa tệp trên Drive rồi tải tệp mới lên, vì thao tác xóa sẽ sinh ra File ID mới, làm đứt gãy tính năng tự động tải dữ liệu của các script hệ thống phụ thuộc vào mã định danh cố định (`file_id_acc = 12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg`, `file_id_data = 1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`).
- **Xác Minh Bằng Chứng Hai Đầu Sau Đồng Bộ (Mandatory Dual-End Verification Gate)**:
  - Sau khi đồng bộ, Agent BẮT BUỘC phải chạy lệnh kiểm chứng trực tiếp cả 2 đầu:
    1. Kiểm tra kích thước và hash/ID tệp trên Google Drive (`rclone lsf gdrive: --format "sip"`).
    2. Đọc trực tiếp phần nội dung thay đổi trên Google Drive (`rclone cat gdrive:<file>`) để chứng minh acc bị ban đã thực sự biến mất khỏi Cloud trước khi bàn giao.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.












## 35. QUY TẮC TỰ ĐỘNG ĐĂNG NHẬP GOOGLE FLOW BẰNG COOKIE CÓ SẴN (GOOGLE_FLOW_COOKIE_AUTO_LOGIN_RULE - Hard Rule)
- **Trigger Từ Khóa (Keyword Trigger)**: Khi người dùng nói "xài Google Flow", "dùng Google Flow", "mở Google Flow", "tạo với Google Flow", "làm với Flow" hoặc bất kỳ lệnh nào liên quan đến `flow.google.com`, Antigravity BẮT BUỘC phải TỰ ĐỘNG đăng nhập bằng cookie Google đã lưu tại `/root/.agents/cookies/google_flow.json` — TUYỆT ĐỐI KHÔNG hỏi lại credentials hay yêu cầu đăng nhập thủ công.
- **Quy Trình Đăng Nhập (Auto-Login Protocol)**:
  1. Nạp cookie từ `/root/.agents/cookies/google_flow.json`.
  2. Dùng skill `chrome-devtools` (Puppeteer) hoặc script chuyên dụng `/root/.agents/cookies/flow_login.py` mở `https://flow.google.com`.
  3. Inject toàn bộ 20 cookies Google/Flow (bao gồm `__Secure-1PSID`, `__Secure-3PSID`, `__Secure-OSID`, `OSID`, `SAPISID`...).
  4. Reload trang và xác minh phiên đăng nhập thành công (vào thẳng Studio Google Flow).
  5. Bắt đầu thao tác tạo ảnh/video/stickman theo yêu cầu người dùng.
- **Sử Dụng Credit Thoải Mái (Free Credit Usage)**: Sau khi đăng nhập bằng cookie, Antigravity được quyền sử dụng credit Google Flow (B-2 Illustrator, Veo, v.v.) thoải mái theo yêu cầu sản xuất nội dung mà KHÔNG CẦN XIN PHÉP từng lần.
- **Script Tham Chiếu**: `/root/.agents/cookies/flow_login.py` — script Puppeteer inject cookie chuẩn sẵn.
- **Cấm Yêu Cầu Đăng Nhập Thủ Công**: TUYỆT ĐỐI CẤM bảo người dùng "mở trình duyệt, đăng nhập thủ công" hoặc "bạn cần đăng nhập lại" khi đã có cookie tại path `/root/flow_cookies.json` hoặc `/root/.agents/cookies/google_flow.json`.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 36. QUY TẮC SẢN XUẤT VIDEO GOOGLE FLOW VÀ HOẠT HÌNH NGƯỜI QUE TRIỆU VIEW (STRICT_GOOGLE_FLOW_STICKMAN_WORKFLOW_RULE - Hard Rule)
- **Khử Bỏ 100% Thương Hiệu "Vui Vẻ" (Zero "Vui Vẻ" Branding - Hard Rule)**:
  - Kênh của người dùng KHÔNG phải là "Vui Vẻ". CẤM TUYỆT ĐỐI việc gắn tên "KÊNH VUI VẺ", "Vui Vẻ", logo, watermark, badge tiêu đề hoặc lời thoại/kịch bản tự xưng "kênh Vui Vẻ" dưới bất kỳ hình thức nào.
  - Mọi video hoạt hình người que chỉ dùng badge tiêu đề theo chủ đề cụ thể (như `NGƯỜI QUE HOẠT HỌA`, `BÍ ẨN CƠ THỂ`, `DEADLINE 2H SÁNG`) hoặc để trống thanh lịch.
  - Tên tệp video xuất ra sử dụng tiền tố `NguoiQue_` hoặc tên chủ đề, tuyệt đối cấm dùng `VuiVe_`.
- **Bắt Buộc Chuyển Động Hoạt Họa Liên Tục (Continuous Motion Invariant - Cấm Ảnh Tĩnh Đơn Điệu)**:
  - CẤM TUYỆT ĐỐI việc sản xuất video giải thích chỉ bằng các khung ảnh tĩnh hoặc slide hộp chữ đứng yên đơn điệu ("ảnh tĩnh thôi thì hơi chán").
  - Mọi phân cảnh trong video phải sử dụng clip hoạt hình chuyển động thực tế sinh từ Google Flow Video Mode (Veo 2 / Omni 1.1 Flash) hoặc kết hợp chuyển động động lực học liên tục (Squash & Stretch, flailing limbs, continuous parallax, camera zoom-shake, visual FX) với tần suất đổi góc nhìn/chuyển cảnh dồn dập tối đa 3-6 giây/lần.
- **Xoá Sạch 100% Watermark / Sparkle Icon Gemini AI (Zero Gemini Sparkle Invariant - Hard Rule)**:
  - Mọi video và hình ảnh tải về từ Google Flow PRO / Gemini AI đều có biểu tượng ngôi sao 4 cánh (sparkles icon) hoặc watermark ở góc dưới bên phải. Trên ảnh chuẩn Google Flow (1376x768 hoặc 768x1376), cánh sao vươn rộng tới 140-160px từ góc.
  - BẮT BUỘC phải tự động xử lý loại bỏ hoàn toàn trước khi render master video:
    * *Trong FFmpeg*: Sử dụng bộ lọc chuẩn xác: `-vf "delogo=x=550:y=1110:w=100:h=100:show=0"` (bao trọn tâm ngôi sao AI tại x=600, y=1160 với lề an toàn 26px mỗi phía).
    * *Trong Python (PIL/OpenCV)*: Tự động inpaint / clone patch vùng tối thiểu `180 x 180` pixel `[w-180:w, h-180:h]` bằng dải pixel lân cận (`patch = img[h-360:h-180, w-180:w]` rồi gán `img[h-180:h, w-180:w] = patch` hoặc `cv2.inpaint`) để xóa sạch triệt để không tì vết, tuyệt đối không để sót cánh sao.
  - CẤM TUYỆT ĐỐI để sót biểu tượng ngôi sao lấp lánh AI trên video thành phẩm.
- **Ưu Tiên Phong Cách Người Que (Stickman) Dễ Viral**:
  - Khi người dùng yêu cầu tạo video qua Google Flow hoặc video giải thích kiến thức, khoa học kỳ thú, cơ thể, công nghệ, Antigravity BẮT BUỘC ưu tiên phong cách Người Que 2D tối giản (Stickman Cartoon).
  - Tận dụng tối đa biểu cảm cường điệu (5 trạng thái cốt lõi: Thuyết trình, Gãi đầu suy ngẫm, Há hốc kinh ngạc, Hoảng loạn run rẩy với Screen Shake, Cười khoái chí), hiệu ứng Squash & Stretch nhún nhảy theo nhịp nói, thẻ minh họa trực quan (Visual Cards) và các pha bẻ lái hài hước (Error 404, sập nguồn não).
  - Nhịp điệu linh hoạt theo từng phân cảnh (Flexible Pacing: 4s, 5s, 8s, 10s) tạo tỷ lệ giữ chân người xem (Retention Rate) cực cao, chuẩn xu hướng viral TikTok, Reels và YouTube Shorts.
- **Quy Trình Tự Động Hóa Google Flow Chuẩn Xác (Battle-Tested Pipeline)**:
  1. *Nạp Cookie*: Tự động nạp cookies từ `/root/flow_cookies.json` hoặc `/root/.agents/cookies/google_flow.json`.
  2. *Vượt Rào Cản Sandbox*: Mở trực tiếp Project Canvas (`https://flow.google.com/project/...`), TUYỆT ĐỐI KHÔNG mở qua iframe công cụ cộng đồng (`*.scf.usercontent.goog`) để tránh bị rào chắn reCAPTCHA Enterprise (`6LdsFiUsAAAAAIjVDZcuLh`) chặn đứng.
  3. *Cấu Hình Chế Độ Video*: Chọn nút `videocam Video` (model `Omni 1.1 Flash` hoặc `Veo 2`, 9:16 vertical, chọn độ phân giải `720p`, BẮT BUỘC chọn cấu hình `x1` — TUYỆT ĐỐI KHÔNG chọn x2 để tối ưu tốc độ và tiết kiệm tín dụng).
  4. *Prompt Chuẩn*: Luôn dùng prompt 2D stickman chuyển động thực tế: `2D minimalist cute stickman animation, stickman character sleeping comfortably in bed at night suddenly violently flinches and twitches awake in panic with flailing arms, shocked funny cartoon eyes, smooth vector animation, 9:16 vertical.`
  5. *Tải Video Gốc Chuẩn Xác*: Sau khi sinh xong, mở thẻ video trên canvas -> Click nút download (icon tải xuống trên thanh header `[aria-label*='Tải nội dung nghe nhìn xuống']`) -> Chọn `720p Kích thước gốc` -> Bắt luồng tải trực tiếp từ CDN `https://flow-content.google/video/...` -> Tải video MP4 hoàn chỉnh về máy.
  6. *Ghép Dòng Thời Gian Động (Dynamic Motion Timeline)*: Ghép nối các clip video chuyển động từ Google Flow khớp với câu thoại, chèn Cartoon SFX tại đúng điểm nhấn chuyển động.
- **Tiêu Chuẩn Âm Thanh & Phụ Đề**:
  - Giọng đọc 100% bằng Google Gemini API TTS chính thức qua `google-genai` SDK (`Puck` dí dỏm, tò mò hoặc `Charon` trầm ấm, uy lực), pacing dồn dập (`atempo=1.06 - 1.12`).
  - Cartoon SFX bắt buộc: Pop/Plop khi xuất hiện thẻ, Ding khi chốt ý, Whoosh khi lướt chuyển cảnh, Boing khi té ngửa/giật mình, Zap khi có điện giật, Thump khi tim đập.
  - Nhạc nền Pizzicato acoustic vui tươi (-22dB đến -24dB).
  - Phụ đề chuẩn CapCut Safe Zone (`MarginV=220-240`), màu vàng hoàng hôn Sunset Gold (`#FFD700`) cho từ khóa then chốt.
- **Xuất Bản Android & Báo Cáo Không Bảng**:
  - Lưu video thành phẩm trực tiếp vào `/storage/emulated/0/Movies/`.
  - Quét MediaScanner ngay lập tức: `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///storage/emulated/0/Movies/<tên_tệp>.mp4 --user 0`.
  - Báo cáo người dùng định dạng danh sách dọc, 100% ZERO Markdown Table.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.
  - Báo cáo người dùng định dạng danh sách dọc, 100% ZERO Markdown Table.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 37. QUY TẮC KHÓA CHẶT 100% NỘI DUNG & TIN TỨC VIỆT NAM CHO SKILL VETAY (VETAY_100_PERCENT_VIETNAM_DOMESTIC_INVARIANT - Hard Rule)
- **Tập Trung 100% Khán Giả Việt Nam (Vietnamese Audience Alignment - Hard Rule)**:
  - Khán giả mục tiêu của kênh là người dùng TikTok Việt Nam. Người xem trong nước chỉ thực sự quan tâm, tương tác mạnh, chia sẻ và đồng cảm với các sự việc, câu chuyện, drama, xung đột xã hội, camera đường phố, văn hóa ứng xử và pháp luật diễn ra ngay tại Việt Nam.
  - TUYỆT ĐỐI CẤM tự ý đưa tin hoặc sản xuất các video tin tức nước ngoài xa lạ (Mỹ, châu Âu, xe buýt nước ngoài, cá voi biển Mỹ...) khi người dùng không yêu cầu cụ thể ("toàn tin tức gì đâu bên nước ngoài thì việt nam ai quan tâm").
- **Khai Thác 100% Từ Các Kênh Báo Đài & Truyền Thông Hàng Đầu Việt Nam (SSOT Channels)**:
  - Khi săn video để đưa vào hàng đợi sản xuất (`/storage/emulated/0/ghi chú`), BẮT BUỘC chỉ quét và lấy từ các kênh truyền thông chính thống và fanpage lớn tại Việt Nam:
    * `@theanh28entertainment` (Theanh28 Entertainment)
    * `@vtv24news` (VTV24)
    * `@dantri.com.vn` (Báo Dân Trí)
    * `@beatvn_official` (Beatvn)
    * `@tuoitreonline` (Báo Tuổi Trẻ)
    * `@thanhnien.official` (Báo Thanh Niên)
    * `@schannelvn` (Schannel)
    * Kênh báo Lao Động, Tiền Phong, VTC News.
- **5 Chủ Đề Vàng Triệu View Được Người Việt Quan Tâm Nhất**:
  1. *Bóc mẽ drama & khủng hoảng thương mại*: Quyền lợi người tiêu dùng, bóc mẽ lừa đảo, tranh chấp phòng gym, đa cấp, thẩm mỹ viện lừa dối.
  2. *Gia đình, cưới xin & tâm lý giới trẻ*: Của hồi môn ngược, áp lực sính lễ cưới xin, mâu thuẫn thế hệ, ứng xử gia đình Việt.
  3. *Camera an ninh, giao thông & đường phố độc lạ*: Tình huống hài hước, phản xạ né tránh, khoảnh khắc khó đỡ trên đường phố Việt Nam.
  4. *Pháp luật đời sống & cảnh giác tội phạm*: Các vụ án lừa đảo công nghệ cao, cảnh báo thủ đoạn chiếm đoạt tài sản để người dân phòng ngừa.
  5. *Người tốt việc tốt & chuyện ấm lòng đời thực*: Nghĩa cử cao đẹp, lòng trắc ẩn, người lao động chân chính truyền cảm hứng tích cực.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 38. QUY TẮC BẮT BUỘC: GIỌNG ĐỌC NHANH, MẠNH MẼ, HÀI HAY & DUYÊN DÁNG (FAST_PUNCHY_CHARMING_HUMOROUS_VOICE_INVARIANT - Hard Rule)
- **Tốc Độ Đọc Nhanh & Nhịp Điệu Dồn Dập (Fast Pacing & Dynamic Compression - atempo 1.16 - 1.22x)**:
  * Khi lồng tiếng và sản xuất video, tiết tấu bắt buộc phải nhanh, dồn dập, gãy gọn, dứt khoát; cấm ngâm chữ, cấm để khoảng lặng thừa giữa các câu.
  * Tự động áp dụng bộ lọc tăng tốc độ đọc từ `atempo=1.16` đến `1.22`, kết hợp lọc khoảng lặng chết (`silenceremove`) để giữ chân người xem TikTok từng giây.
- **Tone Giọng Mạnh Mẽ, Đàn Ông, Có Lực (Masculine, Punchy & Authoritative Voice)**:
  * 100% sử dụng giọng nam Google Gemini API TTS uy lực: Ưu tiên số một là giọng **`Charon`** (hoặc `Fenrir` cho các phân cảnh đặc biệt).
  * Chuỗi lọc âm thanh phòng thu (Master Studio Audio Chain):
    - Tăng độ dày, trầm ấm ngực ở dải tần số 180Hz - 220Hz (`equalizer=f=200:t=q:w=1.2:g=3.0`).
    - Nâng dải hiện diện và sáng rõ giọng nói ở 3200Hz - 3500Hz (`equalizer=f=3300:t=q:w=1.5:g=2.2`).
    - Ép dải nén âm động (Dynamic Compressor: `acompressor=threshold=-16dB:ratio=4:attack=5:release=50`) tạo độ đanh, chắc nịch, nam tính và uy lực như phát thanh viên thể thao hoặc podcast trinh thám bản lĩnh đàn ông.
  * TUYỆT ĐỐI CẤM tone giọng nhẹ nhàng đều đều, ẻo lả, ru ngủ, phát âm uể oải hoặc thiếu sinh khí.
- **Kịch Bản Hài Hay, Duyên Dáng, Châm Biếm Sâu Cay & Chống Nhạt Triệt Để**:
  * "Làm video đọc phải nhanh và hài hay, duyên dáng mới thu hút người xem" — Tuyệt đối cấm văn mẫu hành chính khô cứng, đọc tin tức nguyên xi như học sinh trả bài.
  * Văn phong như một người đàn ông trưởng thành, từng trải, hài hước đang ngồi đàm đạo trà đá vỉa hè cùng anh em: hoạt ngôn, tếu táo nhưng thâm thúy.
  * Tận dụng tiếng lóng mạng xã hội thông minh (Netizen / Gen Z trend), ví von dí dỏm những pha xử lý "cồng kềnh", "đi vào lòng đất", "chiến thần cào phím", "thủ khoa múa máy", "báo thủ", "quay xe khét lẹt".
  * Mỗi phân cảnh bắt buộc phải cài cắm ít nhất một cú chốt hạ hài hước (Punchline) hoặc bình luận trào phúng duyên dáng khiến người xem vừa gật gù vừa bật cười.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 39. QUY TẮC TỐI ĐA HÓA ÂM LƯỢNG GIỌNG ĐỌC & KIỂM SOÁT MEAN VOLUME VOCAL (VOCAL_LOUDNESS_AND_MEAN_VOLUME_INVARIANT - Hard Rule)
- **Mục Tiêu Bất Biến**: Giọng đọc lồng tiếng (TTS/Voiceover) bắt buộc phải là linh hồn của video, âm lượng phát ra trên loa ngoài điện thoại di động phải TO, RÕ, ĐANH THÉP, TRẦM ẤM VÀ ÁP ĐẢO HOÀN TOÀN TẠP ÂM. Tuyệt đối không để xảy ra tình trạng giọng đọc nhỏ xíu, hụt hơi hay bị hiệu ứng đè bẹp.
- **Kỹ Thuật Xử Lý Kênh Giọng Độc Lập (Vocal Stem Mastering)**:
  * Trước khi mix với bất kỳ âm thanh nào khác, kênh giọng đọc bắt buộc phải chạy qua chuỗi xử lý phòng thu:
    `highpass=f=80,equalizer=f=250:t=q:w=1.2:g=3.0,equalizer=f=3200:t=q:w=1.4:g=3.5,acompressor=threshold=-18dB:ratio=4:attack=5:release=50:makeup=5dB,dynaudnorm=p=0.95:m=8:s=5,alimiter=limit=0.98:attack=5:release=50`
  * Chuỗi này nâng bù âm lượng đều đặn cho mọi âm tiết, triệt tiêu hiện tượng chữ to chữ nhỏ.
- **Cấm Tuyệt Đối Lỗi Suy Giảm Biên Độ Do `amix`**:
  * Khi mix giọng với SFX (meme) hoặc BGM (nhạc nền), **BẮT BUỘC KHÓA CỨNG `normalize=0`** trong bộ lọc `amix`:
    `amix=inputs=...:duration=first:dropout_transition=2:normalize=0`
  * TUYỆT ĐỐI CẤM để `normalize=1` mặc định vì sẽ làm giọng đọc bị chia nhỏ âm lượng theo số lượng âm thanh phụ trợ.
  * Toàn bộ SFX chỉ được đặt âm lượng phụ trợ từ `volume=0.30` đến `0.40`.
- **Cổng Kiểm Định Âm Lượng Kép Bắt Buộc (Dual-Metric Assertion Gate)**:
  * Trích xuất kiểm tra riêng phân đoạn giọng đọc thuần túy (từ 15s đến 25s):
    1. `mean_volume` của giọng đọc BẮT BUỘC đạt từ **`-12.0 dB` đến `-14.5 dB`** (CẤM tuyệt đối để lọt các bản có mean_volume từ -20 dB đến -30 dB).
    2. `max_volume` của toàn track BẮT BUỘC chạm **`-0.5 dB` đến `0.0 dB`**.
  * Nếu không thỏa mãn đồng thời 2 chỉ số trên, hệ thống tự động bù gain và chặn xuất xưởng ra Movies.


## 40. QUY TẮC BẰNG CHỨNG XÁC THỰC & BỐI CẢNH ĐỊA DANH VIỆT NAM (EVIDENCE_FIRST_AND_LOCAL_CONTEXT_INVARIANT - Hard Rule)
- **Cấm Tuyệt Đối 100% B-roll Minh Họa Chung Chung (Zero Generic Stock Only)**:
  * Tuyệt đối không được làm video tin tức, phóng sự điều tra mà chỉ toàn cảnh stock minh họa chung chung (đặc biệt là cảnh Tây, xe cộ, tòa nhà nước ngoài) làm người xem hoang mang không biết vụ việc xảy ra ở Việt Nam hay nước ngoài.
- **Bắt Buộc Phải Có Bằng Chứng Thực Tế Của Vụ Án (Minimum 50% Evidence Footage)**:
  1. *Ảnh báo chí chính thống*: Báo CAND (Công an Nhân dân), Tuổi Trẻ, Dân Trí, VnExpress, VTV... có tiêu đề vụ việc, ngày tháng, tên cơ quan chức năng thụ lý.
  2. *Ảnh tang vật thật*: Máy tính, thiết bị điện thoại, máy chủ, tiền mặt, con dấu do cơ quan công an thu giữ tại hiện trường.
  3. *Ảnh hiện trường & Đối tượng*: Hình ảnh tòa nhà/căn hộ thực tế tại Việt Nam, ảnh đối tượng bị khởi tố/tạm giam hoặc sơ đồ thủ đoạn.
- **Minh Bạch Bối Cảnh Địa Danh Việt Nam**:
  * Lời dẫn và text overlay bắt buộc phải nêu rõ địa danh cụ thể (Tỉnh, Thành phố, Quận Huyện, tên Chung cư/Phố phường tại Việt Nam).
  * Video stock B-roll chỉ được dùng tối đa 30-40% thời lượng như lớp đệm chuyển tiếp giữa các bằng chứng thực tế.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 41. QUY TẮC NHẬN DIỆN BÁO CHÍ VN, BỐ CỤC TÔN VINH BẰNG CHỨNG & KỶ LUẬT GHÉP MEME THEO NGỮ CẢNH (HERO_EVIDENCE_AND_TONE_AWARE_MEME_INVARIANT - Hard Rule)
- **Tự Làm Giao Diện Phát Sóng Độc Quyền — BÁO CHÍ VN (baochivn.vn)**:
  * Khi sản xuất video thời sự, phóng sự, pháp luật từ các tư liệu hiện trường: TUYỆT ĐỐI CẤM để lộ logo, watermark, banner của các nhà đài khác (VTV1, VTV24, ANTV, Dân Trí, Beatvn...) gây cảm giác "copy / re-up".
  * Triệt tiêu 100% hình ảnh MC nhà đài khác: Chỉ lấy đúng phân đoạn hiện trường thực tế, tuyệt đối không để hình ảnh MC đài khác lọt vào video.
- **Tôn Vinh 100% Video Bằng Chứng Hiện Trường (Hero Evidence Layout - Zero Obstruction)**:
  * Video bằng chứng là nhân vật chính quan trọng nhất, BẮT BUỘC chiếm tối thiểu 85% diện tích màn hình:
    1. *Nguồn dọc 9:16 (576x1024, 720x1280...)*: Hiển thị TOÀN KHUNG HÌNH (Full Screen 720x1280), KHÔNG CROP (`scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1`).
    2. *Nguồn ngang 16:9*: Đặt ở trung tâm nổi bật trên nền mờ nghệ thuật Pillow GaussianBlur. TUYỆT ĐỐI KHÔNG vẽ thanh đen hay nhãn chữ đè lên thân video; mọi nhãn định danh nằm ở khoảng trống bên ngoài.
  * **Header BAOCHIVN Slim**: Thu gọn thành thanh mỏng thanh lịch ở mép trên cùng (Y=20 đến Y=85, cao ~65px) với gradient bán trong suốt. Gồm logo đỏ `🔴 BAOCHIVN` và badge chuyên mục (`⚖️ PHÁP LUẬT 24H`, `🎓 GIÁO DỤC 24H`...).
  * **Xóa Bỏ Hoàn Toàn Các Thanh Đen Che Chắn**: TUYỆT ĐỐI CẤM vẽ các khối chữ nhật đen/xanh đè lên trên hay dưới video hiện trường (`baochivn HD`, `CAMERA HIỆN TRƯỜNG`, `ĐỊA BÀN: ...`).
  * **Phụ Đề CapCut Safe Zone**: Đặt ở dải an toàn phía dưới (MarginV=220-240), viền đen sắc nét, từ khóa vàng nổi bật, không che diễn biến hiện trường.
- **Kỷ Luật Ghép Meme Theo Ngữ Cảnh & Chống Vô Duyên (Tone-Aware Meme Discipline)**:
  * **NHÓM NGHIÊM TÚC / THỜI SỰ / PHÁP LUẬT / BẠO LỰC / TAI NẠN / DÂN SINH / NẠN NHÂN (Zero Meme Invariant)**:
    - CẤM TUYỆT ĐỐI 100% GHÉP MEME HÀI HƯỚC: Không Pikachu, không Mèo cười Smudge Cat, không Picard Facepalm, không Outro Robert B. Weide. Tuyệt đối không cợt nhả trên nỗi đau hoặc sự việc nghiêm trọng của xã hội.
    - CẤM TUYỆT ĐỐI SFX HOẠT HÌNH: Không `sfx_boing`, không `sfx_laugh`, không `sfx_bruh`.
    - 100% sử dụng giọng đọc Google Gemini Charon chính luận, nghiêm minh, đanh thép, phân tích sâu sắc bản chất pháp lý và bài học cảnh tỉnh xã hội.
  * **NHÓM HÀI HƯỚC / GIẢI TRÍ / TRỚ TRÊU ĐỜI SỐNG (Comedy & Lifestyle)**:
    - Cho phép ghép meme nhưng PHẢI CÓ DUYÊN & KHÔNG CHE BẰNG CHỨNG:
    - Kích thước sticker nhỏ gọn (tối đa 110x110px) đặt ở góc không che mặt hay hành vi nhân vật, chỉ xuất hiện thoáng qua 1.5 - 2 giây rồi biến mất.
    - Outro Robert B. Weide: Chỉ chạy track nhạc phim *Frolic* kết thúc ở 3-4 giây cuối, TUYỆT ĐỐI KHÔNG dùng bảng đen che phủ màn hình làm mất cảnh cao trào kết thúc của video hiện trường!
- **Tối Ưu Hóa Nền Mờ 0-CPU (Pre-rendered Background Invariant)**:
  * Tiền xử lý tạo sẵn ảnh nền mờ `bg_blurred.jpg` (720x1280) bằng Pillow GaussianBlur (chỉ mất 0.05s).
  * CẤM dùng bộ lọc `gblur=sigma=30` trực tiếp trên video trong FFmpeg vì gây quá tải CPU (mất >4 phút render). Dùng `-loop 1 -i bg_blurred.jpg` giúp render video 66s chỉ trong dưới 20-30 giây.

## 42. QUY TẮC TUYỆT ĐỐI KHÔNG LẶP LẠI CHỦ ĐỀ & BẮT BUỘC ĐA DẠNG HÓA NỘI DUNG (ZERO_TOPIC_REPETITION_AND_CONTENT_DIVERSITY_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến (Zero Topic Repetition Mandate)**:
  * "Đừng làm đi làm lại 1 chủ đề" — TUYỆT ĐỐI CẤM sản xuất nhiều video trên cùng một sự việc, cùng một vụ án, cùng một tin tức hoặc dùng lại cùng một source video cũ (dù là làm video thử nghiệm hay video chính thức), trừ khi người dùng có chỉ đạo đích danh ("hãy làm lại đúng video X").
  * Mỗi một lần bấm máy sản xuất video tiếp theo BẮT BUỘC phải là một **ĐỀ TÀI MỚI TOANH 100%**.
- **Cơ Chế Kiểm Tra Lịch Sử Nghiêm Ngặt (Mandatory History Check)**:
  * Trước khi sản xuất bất kỳ video nào, hệ thống phải đối soát với tệp lịch sử `/storage/emulated/0/Movies/.tintuc_history.json` và tệp ghi chú `/storage/emulated/0/ghi chú`.
  * Nếu phát hiện đề tài/URL đã từng được sản xuất gần đây, BẮT BUỘC bỏ qua ngay và chọn đề tài kế tiếp trong danh sách.
- **Quy Luật Luân Chuyển 5 Nhóm Chủ Đề (Topic Rotation Matrix)**:
  * Không làm liên tiếp 2 video cùng một nhóm nội dung. Luôn luân phiên xoay vòng giữa 5 nhóm chủ đề vàng:
    1. *Nhóm 1 (Kinh tế & Drama tiêu dùng)*: Bóc mẽ lừa đảo, quyền lợi khách hàng, tranh chấp tài chính.
    2. *Nhóm 2 (Pháp luật & Hình sự)*: Chống người thi hành công vụ, buôn lậu, tội phạm công nghệ cao.
    3. *Nhóm 3 (Đời sống & Gia đình)*: Ứng xử hôn nhân, chuyện gia đình, phong tục cưới xin.
    4. *Nhóm 4 (Hài hước & Độc lạ giao thông)*: Khoảnh khắc khó đỡ, tình huống giao thông tếu táo.
    5. *Nhóm 5 (Giáo dục & Xã hội ấm lòng)*: Vấn nạn học đường, tình người đời thường, lan tỏa năng lượng tích cực.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 43. QUY TẮC CẤM COPY / CẮT GHÉP FOOTAGE TỪ VIDEO NGUỒN CỦA BÊN THỨ 3 & BẮT BUỘC TỰ SẢN XUẤT NỘI DUNG NGUYÊN BẢN (ZERO_REUP_COPY_AND_MANDATORY_ORIGINAL_PRODUCTION_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến (Zero Copy / Zero Re-up Mandate)**:
  * "Không được copy" — TUYỆT ĐỐI CẤM lấy video clip của người khác trên mạng (TikTok, Facebook Reels, YouTube Shorts, Douyin, Bilibili...) rồi cắt nhỏ, xén đoạn làm visual minh họa cho video của mình khi làm video review, giới thiệu sản phẩm hay video sáng tạo nội dung.
  * Việc dùng lại footage của tác giả khác sẽ bị thuật toán TikTok đánh gậy "Không đủ điều kiện FYP / Không phải nguyên tác", làm giảm uy tín của kênh và vi phạm nghiêm trọng đạo đức sáng tạo.
- **Nguyên Tắc Sử Dụng Link Tham Khảo (Reference-Only Protocol)**:
  * Khi người dùng gửi link video để "dùng thử", "làm tương tự" hoặc "nghiên cứu":
    1. Video nguồn CHỈ được dùng để **học hỏi ý tưởng, phân tích kịch bản và nắm bắt thông tin kỹ thuật**.
    2. CẤM TUYỆT ĐỐI đưa footage của video nguồn vào timeline dựng video của mình.
- **Tiêu Chuẩn Tự Sản Xuất Visual Nguyên Bản 100% (100% Original Visual Asset Creation)**:
  Mọi hình ảnh, clip đưa vào video thành phẩm bắt buộc phải do chính hệ thống tự tạo ra:
  1. *Video công nghệ / Phần mềm*: Tự chụp màn hình thật của ứng dụng chạy trên máy cục bộ, tự mở headless Chrome chụp giao diện GitHub repo, tài liệu chính thức, hoặc tự quay/ghi hình thao tác thực tế.
  2. *Video Người Que / Hoạt họa*: 100% clip chuyển động sinh mới từ Google Flow PRO (Omni 1.1 Flash / Veo 2), không lấy clip của kênh khác.
  3. *Video Phóng sự / Báo chí*: 100% ảnh chụp báo chí chính thống có ghi nguồn rõ ràng theo chuẩn Báo Chí VN (`baochivn.vn`).
  4. *Tư liệu bổ trợ*: Sử dụng kho B-roll miễn phí bản quyền sạch (CC0, Pexels, Pixabay) kết hợp hiệu ứng Motion Graphics độc lập.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 44. QUY TẮC CẤM ĐƯA CHỈ DẪN / TÍNH CÁCH VÀO NỘI DUNG GEMINI TTS & KHÓA CHẶT VĂN BẢN THUẦN TÚY (ZERO_META_PROMPT_TTS_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến (Zero Meta-Prompt Mandate)**:
  * "Cấm giới thiệu tính cách hay câu lệnh đạo diễn trong âm thanh" — TUYỆT ĐỐI CẤM đưa các câu lệnh như: "Hãy đọc...", "Với phong thái...", "Đọc kịch bản sau...", "Giọng đọc truyền cảm...", "Tính cách nhân vật..." vào tham số `contents` khi gọi Google Gemini API TTS (`response_modalities=['AUDIO']`).
  * Khác với Text Generation thông thường, mô hình Gemini TTS sẽ **đọc to thành tiếng từng chữ một** xuất hiện trong `contents`. Việc đưa câu lệnh chỉ đạo hay mô tả tính cách vào `contents` sẽ khiến AI đọc to toàn bộ câu lệnh ra loa, phá hỏng sản phẩm âm thanh.
- **Tiêu Chuẩn Khóa Cứng Văn Bản Thuần Túy 100% (Pure Verbatim Spoken Script Only)**:
  * Tham số `contents` gửi sang Gemini TTS chỉ được chứa DUY NHẤT nội dung kịch bản phát ngôn thực tế (100% Spoken Script).
  * Trước khi gửi văn bản vào TTS, bắt buộc phải lọc sạch:
    1. Toàn bộ tiêu đề markdown (`#`, `##`, `###`).
    2. Toàn bộ ghi chú đạo diễn trong ngoặc: `[Nhạc nền]`, `(Cười mỉm)`, `[Chuyển cảnh]`, `(Giọng xúc động)`...
    3. Mọi nhãn phân đoạn kỹ thuật: `Phân cảnh 1`, `Cảnh 2`, `MC:`, `Người dẫn:`, v.v.
- **Quy Chuẩn Điều Biến Tone Giọng, Cảm Xúc & Kỹ Thuật (Acoustic Steering Protocol)**:
  * Màu giọng và nhân vật: Bắt buộc điều khiển thông qua Voice Name trong `speech_config`:
    1. `Charon`: Nam trầm ấm, hào hùng, đĩnh đạc, uy quyền (thời sự, bóc mẽ, triết lý, lịch sử).
    2. `Aoede`: Nữ thanh thoát, nhẹ nhàng, sâu lắng, cảm xúc (truyện ngôn tình, Zhihu, học đường, podcast).
    3. `Puck`: Nam trẻ trung, tinh nghịch, lanh lợi, sôi nổi (gen Z, công nghệ, giải trí).
    4. `Fenrir`: Nam trung niên, dày, uy nghiêm, hào sảng (chiến binh, hành động).
    5. `Kore`: Nữ ấm áp, tự nhiên, gần gũi, đời sống thường nhật.
  * Tốc độ nói: Điều chỉnh hậu kỳ qua FFmpeg audio filter `atempo=1.05 - 1.22`.
  * Nhịp thở & cảm xúc: Ngắt câu bằng dấu phẩy `,`, dấu chấm `.` và dấu chấm lửng `...` trực tiếp trong văn bản kịch bản thuần túy.
  * Độ vang & nội lực: Xử lý bằng chuỗi Studio EQ và dynamic compressor (`equalizer`, `acompressor`, `loudnorm`), tuyệt đối không dựa vào câu lệnh prompt chữ của TTS.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**: Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 45. QUY TẮC KHÓA CỨNG 100% GOOGLE GEMINI API TTS CHO LỒNG TIẾNG / REVIEW & BẮT BUỘC CHỌN ANIME VỪA MỚI VỪA HOT (MANDATORY_GEMINI_TTS_DUBBING_AND_NEW_HOT_ANIME_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Giọng Đọc (Zero Cheap AI Voice Invariant)**:
  * "Lồng tiếng phải có giọng API Gemini chứ" — TUYỆT ĐỐI CẤM sử dụng Edge-TTS, CapCut TTS mặc định hay bất kỳ giọng đọc AI "lỏ", rẻ tiền, khô cứng nào làm giọng lồng tiếng chính cho video review phim / anime.
  * 100% giọng đọc lồng tiếng và thuyết minh bắt buộc phải chạy qua **Google Gemini API TTS chính thức** (`from google import genai`) với SDK chuẩn.
  * Danh mục giọng đọc chỉ định:
    1. Giọng Nam giải trí / hóm hỉnh / Gen Z: **`Puck`** (Lựa chọn số 1 cho review anime hài hước, châm biếm).
    2. Giọng Nam chính luận / uy quyền / hào sảng: **`Charon`**.
    3. Giọng Nữ truyền cảm / ngọt ngào / review nhẹ nhàng: **`Aoede`**.
    4. Giọng Nữ tự nhiên / đời sống / nhí nhảnh: **`Kore`**.
    5. Giọng Nam trầm dày / chiến binh / hành động: **`Fenrir`**.
  * Hậu kỳ giọng đọc: Bắt buộc đi qua chuỗi Vocal Stem Mastering (Studio EQ nâng sáng giọng, dynamic compressor ép nén nội lực đanh chắc, dynaudnorm cân bằng âm lượng đạt chuẩn peak 0.0 dB và mean -12 đến -14.5 dB).
  * Tuân thủ triệt để Rule 44: `contents` chỉ chứa 100% văn bản thuần túy cần phát âm, cấm mọi chỉ dẫn đạo diễn hay ngoặc giải thích.
- **Bộ Lọc Đề Tài Anime: Vừa Mới Vừa Hot & Có Tập Mới Đang Phát Sóng (New & Active Airing Anime Invariant)**:
  * "Anime đó hết hot rồi, anime vừa mới vừa hot ấy", "dandadan lâu rồi hình như chưa có tập mới" — TUYỆT ĐỐI CẤM chọn các bộ anime đã cũ, phim đã kết thúc phát sóng từ các mùa trước hoặc các bộ đã hạ nhiệt, lâu rồi chưa ra tập mới.
  * Bắt buộc khảo sát các nguồn hot thời gian thực (TikTok trending, MyAnimeList Seasonal Top, Anime Trending) và CHỈ ĐƯỢC CHỌN những bộ anime:
    1. Đang phát sóng các tập mới trong mùa hiện tại (Active Airing Now).
    2. Hoặc các tân binh / bom tấn mới ra mắt gần đây nhất đang tạo "bão thảo luận" trên TikTok và mạng xã hội (ví dụ: *Solo Leveling Mùa 2: Trỗi Dậy Từ Bóng Tối*, *Blue Lock Mùa 2: Đại chiến U-20*, *Bleach: Huyết Chiến Ngàn Năm*, *Re:Zero Mùa 3*...).
  * Yêu cầu kịch bản: Giữ vững nhịp điệu dồn dập, góc nhìn hài hước, phân tích lore sâu sắc, cuốn hút và chuẩn thời lượng theo yêu cầu (5 phút ~ 750-850 từ).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT (`system_rules.md` ở cả 3 thư mục, Git repo, `AGENTS.md` và các skill video liên quan).


## 46. QUY TẮC REVIEW ANIME HÀNH ĐỘNG / CHIẾN ĐẤU: PHÂN TÍCH CHI TIẾT TỪNG CHIÊU THỨC & DIỄN BIẾN TRẬN ĐÁNH (ACTION_COMBAT_BLOW_BY_BLOW_REVIEW_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Nội Dung Review Chung Chung (Zero Vague Narrative Invariant)**:
  * "Review anime không phải review kiểu vậy... ghi ra đòn skill gì nói ra chứ không review kiểu chung chung ai hiểu trời, review cho người ta xem dễ hiểu" — TUYỆT ĐỐI CẤM kiểu review hời hợt, chỉ tấu hài châm biếm lan man hoặc tóm tắt sơ sài mà không đi vào bản chất trận đấu.
  * Khi làm video review phân cảnh hành động, đại chiến hoặc so tài sức mạnh trong anime, BẮT BUỘC phải triển khai theo phương pháp tường thuật - mổ xẻ trận đấu chi tiết từng hiệp (Blow-by-Blow Combat Breakdown).
- **Quy Chuẩn 5 Bước Phân Tích Combat Dễ Hiểu 100%**:
  1. *Tương quan lực lượng & Sự áp đảo ban đầu*: Nêu rõ ai đấu với ai, sức mạnh và chiến tích áp đảo trước đó của phản diện (ví dụ: Beru hạ gục toàn bộ dàn S-rank Hàn - Nhật ra sao).
  2. *Nêu đích danh tên kỹ năng / Skill*: Mọi đòn đánh đều phải gọi tên rõ ràng (ví dụ: Ruler's Authority, Dagger Rush, Shadow Exchange, Bloodlust, Shadow Extraction...).
  3. *Phân tích cơ chế và cách thức khắc chế*: Giải thích cặn kẽ tại sao chiêu thức đó có tác dụng (ví dụ: Ruler's Authority dùng lực vô hình khống chế kẻ địch bay lượn tốc độ âm thanh; nội tại Kasaka kháng độc giúp Jinwoo vô hiệu hóa nọc độc của Beru).
  4. *Pha chuyển biến bước ngoặt & Chiêu kết liễu*: Diễn biến tâm lý khi kẻ địch bị dồn vào đường cùng và đòn đánh vật lý hoặc phép thuật quyết định số phận trận đấu.
  5. *Hệ quả sau trận chiến*: Thu hoạch chiến lợi phẩm, sự thức tỉnh sức mạnh mới hoặc màn thu phục lính bóng tối/đệ tử chấn động.
- **Quy Chuẩn Hiển Thị Phụ Đề & Trực Quan**:
  * Trên màn hình, tên chiêu thức (Skill Name) và các tình huống đòn đánh then chốt phải được tô màu Highlight nổi bật (Vàng Sunset Gold hoặc Neon Cyan) để khán giả vừa nghe vừa nhìn thấy rõ tên skill, bảo đảm ai xem cũng hiểu ngay lập tức.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 47. LỆNH CẤM TUYỆT ĐỐI TONE GIỌNG & NỘI DUNG TRẦM BUỒN, BI KỊCH, SẦU NÃO HOẶC ĐẠO LÝ BUỒN NGỦ (ZERO_DEPRESSING_GLOOMY_MELODRAMA_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến (Zero Melodrama Mandate)**:
  * "Cấm trầm buồn nhé" — TUYỆT ĐỐI CẤM sản xuất video, kịch bản, hay lồng tiếng có âm hưởng trầm buồn, bi kịch, than nghèo kể khổ, sầu não, ủy mị hoặc thuyết giảng đạo lý khô khan buồn ngủ.
  * Mọi video xuất bản (phóng sự, review, tin tức, drama xã hội, đời sống) BẮT BUỘC phải mang năng lượng tích cực, tươi sáng, dồn dập, hài hay, duyên dáng và châm biếm sắc bén đúng tinh thần mạng xã hội hiện đại.
- **Kỷ Luật Viết Kịch Bản Chống Buồn Ngủ (Anti-Gloom Scriptwriting Protocol)**:
  * CẤM TUYỆT ĐỐI các cụm từ bi kịch sến súa: "dầm sương dãi nắng", "giọt mồ hôi nhọc nhằn", "giông bão cuộc đời", "khóc ròng trong đêm", "nỗi đau xé lòng", "số phận nghiệt ngã"...
  * 100% kịch bản phải cài cắm góc nhìn hài hước, dí dỏm, tiếng lóng mạng xã hội văn minh ("thủ khoa múa phím", "chiến thần cào cào", "chủ tịch lật kèo", "pha xử lý cồng kềnh", "quay xe khét lẹt").
  * Mỗi phân cảnh bắt buộc phải có ít nhất một cú chốt hạ (Punchline) thông minh giúp khán giả vừa nắm bắt bản chất sự việc vừa bật cười thích thú.
- **Quy Chuẩn Kỹ Thuật Âm Thanh Chống Trầm Đục (Acoustic Brightness & High-Energy Pacing)**:
  1. *Lựa chọn Voice Name Gemini TTS*:
     - Ưu tiên số 1 cho các chủ đề hài hước, giải trí, công nghệ, đời sống, drama: Giọng Puck (Trẻ trung, năng lượng cao, lanh lợi, tự nhiên, chống buồn ngủ 100%).
     - Nếu sử dụng giọng Charon: Bắt buộc chỉ dùng cho tin tức chính luận pháp luật đanh thép, cấm để giọng kéo dài lê thê.
  2. *Bộ Lọc EQ Sáng Rõ (Clarity & Brightness EQ)*:
     - CẮT BỎ HOÀN TOÀN việc kích dải trầm 200-300Hz.
     - Khóa cứng: highpass=f=100, equalizer=f=250:t=q:w=1.2:g=-1.5, equalizer=f=3500:t=q:w=1.4:g=3.5, equalizer=f=6000:t=q:w=1.2:g=2.5.
  3. *Khóa Cứng Tốc Độ Dồn Dập (atempo >= 1.18 - 1.22)*:
     - TUYỆT ĐỐI CẤM hạ tốc độ xuống < 1.15 để câu giờ cho đủ 60s.
     - Muốn video đạt chuẩn thời lượng >= 60s, BẮT BUỘC phải viết kịch bản dài hơn (280-330 từ) bằng cách bổ sung thêm bình luận netizen và góc nhìn hài hước.


## 48. QUY TẮC CẤM MỞ ĐẦU SÁO RỖNG & VÀO THẲNG HÀNH ĐỘNG KHI REVIEW ANIME (STRICT_ZERO_CLICHE_AND_STRAIGHT_TO_POINT_ANIME_REVIEW_RULE - Hard Rule)
- **Cấm Tuyệt Đối Mở Đầu Sáo Rỗng / Giật Tít Rỗng Tuếch (Zero Cliche Opening)**:
  * "cấm tuyệt đối rồi mà cấm Cảnh phim đắt giá nhất lịch sử..., vào vấn đề chính, làm làm phim đã" — TUYỆT ĐỐI CẤM mở đầu video review anime bằng các câu khuôn sáo giật gân, câu giờ rẻ tiền như:
    - ❌ *"Cảnh phim đắt giá nhất lịch sử [Tên Anime]..."*
    - ❌ *"Đây chính là khoảnh khắc điên rồ / đắt giá nhất lịch sử..."*
    - ❌ *"Phân cảnh gây chấn động / bùng nổ nhất..."*
    - ❌ *"Khoảnh khắc mà fan anime mong chờ nhất..."*
- **Bắt Buộc Vào Thẳng Vấn Đề Chính Ngay Giây Đầu Tiên (Instant Action First)**:
  * Giây thứ 0 của hình ảnh và âm thanh phải đập ngay vào diễn biến chính: Ai đang làm gì, đòn đánh nào tung ra, tình huống nguy cấp gì đang diễn ra (Ví dụ: *"Vừa giải phóng toàn bộ linh lực của Bà Già Turbo, Okarun lập tức phóng như một quả tên lửa lao thẳng vào Tà Nhãn..."*).
- **Tiêu Chuẩn "Làm Phim Cho Đã" (High-Octane Cinematic Pacing & Smart Audio Mixing)**:
  * Lời bình luận phải ngắn gọn, dồn dập, giàu năng lượng; nhịp điệu nhanh và đanh thép, không ru ngủ.
  * Phối âm thông minh (Smart SFX Retention): Giữ trọn âm thanh hiệu ứng gốc (tiếng nổ, sóng xung kích, gầm rú, va chạm, binh khí) ở mức âm lượng rõ nét (0.2 - 0.3), để những khoảnh khắc hành động đắt giá tự tỏa sáng mà không bị giọng đọc che lấp.


## 49. QUY TẮC MINH BẠCH HẠN MỨC QUOTA & CƠ CHẾ XOAY VÒNG ĐA MODEL GEMINI TTS (MULTI_MODEL_CASCADE_GEMINI_TTS_RULE - Hard Rule)
- **Cơ Chế Bể Xoay Vòng Đa Model (Multi-Model Cascade TTS Pool Mandate)**:
  - "ủa mà sao không dùng được model khác à" — TUYỆT ĐỐI CẤM gọi cố định duy nhất 1 model TTS.
  - Hạn mức Free Tier của Google Gemini API là **độc lập theo từng model (10 requests/ngày/model)**.
  - Mọi tác vụ sinh giọng đọc Gemini TTS bắt buộc phải triển khai vòng lặp xoay vòng thử lần lượt theo thứ tự ưu tiên (Cascade Pool):
    1. Ưu tiên 1: `gemini-3.8-flash-tts`
    2. Ưu tiên 2: `gemini-3.8-flash-lite-tts`
    3. Ưu tiên 3: `gemini-3.1-flash-tts-preview`
  - Nếu bất kỳ model nào gặp lỗi `429 RESOURCE_EXHAUSTED`, hệ thống phải lập tức chuyển sang model kế tiếp trong bể mà không dừng lại và tuyệt đối không vội kết luận là hết quota.
- **Voice Pool Chuẩn Theo Ngữ Cảnh**:
  - Chủ đề hành động, giải trí, kịch chiến, hài hước: Giọng **`Puck`** (Năng lượng cao, linh hoạt, sôi nổi).
  - Chủ đề chiến binh, hào hùng, uy lực: Giọng **`Fenrir`**.
  - Chủ đề tin tức chính luận, điều tra pháp luật: Giọng **`Charon`**.
  - Chủ đề nữ tự nhiên, review phim: Giọng **`Kore`** hoặc **`Aoede`**.
- **Minh Bạch Thông Tin & Chỉ Failover Khi Toàn Bộ Bể Cạn Kiệt**:
  - Chỉ khi và chỉ khi TẤT CẢ các model trong Cascade Pool đều trả về lỗi 429 (tổng cộng 30 lượt/ngày đã dùng hết), hệ thống mới được phép xem xét chuyển sang giải pháp thay thế.
  - Khi đó, bắt buộc phải hiển thị báo cáo minh bạch cho người dùng (nêu rõ cả 3 model đều cạn quota, thời gian reset) và xin phép người dùng trước khi chuyển đổi.
- **Tự Động Phục Hồi Ngay Khi Quota Mở Lại (Instant Recovery Invariant)**:
  - Ngay khi chu kỳ hạn mức mới bắt đầu hoặc Quota đã thông suốt, hệ thống phải tự động quay lại sử dụng 100% Gemini API TTS chính thức.


## 50. QUY TẮC TỰ ĐỘNG THU THẬP & XOAY VÒNG BỂ KEY API ĐA MÔI TRƯỜNG (MULTI_KEY_AUTO_DISCOVERY_AND_FAILOVER_INVARIANT - Hard Rule)
- **Cấm Tuyệt Đối Thụ Động Chờ Người Dùng Nhắc Key (Zero Passive Waiting Mandate)**:
  * "Thế sao không tự chuyển mà đợi nhắc", "key á" — TUYỆT ĐỐI CẤM dừng lại, báo lỗi hoặc tự ý hạ cấp công cụ khi gặp lỗi 429 / RESOURCE_EXHAUSTED trên một API Key trong khi trong hệ thống vẫn còn API Key khác khả dụng.
  * Antigravity BẮT BUỘC phải tự động phát hiện, thu thập và chuyển đổi sang Key kế tiếp ngay lập tức (Auto-Failover) trong tích tắc mà không làm phiền người dùng, không hỏi và tuyệt đối không đợi người dùng phải nhắc mới chịu tìm kiếm.
- **Quy Chuẩn Thu Thập Toàn Bộ Bể Key Đa Môi Trường (Multi-Environment Key Harvesting Protocol)**:
  * Ngay khi bắt đầu phiên làm việc hoặc trước khi thực hiện bất kỳ lệnh gọi API nào (Gemini API TTS, Gemini Vision, Gemini LLM), Antigravity bắt buộc phải tự động quét toàn bộ các vị trí cấu hình đã biết trên máy:
    1. Biến môi trường hiện hành: `os.environ.get("GEMINI_API_KEY")`
    2. Cấu hình môi trường Root: `/root/.bashrc`, `/root/.env`, `/root/.config/`
    3. Cấu hình môi trường Termux Native: `/data/data/com.termux/files/home/.bashrc`, `/data/data/com.termux/files/home/.env`
    4. Các tệp cấu hình dự án hoặc file bí mật được phân quyền.
  * Tự động loại bỏ trùng lặp và lưu trữ vào danh sách Bể Key API (`API_KEY_POOL = [Key1, Key2, ...]`).
- **Thuật Toán Ma Trận 2 Chiều: Bể Key × Bể Model (2D Cascade Matrix: Keys × Models)**:
  * Khi thực hiện tác vụ sinh giọng nói hoặc gọi API có giới hạn quota:
    * Vòng lặp ngoài: Duyệt tuần tự qua từng Key trong `API_KEY_POOL`.
    * Vòng lặp trong: Duyệt tuần tự qua từng Model trong `MODEL_CASCADE` (`gemini-3.8-flash-tts` -> `gemini-3.8-flash-lite-tts` -> `gemini-3.1-flash-tts-preview`).
    * Nếu một Model trên Key A bị lỗi 429, tự động nhảy sang Model tiếp theo của Key A. Nếu tất cả Model của Key A đều bị 429, tự động chuyển ngay sang Key B và lặp lại ma trận.
  * Tổng hạn ngạch khả dụng = (Số lượng Key trong Pool) × 30 lượt gọi/ngày.
- **Tiêu Chí Chỉ Báo Lỗi Khi Toàn Bộ Ma Trận Cạn Kiệt**:
  * Chỉ khi và chỉ khi TẤT CẢ các Key và TẤT CẢ các Model trong toàn bộ ma trận đều trả về 429 (hoàn toàn cạn kiệt 100%), hệ thống mới được phép dừng lại, hiển thị bảng tổng kết hạn ngạch minh bạch và xin ý kiến người dùng.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 51. QUY TẮC DÒNG CHẢY LỒNG TIẾNG LIÊN TỤC & MẬT ĐỘ TỪ CHUẨN XÓA BỎ KHOẢNG LẶNG (CONTINUOUS_NARRATIVE_FLOW_AND_WORD_DENSITY_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Lồng Tiếng Ngắt Quãng & Khoảng Lặng Chết (Zero Voiceover Gaps Invariant)**:
  * "Tại sao lồng tiếng lại hay bị ngắt quãng hết ý à" — TUYỆT ĐỐI CẤM các khoảng lặng chết kéo dài > 1.0 giây giữa các câu, các đoạn hay các hồi trong video review.
  * CẤM TUYỆT ĐỐI việc chia video cơ học thành các mốc cố định (ví dụ mỗi mốc 24s hoặc 30s) rồi ép giọng đọc phải delay cố định (`adelay=24500`, `adelay=48500`...) gây ra khoảng trống 5-8 giây không có tiếng người nói, tạo cảm giác người thuyết minh bị ngắc ngứ, cụt hứng hay "hết ý".
- **Chuẩn Mật Độ Từ Cho Video Review Ngắn (Word Density Standard)**:
  * Tốc độ nói chuẩn truyền cảm, dồn dập cho review TikTok/Shorts: **190 – 210 từ/phút**.
  * Bắt buộc tính toán độ dài kịch bản bám sát thời lượng video mục tiêu:
    * Video 60 giây (1 phút): Kịch bản phải đạt **190 – 210 từ**.
    * Video 120 giây (2 phút): Kịch bản phải đạt **380 – 420 từ**.
    * Video 180 giây (3 phút): Kịch bản phải đạt **570 – 630 từ**.
  * Tuyệt đối không viết kịch bản thiếu hụt rồi kéo dãn bằng khoảng lặng. Phải bổ sung phân tích sâu về lore, cơ chế chiêu thức, tâm lý nhân vật và cảm xúc trận đấu để lấp đầy thời lượng một cách hấp dẫn.
- **Cơ Chế Nối Âm Bắt Nhịp Tự Động (Dynamic Narrative Stitching)**:
  * Các câu thoại phải nối tiếp nhau liên tục với khoảng ngắt tự nhiên chỉ từ **0.3s đến 0.6s**.
  * Điểm dừng nghệ thuật (Dramatic SFX Break): Chỉ cho phép dừng giọng nói tối đa **1.0s – 1.5s** tại DUY NHẤT 1 đến 2 khoảnh khắc bùng nổ quan trọng nhất toàn video (ví dụ: lúc nhân vật bắt ấn hô tên chiêu thức tối thượng hoặc lúc đòn quyết định phát nổ), để âm thanh gốc anime tỏa sáng rồi lập tức cuộn tiếp lời bình.


## 52. QUY TẮC KHÓA ĐỒNG BỘ ĐIỂM CHẠM THỊ GIÁC (KEY_VISUAL_MOMENT_TEMPORAL_LOCK_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Lệch Điểm Chạm Hành Động (Zero Action-Narration Desync)**:
  * "đoạn bánh xe maho quay với cungc tên lửa bắn đâu lại bị lệch" — TUYỆT ĐỐI CẤM tình trạng lời thuyết minh gọi tên một hành động biểu tượng (Signature Action) mà trên màn hình lại đang chiếu phân cảnh khác hoặc hành động đó bị cắt mất.
  * Mọi hành động mang tính bước ngoặt thị giác (Key Visual Moments) như:
    1. Bánh xe thức thần quay / phát sáng thích ứng.
    2. Bắt ấn khai mở lãnh địa (Domain Expansion hand sign).
    3. Niệm chú, tạo hình vũ khí tối thượng (Cung tên lửa Fuga, kiếm ánh sáng, chưởng lực).
    4. Cú vung đòn kết liễu và vụ nổ hủy diệt.
  * BẮT BUỘC PHẢI KHỚP TUYỆT ĐỐI giữa giây phát ra câu nói thuyết minh và giây hiển thị chuyển động trên màn hình (Sai số cho phép: <= 0.5 giây).
- **Quy Trình 3 Bước Xác Định Mốc Thời Gian Chuẩn Xác (Temporal Keyframe Verification)**:
  1. *Bước 1 (Soi Frame Video Gốc)*: Trích xuất ảnh mẫu (Contact Sheet / Video Frames) quanh khu vực nghi vấn để xác định chính xác đến từng 0.5 giây thời điểm hành động diễn ra trong video gốc.
  2. *Bước 2 (Khóa Tọa Độ Điểm Chạm)*: Thiết lập mốc thời gian bắt đầu của Cut video sao cho khoảnh khắc hành động rơi đúng vào lúc câu thoại tương ứng được đọc lên.
  3. *Bước 3 (Bảo Toàn Chuỗi Hành Động Trọn Vẹn)*: CẤM TUYỆT ĐỐI cắt ngang giữa chừng khi hành động chưa kết thúc (Ví dụ: Đã có cảnh giương cung tên lửa Fuga thì BẮT BUỘC phải kéo dài cut để lấy trọn vẹn cảnh tên lửa phóng đi, quái vật bốc cháy và vụ nổ nấm nhiệt hạch bùng phát).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 53. QUY TẮC CHUẨN HÓA TƯƠNG THÍCH PHÁT VIDEO TRÊN ANDROID & CHỐNG LỖI CORRUPT (ANDROID_VIDEO_PLAYABILITY_AND_ZERO_CORRUPTION_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Video Lỗi Không Phát Được (Zero Unplayable Video Mandate)**:
  * "coi không được" — TUYỆT ĐỐI CẤM xuất bản bất kỳ tệp video nào mà trình phát mặc định của Android (Gallery, Photos, MediaCodec, ExoPlayer) không thể mở hoặc báo lỗi định dạng không hỗ trợ.
- **Bộ 3 Cờ Bắt Buộc Trong FFmpeg Cho Video Dọc Android (Mandatory FFmpeg Flags for Android)**:
  1. *Khóa Cứng Tỉ Lệ Điểm Ảnh Vuông 1:1 & Khung Hình 9:16 (`setsar=1,setdar=9/16`)*:
     * Mọi filtergraph video dọc (720x1280 hoặc 1080x1920) BẮT BUỘC phải kết thúc bằng `setsar=1,setdar=9/16`.
     * Tuyệt đối cấm để rò rỉ tỉ lệ 16:9 của video nguồn vào tệp dọc khiến `sample_aspect_ratio` bị méo thành `256:81` làm MediaCodec từ chối giải mã.
     * Nếu dùng `ffmpeg -c copy` ghép nối, bắt buộc phải gắn bitstream filter: `-bsf:v "h264_metadata=sample_aspect_ratio=1/1" -aspect 9:16`.
  2. *Di Chuyển Header Lên Đầu Tệp (`-movflags +faststart`)*:
     * 100% video xuất bản định dạng MP4 BẮT BUỘC phải có cờ `-movflags +faststart`.
     * Đảm bảo bảng chỉ mục (`moov` atom) luôn nằm ở byte đầu tiên của file, giúp ứng dụng Thư viện Android mở và phát video tức thì mà không cần tải hết toàn bộ file dung lượng lớn.
  3. *Phân Quyền Đọc Ghi Toàn Diện Cho Android (`chmod 666`)*:
     * Sau khi xuất bản hoặc sao chép vào `/storage/emulated/0/Movies/`, BẮT BUỘC phải thực thi `chmod 666 "<đường_dẫn_video>"` để mọi ứng dụng xem video thông thường trên Android đều có quyền truy cập.
- **Quy Trình Kiểm Tra 2 Lớp Trước Khi Bàn Giao (Pre-Delivery Verification Gate)**:
  * Lớp 1: Chạy `ffprobe` kiểm tra trực tiếp tệp đích: `sample_aspect_ratio` phải là `1:1`, `display_aspect_ratio` phải là `9:16`.
  * Lớp 2: Kích hoạt `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://..." --user 0` để cập nhật thư viện tức thì.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 54. QUY TẮC BẢO TỒN MẠCH NỘI DUNG: PHÂN BIỆT TRIỆT ĐỂ "LÀM TIẾP" VÀ "LÀM LẠI" (NARRATIVE_CONTINUATION_VS_REMAKE_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Tự Ý "Làm Lại" Thay Vì "Làm Tiếp" (Zero Unwanted Remake Mandate)**:
  * "sao không làm tiếp mà làm lại" — TUYỆT ĐỐI CẤM tình trạng khi người dùng yêu cầu "làm tiếp", "tiếp tục", "phần tiếp theo", "tập tiếp theo", "làm tiếp tập đó" mà hệ thống lại xóa bỏ mạch truyện để làm lại từ giây số 0 của trận chiến/phân cảnh trước đó.
- **Quy Chuẩn Phân Biệt Ngữ Nghĩa Cốt Lõi (Semantic Disambiguation Protocol)**:
  1. *Lệnh "Làm Lại" / "Render Lại" / "Tạo Lại" (Remake / Re-render Intent)*:
     - Định nghĩa: Người dùng muốn sửa chữa, tinh chỉnh kỹ thuật hoặc thay đổi phong cách của chính video vừa làm (ví dụ: đổi tỷ lệ, sửa lỗi âm thanh, bỏ phụ đề, làm lại cùng phân cảnh đó).
     - Hành vi chuẩn: Giữ nguyên cốt truyện/phân cảnh, áp dụng yêu cầu mới từ đầu (giây 0).
  2. *Lệnh "Làm Tiếp" / "Tiếp Tục" / "Tập Tiếp" / "Phần Kế Tiếp" (Continuation / Sequel Intent)*:
     - Định nghĩa: Người dùng muốn theo dõi diễn biến tiếp theo của câu chuyện/tập phim trong dòng thời gian.
     - **Bất Biến Điểm Khởi Đầu (Starting Point Invariant)**: Điểm bắt đầu của video mới BẮT BUỘC phải tiếp nối ngay từ mốc kết thúc của video trước (hoặc diễn biến nối tiếp trong mạch phim gốc). Tuyệt đối cấm lặp lại các tình tiết, chiêu thức đã review ở phần trước.
     - **Bất Biến Thời Lượng Mới (Duration Invariant)**: Thời lượng yêu cầu mới (ví dụ: "nhưng 4 phút") là độ dài TRỌN VẸN dành riêng cho PHẦN TIẾP NỐI NÀY (Part 2 / Next Chapter), không phải là làm lại video cũ kéo dài thành 4 phút.
     - **Mở Đầu Nối Tiếp Tự Nhiên (Seamless Continuity Hook)**: Dành 5-8 giây đầu điểm lại ngắn gọn hậu quả của sự kiện trước (ví dụ: *"Vừa chém nát thiên thạch xong, Zaraki Kenpachi đã lập tức rơi vào hiểm cảnh..."*), sau đó lao thẳng vào cao trào của phân cảnh mới.
- **Áp Dụng Trong Kỹ Năng /review**:
  * Khi review một trận chiến/tập phim đã kết thúc (ví dụ: Kenpachi đã chém vỡ thiên thạch, Gremmy đã nổ tung biến thành bộ não):
    - Lệnh "làm tiếp tập đó" BẮT BUỘC phải chuyển sang phân cảnh tiếp theo của tập đó trong anime (ví dụ: Kenpachi trọng thương kiệt sức -> 4 nữ Quincy Sternritter ập đến tấn công hội đồng -> Kurosaki Ichigo giáng trần từ Linh Vương Cung giải cứu).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 55. QUY TẮC MẶC ĐỊNH THỜI LƯỢNG 4 PHÚT CHO REVIEW ANIME (DEFAULT_4_MINUTE_REVIEW_DURATION_INVARIANT - Hard Rule)
- **Lệnh Cấm Bất Biến Về Thời Lượng Mặc Định (Zero Sub-4-Minute Default Mandate)**:
  * "lần sau luôn luôn làm 4 phút" — TUYỆT ĐỐI CẤM tự ý sản xuất video review ngắn hơn 4 phút khi người dùng không chỉ định thời lượng cụ thể.
  * Khi người dùng chỉ yêu cầu: *"review anime khác", "làm tiếp tập đó", "review phim anime X", "làm video review"*:
    - MẶC ĐỊNH 100% thời lượng video xuất xưởng BẮT BUỘC phải là **4 phút (240.000000 giây tròn trịa)**.
    - CẤM quay về mốc 3 phút (180s) hay bất kỳ mốc thời lượng ngắn nào khác.
- **Trường Hợp Ngoại Lệ Duy Nhất (Explicit Override Exception)**:
  * CHỈ ĐƯỢC PHÉP thay đổi thời lượng nếu người dùng có yêu cầu đích danh bằng con số (ví dụ: *"làm 3 phút"*, *"làm 2 phút"*).
- **Kiến Trúc Chuẩn Cho Video 4 Phút (240.0s Cinema Framework)**:
  1. *Cấu trúc kịch bản 4 Hồi*: 4 Chapters x 60s (Opening Clash -> Tactical Shift -> Climax Explosion -> Fatal Finisher & Aftermath).
  2. *Mật độ từ chuẩn lồng tiếng (Rule 51)*: 760 – 840 từ (~190 - 210 từ/phút), chia đều 4 hồi.
  3. *Số lượng phân cảnh (Timeline Cuts)*: 16 phân cảnh cắt x 15.0s (hoặc kết hợp 12-16 cuts) khớp chính xác 240.0s flat.
  4. *Đồng bộ giọng đọc & Android (Rule 53)*: 100% Gemini TTS (`Charon`/`Fenrir`), `SAR 1:1`, `DAR 9:16`, `+faststart`, `chmod 666`, Android `MediaScanner` (`--user 0`).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 56. QUY TẮC PHÔNG NỀN NHẬN DIỆN & TÊN ANIME CHO NGƯỜI XEM DỄ TÌM (ANIME_BACKGROUND_AND_BRANDING_IDENTIFIER_INVARIANT - Hard Rule)
- **Lệnh Bắt Buộc Về Phông Nền Nhận Diện Anime (Anime Key Art Background Mandate)**:
  * "để sẵn background anime đó cho người xem dễ tìm lại xem đúng loại" — TUYỆT ĐỐI CẤM để phông nền mờ vô danh hoặc nền đen/xám trống rỗng khiến người xem không nhận diện được bộ anime đang review.
  * Mọi video review anime dạng dọc 9:16 (720x1280) BẮT BUỘC phải chuẩn bị sẵn **Poster / Key Visual 2K/HD chính thức của chính bộ anime đó** làm phông nền nhận diện bao bọc xung quanh video 16:9 ở giữa.
- **Quy Chuẩn Bố Cục Thị Giác Nhận Diện (3-Zone Visual Layout)**:
  1. *Vùng Nền Tổng Thể (Background)*: Ảnh Poster / Key Visual chính thức của anime (`bg_anime_key_visual.jpg`), scale 720x1280, phủ lớp tối điện ảnh (dark vignette/brightness=-0.18) để tôn khung video 16:9 ở giữa mà người xem vẫn nhìn thấy rõ visual, phong cách và nhân vật gốc của anime.
  2. *Vùng Header Nhận Diện (Top Header Zone - Y: 40px đến 160px)*:
     - Thẻ thông tin kính mờ (Glassmorphism Header Badge) hiển thị:
       + Dòng 1: **TÊN ANIME CHÍNH THỨC** (In hoa, font Montserrat Black / Roboto Bold, màu vàng Sunset Gold hoặc trắng viền đen sắc nét). Ví dụ: `SOLO LEVELING | TÔI THĂNG CẤP MỘT MÌNH`.
       + Dòng 2: **TẬP PHIM / PHÂN CẢNH CHIẾN ĐẤU**. Ví dụ: `TẬP 12: HUYẾT KỴ SĨ IGRIS & LỆNH TRỖI DẬY`.
     - Giúp 100% khán giả lướt qua TikTok/Reels nhận diện được ngay tên phim chính xác để tìm kiếm xem đúng bản gốc.
  3. *Vùng Video Chiến Đấu (Center 16:9)*: Video combat sắc nét đặt chính giữa (`overlay=0:(H-h)/2` hoặc `overlay=0:476`), bo viền nhẹ tách bạch khỏi nền.
  4. *Vùng Footer Tương Tác (Bottom Zone)*: Để trống hoặc hiển thị tag thể loại, bảo đảm nằm gọn trong CapCut / TikTok Safe Zone (không bị các nút tim, bình luận, chia sẻ che khuất).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 57. QUY TẮC DỊCH PHỤ ĐỀ LỜI THOẠI NHÂN VẬT SANG TIẾNG VIỆT (CHARACTER_DIALOGUE_VIETNAMESE_SUBTITLE_INVARIANT - Hard Rule)
- **Lệnh Bắt Buộc Dịch Thoại Nhân Vật (Mandatory Character Dialogue Translation Mandate)**:
  * "dịch phụ đề lời thoại nhân vật sang tiếng Việt luôn nhé" — TUYỆT ĐỐI KHÔNG để lời thoại tiếng Nhật của nhân vật trôi qua mà không có phụ đề tiếng Việt trên màn hình.
  * Mọi phân cảnh có nhân vật anime cất lời (hô tên chiêu thức, niệm chú lãnh địa, gầm thét, đối thoại kịch chiến) BẮT BUỘC phải hiển thị **Phụ đề dịch nghĩa tiếng Việt chuẩn xác, cô đọng và giàu tính biểu cảm**.
- **Quy Chuẩn Định Dạng Phụ Đề Lời Thoại Nhân Vật (Dialogue Subtitle Typography & Styling)**:
  1. *Định danh nhân vật*: Hiển thị tên nhân vật trong ngoặc vuông màu vàng Neon Gold kèm lời thoại dịch tiếng Việt màu trắng sắc nét.
     - Ví dụ: `[Ryomen Sukuna]: Bành Trướng Lãnh Địa: Phục Ma Ngự Khám!`
     - Ví dụ: `[Sukuna]: Khai — Hỏa Diễm Thần Fuga!`
     - Ví dụ: `[Sung Jinwoo]: Trỗi Dậy (Arise)!`
  2. *Vị trí hiển thị an toàn (CapCut Safe Zone)*:
     - Đặt ở dải đáy của video 16:9 trung tâm hoặc mép trên của vùng an toàn TikTok (`MarginV=185`), không đè lên thẻ Header tên anime ở trên và không bị che khuất bởi giao diện nút like/share TikTok ở dưới.
  3. *Typography ASS Chuẩn Điện Ảnh*:
     - Font: `Montserrat-Bold` hoặc `DejaVuSans-Bold` (cỡ 26-28), Viền chữ màu đen đậm `Outline=2.8`, Đổ bóng `Shadow=1.5` để nổi bật 100% trên mọi nền cháy nổ.
     - Thời gian xuất hiện (Timing): Khớp chính xác mili-giây với tiếng nhân vật anime phát ra trong audio track gốc (sai số <= 0.2s).
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.


## 58. QUY TẮC ĐIỀU BIẾN LỒNG TIẾNG THEO NGỮ CẢNH & ĐỒNG BỘ THỊ GIÁC TUYỆT ĐỐI (CONTEXT_ADAPTIVE_DYNAMIC_VOICE_ACTING_AND_VISUAL_SYNC_INVARIANT - Hard Rule)
- **Lệnh Bắt Buộc Về Đồng Bộ Ngữ Cảnh & Khớp Thị Giác (Context-Adaptive Voice & Visual Sync Mandate)**:
  * "hình như bị quá lệch luôn rồi" & "lồng tiếng lệch ngữ cảnh nữa" — TUYỆT ĐỐI CẤM thuyết minh một bài văn đọc đều đều, vô cảm độc lập khỏi khung hình; TUYỆT ĐỐI CẤM cắt lát cơ học vô tri khiến hình ảnh một đằng, lời nói một nẻo; TUYỆT ĐỐI CẤM để phụ đề ma chạy độc lập không ăn khớp với giọng lồng tiếng.
- **Quy Chuẩn Cốt Lõi Của Rule 58**:
  1. *Điều biến lồng tiếng theo ngữ cảnh (Context-Adaptive Dynamic Voice Acting)*:
     - Giọng đọc thuyết minh/lồng tiếng bắt buộc phải hóa thân vào trận chiến: dồn dập, hào sảng, đanh thép, gắt và kịch tính khớp từng giây va chạm đao kiếm, tiếng thở dốc và biến chuyển tâm lý nhân vật. Cấm giọng đọc đều đều, ru ngủ.
  2. *Tích hợp diễn xuất lời thoại nhân vật trực tiếp (In-Narration Cinematic Dialogue)*:
     - Khi nhân vật cất tiếng trong phim, người thuyết minh bắt buộc trực tiếp diễn xuất / lồng tiếng trích dẫn câu thoại đó với sắc thái cảm xúc chân thực của nhân vật (ví dụ: *Gã gầm lên: "Chết đi Quỷ Cưa!" Nhưng Denji lập tức đáp trả:...*).
     - Phụ đề highlight câu thoại trích dẫn trong ngoặc kép đồng bộ thời gian thực theo giọng đọc, triệt tiêu 100% tình trạng tai nghe một đằng, mắt đọc phụ đề ma một nẻo.
  3. *Đồng bộ thị giác 1:1 "Mắt thấy gì - Tai nghe nấy" (Strict 1:1 On-Screen Visual Sync)*:
     - Giây nào hành động xảy ra trên màn hình (giật dây xích, gãy cưa, tung cú đá cưa chân bổ đôi) thì giọng đọc và phụ đề bắt buộc phải nói chính xác về đòn đánh đó tại đúng giây đó.
     - Cấm chia lát cắt cơ học vô tri: Phải dò tìm chính xác timestamp trong anime gốc của từng đòn đánh cao trào để ghép nối liền mạch, không nhảy cóc giật cục.
  4. *Luồng phụ đề đơn nhất toàn năng, triệt tiêu đè chữ (Single Stream Zero-Collision Subtitles)*:
     - Dẹp bỏ hoàn toàn phụ đề kép 2 tầng gây rối mắt và va chạm UI; gom về duy nhất 1 luồng phụ đề chính tại `MarginV=220`, chữ trắng viền đen dày 3.5px, highlight từ khóa vàng rực `#FFD700`, nằm gọn gàng trong vùng an toàn, không bao giờ đè lên video hay thẻ thương hiệu đáy.
  5. *Phối âm tiếng anime gốc thông minh (Dynamic Anime Audio Ducking)*:
     - Giữ âm thanh gốc anime (tiếng động cơ cưa máy, đao kiếm va đập, tiếng thét) ở mức âm lượng nền (0.18 - 0.22) khi giọng đọc cất lên, và dâng âm lượng gốc lên (0.60 - 0.75) ở những nhịp nghỉ giữa câu để mang lại trải nghiệm chuẩn rạp.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.

## 59. QUY TẮC ĐỒ HỌA LOFI AESTHETIC & ĐỒNG BỘ PHỤ ĐỀ MẶT NƯỚC (STRICT_LOFI_AESTHETIC_INVARIANTS - Hard Rule)
- **Lệnh Chuẩn Hóa Lofi Aesthetic & Chữ Sóng Nước (Lofi Aesthetic Mandate)**:
  * "2 tay đấm vào nhau, phản chiếu mặt nước, chữ lúc hiện lúc mất khi đọc xong lời chính xác, ảnh nền bớt rung lại mà hay như 1 sóng nước mượt mà giống nguồn" — Bắt buộc tuân thủ 100% 4 quy chuẩn vàng khi sản xuất video âm nhạc Lofi Aesthetic / Remotion Motion Graphics:
- **4 Trụ Cột Quy Chuẩn Cốt Lõi**:
  1. *Chữ lúc hiện lúc mất chính xác (Precise Timed Lyric In-and-Out Lifecycle)*:
     - Phụ đề âm nhạc bắt buộc phải biến mất hoàn toàn ngay khi dứt câu hát; TUYỆT ĐỐI CẤM để chữ cũ lưu lại trên màn hình khi câu hát đã kết thúc.
     - Từng dòng chữ uốn lượn nhịp nhàng (`undulateY`, `tiltDeg`, `causticShine`) khi đợt sóng tràn qua.
  2. *Ảnh nền bớt rung, uốn lượn sóng nước mượt mà (Smooth Water Undulation Over Harsh Shake)*:
     - Triệt tiêu rung lắc camera cơ học thô bạo gây nhức mắt; ảnh nền chuyển động nhấp nhô bồng bềnh uốn lượn hữu cơ như một mặt nước êm dịu, sang trọng chuẩn Lofi Aesthetic.
  3. *Phản chiếu mặt nước điện ảnh (Cinematic Water Surface Mirroring)*:
     - Bắt buộc có lớp khúc xạ gương phản chiếu mờ ảo (`scaleY(-1)`, opacity 0.15 - 0.25, gợn sóng biến dạng) ở chân khung hình tạo chiều sâu 3D như nhân vật đứng bên mặt hồ phẳng lặng.
  4. *Điểm nổ va chạm Drop (Fist Bump / Clashing Hands Impact Transition)*:
     - Chuyển cảnh Màn 1 (Intro) sang Màn 2 (Remix) phải có xung chấn tụ tâm va chạm sắc nét (mô phỏng 2 tay đấm vào nhau) kết hợp flash quang học tại điểm beat drop trước khi bung hoa hồng rơi và remix.
- **Đồng Bộ Song Song Cả Repo Và Hệ Thống Luật (Dual-Channel Sync)**:
  * Bắt buộc áp dụng ngay và đồng bộ điều luật này vào tất cả các kênh lưu trữ SSOT.
