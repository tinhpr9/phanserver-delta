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





