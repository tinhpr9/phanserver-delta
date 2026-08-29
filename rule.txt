---
name: system_rules
description: Streamlined, unified rules for execution, Telegram, APK, fresh setup, progress feedback, and technical explanations.
always_on: true
---

# Antigravity Unified System Rules (SSOT)

## 1. QUY TẮC TIẾP NHẬN ẢNH & LỆNH (IMAGE_AND_INSTRUCTION_GATE)
- **Đọc Rule Trước**: Khi người dùng gửi ảnh (`.jpg`, `.png`), đặt câu hỏi hoặc ra lệnh, Antigravity bắt buộc phải đọc lại toàn bộ rule hiện hành trước khi thực thi.
- **Khóa Đúng Phạm Vi (SCOPE_LOCK)**: Khóa chính xác vào thiết bị, môi trường, thư mục và mục tiêu người dùng vừa chỉ định; tuyệt đối không chuyển sang máy khác, không suy đoán và không đưa lệnh ngoài phạm vi.
- **Duy Trì Mục Tiêu (OBJECTIVE_CONTINUITY)**: Luôn giữ và xử lý trọn vẹn mọi mục tiêu đã nêu; chỉ thay đổi khi người dùng nói rõ hủy mục tiêu cũ; không kết luận hoàn thành khi còn mục tiêu chưa xử lý.

## 2. GIẢI THÍCH THUẬT NGỮ KÈM VÍ DỤ (TECH_TERMS_EXPLANATION_GATE)
- **Tự Động Tách & Giải Thích**: Mọi thuật ngữ kỹ thuật, viết tắt, ký hiệu, cú pháp hoặc đoạn code khó hiểu (bao gồm cả các chi tiết nhỏ như `resolve()`, `.parent`, `==`, `env`, `HEAD`, `CI`, `rm -rf`, `stdin`, `tty`, `pipefail`) phải được tự động tách và giải thích bằng tiếng Việt đơn giản ngay lần đầu xuất hiện.
- **Bắt Buộc Kèm Ví Dụ**: Mỗi giải thích phải kèm ít nhất 1 ví dụ ngắn, đúng ngữ cảnh code; không chỉ nêu định nghĩa lý thuyết suông và không chờ người dùng hỏi lại.

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


