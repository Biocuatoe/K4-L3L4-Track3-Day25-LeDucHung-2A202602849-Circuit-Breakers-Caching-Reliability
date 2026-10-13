# Lab 25B — Report

**Họ tên / nhóm:** Lê Đức Hùng — MSV 2A202602849  **Commit:** 8b2beee210b95e7e04c399f482ab884af1beca1f  **Điểm tự động (`make grade`):** 84.0 / 88 (cục bộ; 4 điểm SLO dữ liệu ẩn do giảng viên chấm)

> Mọi số trong report lấy từ artifact trong repo, có thể tái tạo: `reports/gameday/*.json` + CSV (`make baseline compare`),
> `reports/cache/*.json` (`make cache`), `reports/workflows.json` (`make workflows`), `reports/slo.json` (`make slo`),
> `reports/scoreboard.json` (`python scripts/grade.py --seeds 25,26,27`), `reports/experiments.json`
> (`python scripts/run_experiments.py` — toàn bộ thí nghiệm ở mục 2, 3, 8). Seed của tape = 25 (seed của `configs/gameday.yaml`);
> RNG jitter của client = 1 (mặc định của `factory.build_client`). Điểm cục bộ **không** gồm 4 điểm SLO trên dữ liệu ẩn
> (`slo_hidden.pass = null`: chỉ giảng viên chấm được) và 12 điểm chấm tay của report này.

**Phạm vi kiểm chứng.** Ngoài seed 25, mọi tape public (G1–G6, C1) được chạy với seed 26, 27 qua `scripts/grade.py --seeds 25,26,27`
(PASS cả ba), và client được quét thêm 30 seed (1–30) × 6 tape: **0** lần trượt check. Tôi cũng thử một bộ tape "giống ẩn"
(mọi mốc thời gian lệch +17 s, traffic ×3, capacity 20%, error 40%, latency +6 s; cache tape lệch +23 s) với seed 25–29: vẫn PASS
(đây chỉ là kiểm tra độ bền của riêng tôi, không phải kết quả của bộ tape ẩn thật).

---

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4.0 | FAIL |
| G1 | yours | 1.0 | 4.78 | 1.063 | 0.001 | 2.104 | 0.0 | PASS |
| G2 | naive | 0.456 | 15.034 | 9.904 | 8.904 | 4.627 | 155.0 | FAIL |
| G2 | yours | 1.0 | 4.958 | 1.013 | 0.003 | 2.058 | 0.0 | PASS |
| G3 | naive | 1.0 | 4.768 | 1.164 | 0.164 | 2.328 | 0.0 | FAIL |
| G3 | yours | 1.0 | 4.742 | 1.064 | 0.034 | 2.15 | 0.0 | PASS |
| G4 | naive | 1.0 | 13.764 | 1.004 | 0.004 | 2.008 | 0.0 | FAIL |
| G4 | yours | 1.0 | 5.684 | 1.013 | 0.002 | 2.069 | 0.0 | PASS |
| G5 | naive | 0.3699 | 5.359 | 17.03 | 16.03 | 2.124 | — | FAIL |
| G5 | yours | 0.8179 | 5.477 | 1.003 | 0.002 | 2.504 | — | PASS |
| G6 | naive | 0.517 | 4.836 | 12.344 | 11.344 | 2.009 | 0.0 | FAIL |
| G6 | yours | 1.0 | 6.099 | 1.053 | 0.017 | 2.202 | 0.0 | PASS |

`recovery (s)` = giây từ lúc provider hồi phục tới khi 95% call thành công trong cửa sổ 30 s (`—` = tape không có mốc phục hồi, G5).
Check naive trượt (theo `configs/scenarios.yaml`):

- G1 naive trượt: `availability_min, retry_after_violations_max, amplification_max`
- G2 naive trượt: `availability_min, amplification_max, recovery_s_max`
- G3 naive trượt: `retry_ratio_max`
- G4 naive trượt: `latency_p95_s_max`
- G5 naive trượt: `client_error_retries_max, availability_min`
- G6 naive trượt: `availability_min`

Client của tôi: **6/6 băng PASS** ở seed 25, 26, 27. Cost/turn của "yours" cao hơn naive ở G5/G6 chủ yếu vì traffic được chuyển sang `beta` (1,4/call, G6: cost/turn 2.202) thay vì thất bại không tốn tiền như naive (G5: sau t=300 account A hết quota → naive thất bại hàng loạt; client mới chuyển sang `beta`).
Cost/turn chia cho số lượt *thành công* nên không so sánh trực tiếp được khi availability khác nhau nhiều.

## 2. Cấu hình client và lý do

Mọi số "sweep" bên dưới là thay **một** tham số của cấu hình cuối, giữ nguyên các tham số khác, trên đúng tape nêu tên
(`reports/experiments.json` → `client_sensitivity`, seed 25). Cấu hình cuối: `configs/gameday.yaml` khối `client:`.

| Tham số | Giá trị | Vì sao (dựa trên băng nào, số liệu nào) |
|---|---:|---|
| attempt_timeout_s | 8.0 | User chờ tối đa 30 s; 8 s cho phép chịu 2 attempt treo liên tiếp (16 s) mà vẫn còn ~14 s cho provider thứ ba (G6: `alpha` 503, `alpha-eu` hang, rồi `beta`). Sweep 4/8/15 s: G6 availability 1.0/1.0/0.9958 (15 s bắt đầu mất lượt: `deadline` 8); 4 s cắt nhầm request chậm-nhưng-sống ở G4 (retry_ratio 0.007 so với 0.002, amplification 1.037 so với 1.013). |
| max_attempts_per_provider | 2 | 1 lần retry cùng provider rồi fail over. G3 (500 ngẫu nhiên 30%): xác suất cả hai attempt hỏng = 0,3² = 9%, nên 1 retry đủ cứu 91%. Sweep 1/2/4: G3 retry_ratio 0.0/0.034/0.021 (giới hạn 0,10); G2 giống hệt nhau giữa 2 và 4 (breaker + budget đã chặn). Với 1, mọi lỗi lẻ thành failover ngay (retry_ratio 0, `primary_share_after_restore` 0.996), tốn thêm một provider cho lỗi mà một retry rẻ hơn đã cứu được. |
| backoff_base_s / cap_s | 0,25 / 4,0 | Full jitter `U(0, min(cap, base·2^(n-1)))`. Với `max_attempts_per_provider = 2` chỉ dùng n = 1 → delay ≤ 0,25 s (≪ service median 1,2 s của alpha: retry nhanh nhưng đã phân tán). `cap` 4 s (≈ ½ timeout) chỉ là chặn trên khi ai đó tăng số attempt. Với `retry-after` thì delay = `retry_after + U(0, 0,25)`: **0** vi phạm `retry-after` trên G1 ở mọi seed 1–30. |
| retry_budget_ratio (+ min_per_s 0,5, max_tokens 20) | 0,1 | Retry ≤ ~10% request. G3 retry_ratio: ratio 0 → 0.019, 0,1 → 0.034, 0,5 → 0.041: ratio 0,1 cho đủ retry để cứu lỗi lẻ nhưng cách giới hạn 0,10 một biên ×3. Thí nghiệm 1 (mục 3) cho thấy giá trị thật của budget khi breaker không giúp được. `min_per_s` 0,5 cho service ít traffic vẫn retry được 1 lần / 2 s; `max_tokens` 20 = burst tối đa 20 retry (≈ 2,5 s traffic ở ~8 call/s) trước khi bị giới hạn theo ratio. |
| breaker.window_size / min_calls | 20 / 10 | Chỉ trip khi đã có 10 kết quả (~1,3 s traffic ở alpha, ~8 attempt/s). Với tỉ lệ lỗi nền 30% (G3) xác suất nhị thức P(≥10/20 lỗi) = 0.048 còn P(≥5/10 lỗi) = 0.150 → cửa sổ 10/5 trip nhầm gấp ~3 lần. Sweep 10/5, 20/10, 50/25: G2 p95 4.979/4.958/5.259 s và `primary_share_after_restore` 0.991 ở 50/25 (phản ứng chậm: phải gom 25 kết quả); G3 amplification 1.031/1.064/1.136. Chênh lệch nhỏ — 20/10 là điểm giữa giữa "nhạy" và "ổn định". |
| breaker.failure_rate_threshold | 0,5 | G2/G6 (lỗi gần 100%) cho kết quả y hệt với 0,25–0,8. G3 (30% lỗi) là nơi ngưỡng có tác dụng: amplification 1.025 / 1.064 / 1.136 và retry_ratio 0.008 / 0.034 / 0.068 cho ngưỡng 0,25 / 0,5 / 0,8. 0,8 gần chạm trần retry_ratio 0,10 (breaker gần như không che chở). 0,5 = "đa số call trong cửa sổ hỏng", giữ biên ×3 so với trần; ở G3 breaker của `alpha` vẫn mở 5 lần trong 180 s brown-out (lỗi dồn thành cụm) nhưng đóng lại sau probe thành công (`primary_share_after_restore` 1.0). |
| breaker.slow_call_s (+ slow_rate_threshold 0,6) | 3,0 | G4 (không lỗi, chậm +5 s) chỉ bắt được qua latency: tắt (`1e9`) → p95 **13.765 s (FAIL ≤ 10)**; 3,0 → 5.684 s. Quá nhạy cũng hại: 2,0 s coi cả call bình thường của `alpha-eu`/`beta` là chậm → availability 0.9871, `no_provider_available` = 28. G2 p95 theo `slow_call_s` 5,0 / 3,0: **9.847 → 4.958 s** (hàng đợi dài làm call chậm 3–5 s trước khi có 529; breaker thấy sớm hơn). Đây là tham số tôi đổi so với starter (5,0) dựa trên kết quả 12 seed × 2 bộ tape: 0 trượt, p95 G2 trung bình 10,23 → 5,03 s. |
| breaker.open_duration_s | 10,0 | Đủ lâu để không "đập" provider đang chết, đủ ngắn để `recovery_s ≤ 30`. Sweep 2/10/30 s: G6 amplification 1.09/1.053/1.041 (2 s: probe vào `alpha-eu` đang hang tốn mỗi lần một timeout 8 s); G2 p95 5.245/4.958/5.017 s. 30 s vẫn PASS nhưng kéo dài thời gian quay lại primary khi sự cố ngắn (tệ nhất ≈ 30 s + probe, sát trần `recovery_s` 30). |
| breaker.half_open_max_probes (+ half_open_successes 2) | 2 | Mục đích là *không* thundering-herd. Sweep 1/2/10: G6 p95 5.782/6.099/11.527 s, G2 5.003/4.958/9.068 s — 10 probe đồng thời gần như gấp đôi p95 vì 10 request cùng đi vào provider vẫn hỏng. 2 probe + cần 2 thành công: một probe may mắn trên provider đang chập chờn không đủ để đóng breaker. |

Điều quan trọng của breaker còn là *chính xác về loại lỗi*: 400 / 429 không bao giờ tính vào breaker. Tape G5 (60% request malformed
trong 2 phút) cho `client_error_retries = 0` và `unneeded_failovers = 0` ở mọi seed 1–30, breaker của `alpha` không mở.

Sơ đồ quyết định của `on_error` (đúng như `src/gameday_lab/client.py`):

| Loại lỗi (`classify`) | Ghi breaker? | Retry cùng provider? | Failover? | Cooldown (dùng chung mọi call) |
|---|---|---|---|---|
| CLIENT_ERROR (400/401/403/404/422) | `release` — không ghi | **Không** | **Không** → `GiveUp("client_error")` | không |
| QUOTA_EXHAUSTED (429 `insufficient_quota`) | `release` | không | có, ngay (delay 0) | `quota_cooldown_s` = 300 s |
| RATE_LIMITED (429 khác) | `release` | không (spill-over thay vì chờ) | có, ngay | `now + retry_after` (mặc định 1 s nếu thiếu header) |
| OVERLOADED (503/529) | `on_failure` | có, nếu `tries < 2` **và** breaker chưa OPEN **và** retry budget còn token **và** vừa deadline (delay = full jitter) | có, khi hết một trong các điều kiện trên | không (breaker lo) |
| SERVER_ERROR (5xx khác) | `on_failure` | như OVERLOADED | như OVERLOADED | không |
| TIMEOUT (status 0 / 408) | `on_failure` | như OVERLOADED | như OVERLOADED | không |
| Hết ladder | — | — | chờ cooldown rate-limit ≤ 5 s nếu vừa deadline và breaker không OPEN; ngược lại `GiveUp("no_provider_available")` | — |

## 3. Ba thí nghiệm (mỗi cái 3–5 câu + số)

Tất cả chạy bằng `python scripts/run_experiments.py`: cấu hình/subclass chỉ nằm trong bộ nhớ của script đó; `src/` và `configs/` không bị sửa.

### 3.1 Retry budget là lớp phòng thủ cuối

Làm breaker "hỏng" bằng `breaker.min_calls: 1000000000` và `max_attempts_per_provider: 5` (theo template), rồi chạy G2, G3 hai lần: (a) giữ retry budget;
(b) tắt budget bằng `retry_budget_ratio: 100`, `retry_budget_max_tokens: 1.0e9`, `retry_budget_min_per_s: 1.0e6`.

| Băng | Cấu hình | availability | p95 (s) | amplification | retry_ratio | recovery (s) | give_up | check |
|---|---|---:|---:|---:|---:|---:|---|---|
| G2 | cấu hình cuối (reference) | 1.0 | 4.958 | 1.013 | 0.003 | 0.0 | {} | PASS |
| G2 | breaker hỏng + budget | 0.9987 | 19.149 | 1.379 | 0.057 | 0.0 | {'deadline': 3} | PASS |
| G2 | breaker hỏng, không budget | 0.975 | 21.035 | 1.584 | 0.384 | 16.0 | {'deadline': 59} | PASS |
| G3 | cấu hình cuối (reference) | 1.0 | 4.742 | 1.064 | 0.034 | 0.0 | {} | PASS |
| G3 | breaker hỏng + budget | 1.0 | 4.565 | 1.136 | 0.068 | 0.0 | {} | PASS |
| G3 | breaker hỏng, không budget | 1.0 | 4.661 | 1.162 | 0.158 | 0.0 | {} | FAIL: retry_ratio_max |

Khi breaker mù, **budget một mình** giữ G2 ở retry_ratio 0.057 (so với 0.384 khi tắt: ×6.7),
số lượt chết vì `deadline` 3 so với 59, `recovery_s` 0.0 so với 16.0; ở G3, tắt budget đẩy retry_ratio lên
**0.158 (vượt trần 0,10 → FAIL)**, còn có budget là 0.068. Trung thực về mức độ: ở G2 amplification không-budget là
1.584 (vẫn dưới 1,6) vì mỗi provider chỉ cho 5 attempt, rate-limit 20 rps và hàng đợi 10 s tự cắt bớt, không như 36 attempt/call của naive (9,9× ở G2).
**Vì sao vẫn cần cả hai khi breaker đúng?** Breaker phản ứng *sau* khi cửa sổ đầy (≥ `min_calls`), theo từng provider và chỉ với ngưỡng đã chọn;
nó mở/đóng liên tục khi lỗi dao động: ở G3 với cấu hình cuối, breaker của `alpha` vẫn mở **5** lần và probe hỏng 5 lần
(`reports/experiments.json` → `g3_breaker_transitions`), tức là có những khoảng lỗi nằm *dưới* ngưỡng hoặc *trước* khi trip mà chỉ budget giới hạn retry.
Budget là cơ chế cục bộ, tức thời, không phụ thuộc vào việc phân loại lỗi hay chỉnh ngưỡng đúng; breaker bảo vệ provider, budget bảo vệ *chính hệ thống của mình* khỏi tự khuếch đại tải.

### 3.2 `attempt_timeout_s: 30`

| Băng | attempt_timeout_s | availability | p95 (s) | client_timeout | give_up_reasons | check |
|---|---|---:|---:|---:|---|---|
| G6 | 8 s (cuối) | 1.0 | 6.099 | 78 | {} | PASS |
| G6 | 30 s | 0.9488 | 5.344 | 122 | {'deadline': 106, 'no_provider_available': 16} | FAIL: availability_min |
| G4 | 8 s (cuối) | 1.0 | 5.684 | 1 | {} | PASS |
| G4 | 30 s | 1.0 | 5.608 | 0 | {} | PASS |

Nhìn **availability trước**: G6 rơi từ 1.0 xuống **0.9488 (FAIL ≥ 0,95)**, với 106 lượt chết vì `deadline` + 16 `no_provider_available`: một attempt vào `alpha-eu` (hang) giờ treo tới 30 s = toàn bộ deadline của user, không còn thời gian fail over.
p95 lại **giảm** (6.099 → 5.344 s) vì `latency_p95_s` chỉ tính trên các lượt *thành công*: những lượt treo/hết hạn bị loại khỏi mẫu (survivorship bias) — số p95 đẹp hơn trong khi sản phẩm tệ hơn.
G4 gần như không đổi (availability 1.0 → 1.0, p95 5.684 → 5.608) vì `alpha` ở G4 chỉ chậm thêm 5 s (≈ 1,2 + 5 ≈ 6 s/call theo cấu hình) nhưng vẫn *trả lời* trước 8 s: timeout gần như không kích hoạt (1 so với 0 timeout) — timeout chỉ quan trọng cho provider *treo*; provider chỉ chậm do breaker slow-call xử lý.
**Chọn timeout thế nào cho đúng:** (1) lấy p99 của latency lúc khỏe làm sàn (không được cắt request bình thường — sweep 4 s ở G4 làm retry_ratio tăng ×3,5); (2) lấy deadline của user chia cho số bước fail-over cần chịu được:
(deadline − thời gian cần cho provider khỏe) / (số provider có thể treo + 1) — ở đây (30 − ~2) / 3 ≈ 9 s → 8 s; (3) kiểm tra lại bằng tape có provider *hang*, không chỉ tape chậm.

### 3.3 Bỏ lọc tool calling khỏi `ladder()`

Subclass `ClientNoCapabilityFilter` (chỉ trong `scripts/run_experiments.py`) trả `list(self.order)` cho mọi task; G6:

| Cấu hình | availability | incompatible_routes | give_up_reasons | attempts: beta / gamma-mini | cost/turn |
|---|---:|---:|---|---|---:|
| có lọc (cuối) | 1.0 | 0 | {} | 2130 / 419 | 2.202 |
| không lọc | 0.9015 | **235** | {'incompatible_model_output': 235} | 1842 / 431 | 2.284 |

Nói với product manager: trong 5 phút `alpha` và `alpha-eu` sập và `beta` hạ rate limit, 235 lượt chat của khách (≈ 9.9% turn trong tape) được chuyển sang `gamma-mini` —
mô hình rẻ không có tool calling — cho bước *gọi tool* (tra đơn, khởi tạo hoàn tiền). Mô hình đó **trả lời một cách trôi chảy nhưng không thực hiện hành động**: khách tưởng đã được xử lý, thực tế không có tra cứu nào xảy ra.
Lỗi này tệ hơn một lỗi 5xx rõ ràng vì không ai biết cần thử lại. Availability tụt 1.0 → 0.9015, và đã tốn tiền cho 235 call vô ích.
Khi bị lọc, tool call ở G6 đi `alpha`/`beta` và vẫn đạt availability 1,0; sau thí nghiệm code/config thật không bị thay đổi.

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid (cents) | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.0 (500/500) | 81 | 128 | 81 | 0 | 1496700 | 1.123 |
| yours | 1.0 (500/500) | 66 | 0 | 0 | 0 | 0 | 0.303 |

(500 workflow, seed 25, `make workflows`; `yours` cũng PASS seed 26, 27 qua `grade.py`. `yours` chỉ có 500 lần thực thi payment thật cho 500 phiên.)

**Vì sao chỉ idempotency key là chưa đủ?** Key chỉ làm cho *một thao tác* an toàn khi gửi lại; nó không nhớ workflow đã đi tới đâu. Sau `WorkerCrash`, worker mới không có bộ nhớ, phải chạy lại từ `classify_request`:
tốn lại LLM call (key không che được các step không có side effect) và, nếu key sinh mới, hoàn tiền thêm lần nữa (naive không có key nào) — naive: 128 refund trùng, 14,967 đơn vị tiền chi thừa (`overpaid_cents` = 1,496,700), wasted LLM/crash 1.123 (> 0,6).
**Vì sao chỉ checkpoint là chưa đủ?** Có một cửa sổ nhỏ giữa "payment đã commit" và "checkpoint được ghi": `ServiceTimeout` (response mất) hoặc `WorkerCrash` rơi đúng vào đó.
Không có key ổn định, lần chạy lại không phân biệt được "chưa làm" với "đã làm nhưng chưa ghi" → gọi lại payment → hoàn tiền trùng. Key ổn định `refund-agent/<session>/<step>` biến lần gọi lại thành thao tác trả về kết quả cũ (idempotent), checkpoint cho phép bỏ qua các step đã xong.
**Điều gì xảy ra nếu ghi checkpoint *trước* khi gọi payment?** Nếu worker chết sau khi ghi "issue_refund = done" nhưng trước khi payment chạy, lần resume thấy checkpoint và *bỏ qua* step → tiền **không bao giờ được hoàn** (`lost_refunds > 0`) trong khi bước email lại dùng `state['issue_refund']['refund_id']` không tồn tại. Vì vậy thứ tự đúng:
*chạy step → (thành công) → mới ghi checkpoint*; hậu quả lệch thứ tự duy nhất là chạy lại step đó, mà idempotency key làm vô hại.

## 5. Alerting & error budget

| Sự cố | Mong đợi | Naive alerter (5 phút > 5%) | Burn-rate alerter | Độ trễ phát hiện (naive / burn-rate, phút) |
|---|---|---|---|---:|
| checkout_bug | page | page +1 phút | page +27 phút | 1 / 27 |
| provider_outage | page | page +0 phút | page +4 phút | 0 / 4 |
| deploy_blip | none | **page nhầm** | không page ✓ | — / — |
| slow_leak | ticket | **không phát hiện** | ticket +1337 phút | — / 1337 |
| degraded_evening | page | page +214 phút | page +291 phút | 214 / 291 |
| night_spike | none | **page nhầm** | không page ✓ | — / — |
| small_bump | none | **page nhầm** | không page ✓ | — / — |

Nguồn: `reports/slo.json` (`make slo`). Burn-rate alerter: 3 page, 1 ticket, **0 false page** (naive: 7 page, 0 ticket, 3 false page, và **bỏ sót** `slow_leak`).
Ở `degraded_evening` (lỗi 4% < ngưỡng 5%) naive chỉ page khi dao động ngẫu nhiên của một cửa sổ 5 phút vượt 5% — trễ 214 phút, không đáng tin.

**Error budget 30 ngày** (`error_budget_report` trên `data/sli_30d.csv`): 25,901,755 request, cho phép 129,508.8 request lỗi (0,5%), thực tế 55,618 → availability 0.997853.
**Đã tiêu 42.95%, còn 57.05%. Không đóng băng release** (`freeze_releases = False`: chỉ đóng băng khi còn ≤ 0%).
Lớn nhất là `slow_leak` (25,936 lỗi ≈ 20.0% budget): rò rỉ chậm, đúng loại cần ticket chứ không cần page.

**`small_bump` (20 phút ở 12% lỗi) vì sao không nên đánh thức ai lúc 11 giờ trưa?** Nó chỉ tiêu 1,794 request lỗi ≈ **1.39% budget tháng**; burn rate của cửa sổ 1 giờ ≈ 12% × 20/60 / 0,5% ≈ 8× (< 14,4×) và của cửa sổ 6 giờ ≈ 1,3× (< 6×),
tức là ở nhịp đó phải mất vài ngày mới cạn budget — không có gì cần làm *ngay* lúc 11 giờ; nó tự hết và để lại vết trong dashboard/ticket. Page chỉ nên gọi khi budget bị đốt đủ nhanh để người trực thực sự cứu được (14,4× → cạn 2% budget trong 1 giờ).
Page dư làm on-call mất tin vào alert (alert fatigue) — naive page 3 lần nhầm (`deploy_blip`, `night_spike`, `small_bump`).

## 6. Postmortem — Băng G2 với client naive (blameless)

*Hình: `reports/gameday/G2_overload_storm.png` (`make plot`; trái = naive, phải = resilient). Dữ liệu: `reports/gameday/naive_G2_overload_storm_timeseries.csv`.*

**Tóm tắt (3 câu):** Lúc t=120 s `alpha` mất 75% GPU trong 180 s. Client v1 (3 tầng retry xếp chồng, tối đa 36 attempt/call, delay cố định, không jitter/budget/breaker) khuếch đại tải lên
~18× bình thường, và hệ thống không có lượt thành công nào từ t=137 tới t=452 — kéo dài thêm ~153 s *sau khi* provider đã hồi phục lúc t=300.
Client mới (phải hình) giữ availability 1.0 trên cùng tape.

**Ảnh hưởng:** 1,285/2,362 lượt user thất bại (54.4%; availability 0.456); không có lượt thành công nào trong ~316 s liên tục.
Nếu tháng chỉ có sự cố này và traffic bằng đúng tape (4 turn/s ≈ 10,368,000 turn/tháng, budget 0,5% = 51,840 lượt lỗi) thì sự cố đã ăn **2.48%** error budget tháng
(với khối lượng 25,9 triệu request của `sli_30d.csv`: 0.99%); tốc độ đốt trong tape = 109× (ngưỡng page nhanh là 14,4×).

**Timeline** (giây ảo — số lấy trực tiếp từ CSV; "call thành công / call kết thúc" là `calls_ok` / `calls_done` cộng theo khoảng):

| t | Sự kiện | Bằng chứng (số) |
|---:|---|---|
| 0–119 | Bình thường | 7.5 attempts/s; 895/895 call thành công (100%) |
| 120 | `alpha` mất 75% năng lực (capacity ×0,25: ~15 rps → ~3,75 rps) | t=120–124: 6.0 attempts/s, 12/12 thành công — hàng đợi còn hấp thụ được |
| 125–139 | Hàng đợi đầy, 529 và timeout bắt đầu; retry chồng lên | 36.7 attempts/s; 39/39 call thành công; call thành công cuối cùng ở t=136 |
| 140–150 | Bão retry: attempt tăng vọt, thành công về 0 | 214.2 attempts/s; 0/47 call thành công; **đỉnh 254 attempts/s tại t=143** (34× bình thường) |
| 150–299 | Tải duy trì ~18× bình thường dù lượng *call mới* vẫn chỉ ~8/s | 146.5 attempts/s; 0/631 call thành công; cả giai đoạn 120–300: 137.2 attempts/s so với 7.5 ban đầu |
| 300 | **`alpha` hồi phục hoàn toàn** (capacity ×1) | t=300–319: 27.2 attempts/s; 0/28 call thành công — hệ thống *không* phục hồi |
| 320–359 | Retry giảm nhưng 0 thành công | 15.8 attempts/s; 0/141 call thành công |
| 360–399 | Làn sóng retry thứ hai | 106.2 attempts/s; 0/175 call thành công |
| 400–439 | Vẫn 0 thành công | 50.0 attempts/s; 0/158 call thành công |
| 453 | Lượt thành công đầu tiên sau 316 s | t=440–459: 13.4 attempts/s; 45/97 call thành công; `recovery_s` = 155.0 (mốc 95% = t=455) |
| 460–479 | Phục hồi hẳn | 10.4 attempts/s; 254/262 call thành công |

Tổng cộng: 34,475 attempt cho 3,481 call (**9.904×**; mọi attempt đều đi vào `alpha`). Lỗi: 26,298 lần 429 (82% số lỗi),
3,194 lần 529, 2,737 timeout phía client.

**Trigger vs root cause.**
*Trigger* (kích hoạt): `alpha` mất 75% GPU trong 3 phút (t=120–300) — một sự cố nhà cung cấp bình thường, ngắn và tự hết. *Root cause* (nguyên nhân gốc): thiết kế retry của chính chúng ta — 3 tầng retry xếp chồng
(app × gateway × SDK = 36 attempt/call), delay cố định 0,2 s không jitter, không `retry-after`, không retry budget, không circuit breaker, không fail over, không nhận biết deadline — biến một sự cố 180 s thành 316 s không có lượt thành công, trong đó
~153 s xảy ra *sau* khi nguyên nhân kích hoạt đã biến mất.

**Vì sao provider đã hồi phục lúc t=300 mà hệ thống vẫn chưa phục hồi (metastable failure)?** Vòng lặp tự duy trì: (1) khi `alpha` chậm, các call timeout sau 8 s nhưng **server vẫn tiếp tục xử lý request đó** (công sức bị phí); (2) client không dừng mà retry ngay
(0,2 s, tối đa 36 lần), nên mỗi call đẻ thêm attempt: ~18× tải trong khi nhu cầu thật không đổi; (3) hàng đợi của `alpha` luôn đầy request *mà client đã bỏ đi* — chúng vẫn chiếm 18 server (mỗi request ~1,2 s ⇒ năng lực khỏe ≈ 15 req/s) trong khi mọi attempt mới phải chờ gần 10 s (ngưỡng shed 529)
nên lại timeout ở 8 s; (4) rate limit của tenant là 20 req/s — *cao hơn* năng lực khỏe 15 req/s — nên dù provider đã hồi phục, lượng retry được chấp nhận vẫn lớn hơn khả năng phục vụ và hàng đợi không bao giờ xả hết; phần còn lại bị 429 (chiếm 82% lỗi), mỗi 429 lại sinh thêm một lần retry.
Tải của chính chúng ta, không phải provider, duy trì sự cố: chỉ khi các call cũ hết 36 attempt/bỏ cuộc và lượng retry chạm dưới năng lực (t≈453), hàng đợi mới xả và hệ thống phục hồi. (Làn sóng thứ hai ở t=360–399 phù hợp với việc những call mới bắt đầu từ t≈300 cũng bước vào chuỗi retry riêng — đây là suy luận từ cơ chế, không phải số đo trực tiếp.)

**Điều gì giúp / điều gì làm tệ hơn:** *Giúp:* rate limit 429 trả lỗi nhanh (0,05 s, không chiếm server), ngưỡng shed 529 ở 10 s chặn hàng đợi vô hạn, và tải thật chỉ ~8 req/s nên khi retry cạn thì phục hồi rất nhanh (từ 45/97 call thành công sang 254/262 call thành công trong 20 s).
*Làm tệ hơn:* retry 3 tầng (36×), delay cố định (các client đồng bộ, không có jitter), bỏ qua `retry-after`, mọi attempt dồn vào một provider duy nhất dù `alpha-eu`/`beta` còn năng lực, không có breaker/budget nên không có "van xả", không biết deadline 30 s của user nên vẫn đốt attempt cho lượt user đã bỏ đi.

**Action items** (cụ thể, có owner, đo được; không quy lỗi cho cá nhân — gốc rễ là thiếu cơ chế bảo vệ ở tầng thiết kế và quy trình):

| # | Hành động | Loại (prevent / detect / mitigate) | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Gộp 3 tầng retry thành **đúng 1 tầng** ở client: full jitter, tôn trọng `retry-after`, retry budget 10% (`retry_budget_ratio: 0.1`), tối đa 2 attempt/provider; tắt retry ở gateway và SDK | Prevent | Platform / LLM-gateway team | CI chạy tape G2 (và G1, G3): `amplification ≤ 1,2` (hiện 1.013; naive 9.904), `retry_ratio ≤ 0,10`; fail build nếu vượt |
| 2 | Circuit breaker sliding-window + fallback ladder có kiểm tra khả năng (tool → chỉ provider có tool calling) và cooldown dùng chung cho 429 | Mitigate | Platform / LLM-gateway team | Replay G2: `availability ≥ 0,95` (hiện 1.0), `recovery_s ≤ 30` (hiện 0.0), `primary_share_after_restore ≥ 0,8` (hiện 1.0) trong CI |
| 3 | Cảnh báo theo **burn-rate đa cửa sổ** (14,4×/1 h & 5 m, 6×/6 h & 30 m) và thêm cảnh báo *amplification* (attempt/call > 1,5 trong 1 phút) + tỉ lệ 529/timeout theo provider, để phát hiện bão retry từ phút đầu | Detect | SRE / On-call | Replay tape G2 naive và xác nhận page nhanh trong ≤ 5 phút sau t=120 (so với 316 s không có lượt thành công); chỉ số: thời gian từ trigger tới page (MTTD) trong game day hằng quý; 0 false page trên `sli_30d.csv` |
| 4 | Propagate **deadline** của user xuống provider/gateway và hủy request đã bị client bỏ (cancel-on-disconnect) + load shedding theo deadline, để hàng đợi không chứa "công việc ma" | Prevent / Mitigate | Provider-gateway team | Trong mô phỏng phục hồi: tỉ lệ request xử lý sau khi client đã timeout < 5% và `recovery_s ≤ 30` kể cả khi tắt breaker của client (kiểm tra bằng tape G2 với client naive đã bật cancel) |
| 5 | Game day định kỳ: chạy 6 tape trong CI mỗi PR đổi `client:`; runbook "bão retry": tắt retry tầng dưới, hạ tenant rate limit cho tới khi hàng đợi xả | Prevent / Mitigate | SRE / Eng manager | `make compare` xanh 6/6 trong CI; diễn tập quý có ghi lại `recovery_s` |

## 7. Một điểm yếu còn lại

**Provider *treo* (hang) vẫn tốn một timeout đầy đủ cho mỗi request tới khi breaker mở.** Ở G6, `alpha-eu` hang: client ghi nhận 78 `client_timeout` (mỗi cái 8 s)
trước khi các breaker ngăn được; p95 của G6 là **6.099 s** so với 4.78/4.742 s ở G1/G3, và `cost/turn` 2.202 so với 2.104 ở G1 vì `beta` (1,4/call) gánh tải
(`attempts_by_provider`: alpha 2398, alpha-eu 78, beta 2130, gamma-mini 419). Ngoài ra, mỗi probe HALF-OPEN vào provider đang hang cũng tốn một timeout 8 s (sweep `open_duration_s` = 2 s làm G6 amplification tăng lên 1.09).
**Cách sửa:** (a) timeout thích nghi theo từng provider — ví dụ `min(8, 3 × p99 gần nhất)` — để request treo bị cắt sau ~3–4 s khi provider vốn trả lời trong ~1 s; (b) *hedged request*: nếu chưa có phản hồi sau p95, gửi song song sang provider kế tiếp và lấy kết quả đầu tiên, tính hedge vào cùng retry budget để không tạo amplification mới;
(c) health-check chủ động bằng request rẻ để probe HALF-OPEN không dùng traffic của user. **Đánh đổi:** hedge/timeout ngắn làm tăng chi phí và amplification (trần là 1,6), timeout thích nghi có thể cắt nhầm khi p99 tạm thời thấp, và health-check tạo thêm tải nền; cần đo lại bằng G4 (chậm nhưng sống) để chắc chắn không cắt nhầm provider chỉ chậm.

## 8. Cache (Part G)

Số từ `reports/cache/*.json` (`make cache`, seed 25) và `reports/experiments.json`.

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0.8373 | 0.8424 | 0.0 | 0 | 0 | 0 | 1.386 | FAIL |
| cached (của bạn) | 0.9124 | 0.9645 | 0.652 | 157 | 0 | 3 | 0.915 | PASS |

Không cache trượt `faq_availability_min, cache_hit_ratio_min`. Cache giữ `availability` tổng (0.9124) thấp hơn `faq_availability` (0.9645) vì
1088 lượt không phải FAQ (cần tool call) không thể phục vụ từ cache: chỉ 903/1088 (83.0%) thành công, đúng như FAQ trong README.
Cấu hình cuối cũng PASS seed 26 (`faq_availability` 0.9563, hit 0.656, outdated 2) và 27 (0.9638, 0.653, 2).

| Tham số `cache:` | Giá trị | Vì sao (số liệu nào) |
|---|---:|---|
| similarity_threshold | 0,92 | Trên catalog FAQ, cặp "gần mà khác" cao nhất là refund_policy vs refund_time = **0.862** (kế tiếp: payment_methods vs cod 0.846, shipping_fee_city vs shipping_fee_province 0.841), trong khi hai cách diễn đạt của *cùng* câu hỏi thấp nhất là **0.951**. Ngưỡng nằm trong khoảng trống 0,862–0,951: 0,92 cách mức nhầm cao nhất 0,058 và cách mức "cùng ý" thấp nhất 0,031. 0,80 → 157 câu sai (`other_question`); 0,97 loại luôn nhiều paraphrase thật (hit 0.581 so với 0.652). |
| ttl_s | 60 | Thay đổi *không báo trước* (phí ship ở t=480) chỉ bị giới hạn bởi tuổi entry. `outdated_answers` theo TTL 30/60/300: 2/3/**95** (trần 15; TTL 300 FAIL). 60 giữ biên ×5 so với trần; 30 vẫn PASS nhưng hit giảm 0.592 (so với 0.652) và cost/turn tăng 0.955 (so với 0.915). |
| max_stale_s | 300 | Sự cố trong C1 dài 120 s (t=240–360). Stale-if-error cần ≥ độ dài sự cố: 0 → `faq_availability` 0.8733 (FAIL < 0,93); 120 → 0.9599; 300 → 0.9645. Chọn 300 (biên ×2,5 so với sự cố trong tape, thay vì đúng 120) vì stale chỉ được dùng khi *mọi provider bỏ cuộc* và không đổi `outdated_answers` (cùng 3). |
| max_entries | 500 | Catalog có 18 ý hỏi dùng chung; vì các paraphrase của cùng một ý (≥ 0,951) vượt ngưỡng 0,92 nên được *refresh* chứ không chồng thêm, còn các ý khác nhau (≤ 0,862) thì không gộp: tối đa 18 entry mỗi phiên bản prompt. 500 chỉ là chặn trên bộ nhớ, LRU không phải loại entry nào trong C1. |

Cấu hình ban đầu của starter (0,80 / 600 / 0) với cache đã cài đặt đúng cho: hit 0.742, `wrong_answers` **181** {'other_question': 181}, `outdated_answers` **80**,
`faq_availability` 0.8587 — trượt cả 3 check ngoài hit ratio.

### Thí nghiệm (mỗi cái 2–4 câu + số)

**1. Ngưỡng** (TTL 60, stale 300):

| similarity_threshold | hit ratio | faq_availability | stale_served | wrong_answers | outdated | cost/turn | check |
|---|---:|---:|---:|---|---:|---:|:---:|
| 0,80 | 0.666 | 0.8733 | 152 | 157 {'other_question': 157} | 1 | 0.965 | FAIL |
| 0,92 (cuối) | 0.652 | 0.9645 | 157 | 0  | 3 | 0.915 | PASS |
| 0,97 | 0.581 | 0.964 | 153 | 0  | 4 | 0.964 | PASS |

Ở 0,80, **toàn bộ 157 câu sai là `other_question`** — cache nhầm các cặp "gần mà khác" (ví dụ *chính sách hoàn tiền* ↔ *bao lâu thì nhận tiền hoàn* cos 0.862; *COD* ↔ *các hình thức thanh toán* 0.846; *phí ship nội thành* ↔ *đi tỉnh* 0.841),
tức khách hỏi thời gian hoàn tiền nhận câu trả lời về điều kiện hoàn tiền. 0,97 an toàn nhưng bỏ phí hit (-7.1 điểm %) và tăng cost/turn lên 0.964.

**2. TTL** (ngưỡng 0,92, stale 300):

| ttl_s | hit ratio | faq_availability | stale_served | wrong_answers | outdated | cost/turn | check |
|---|---:|---:|---:|---|---:|---:|:---:|
| 30 | 0.592 | 0.9645 | 192 | 0  | 2 | 0.955 | PASS |
| 60 (cuối) | 0.652 | 0.9645 | 157 | 0  | 3 | 0.915 | PASS |
| 300 | 0.731 | 0.964 | 68 | 0  | 95 | 0.863 | FAIL |

Webhook chỉ có ở `policy/refund` (t=150, `on_content_update` → invalidate, `ignored_invalidation = 0`). Việc đổi phí ship ở t=480 **không có webhook**, nên cache không có cách nào biết; thứ duy nhất giới hạn số câu "lỗi thời" là tuổi tối đa của entry — TTL.
TTL 300 để lại entry cũ phục vụ tới 5 phút sau khi đổi (95 câu lỗi thời), TTL 60 chỉ 3. TTL dài hơn đổi lấy hit ratio cao hơn (+7.9 điểm %), nhưng vượt trần 15.

**3. Stale-if-error** (ngưỡng 0,92, TTL 60):

| max_stale_s | hit ratio | faq_availability | stale_served | wrong_answers | outdated | cost/turn | check |
|---|---:|---:|---:|---|---:|---:|:---:|
| 0 | 0.561 | 0.8733 | 0 | 0  | 3 | 0.975 | FAIL |
| 120 | 0.648 | 0.9599 | 149 | 0  | 3 | 0.918 | PASS |
| 300 (cuối) | 0.652 | 0.9645 | 157 | 0  | 3 | 0.915 | PASS |

Với `max_stale_s = 0`, mọi FAQ trong cửa sổ sập 120 s mà entry đã quá TTL đều thất bại: `faq_availability` **0.9645 → 0.8733** (FAIL), stale_served 157 → 0. Stale không làm tăng câu sai: `wrong_answers` vẫn 0 vì stale vẫn qua bộ lọc scope/invalidation.

**Điều tra `wrong_answers_by_reason`:** cấu hình cuối cho `wrong_answers = 0` ở cả 5 loại lỗi mà simulator phân biệt (`other_question`, `other_user`, `personal_cached`, `old_prompt`, `ignored_invalidation`). Để chắc rằng từng cơ chế *thực sự* cần thiết, tôi bỏ riêng từng cơ chế (ablation trong `scripts/run_experiments.py`, ngưỡng/TTL/stale cuối):

| Bỏ cơ chế | wrong_answers | theo lý do |
|---|---:|---|
| scope theo `prompt_version` | 31 | {'old_prompt': 31} (deploy prompt v2 ở t=420 vẫn phục vụ câu của v1) |
| webhook `on_content_update` | 22 | {'ignored_invalidation': 22} (chính sách hoàn tiền đổi ở t=150) |
| luật "không cache câu hỏi cá nhân" | 368 | {'other_user': 367, 'personal_cached': 1} (lộ đơn hàng/điểm của người khác) |
| ngưỡng 0,92 → 0,80 | 157 | {'other_question': 157} |

### Trả lời

- **Vì sao câu hỏi cá nhân ("Đơn #48213 của tôi đang ở đâu?") không được cache, kể cả khi cache theo từng user?** (1) Embedding của hai câu hỏi cá nhân khác nhau chỉ ở số đơn nên giống nhau ~0,99 — vượt mọi ngưỡng hợp lý — nên lookup theo ngữ nghĩa không thể phân biệt "đơn #123" và "đơn #124": cache chung sẽ lộ dữ liệu của người khác
  (ablation: **368 câu sai, 367 là `other_user`**). (2) Ngay cả cache riêng theo user cũng sai: trạng thái đơn/tiền hoàn/điểm thay đổi theo từng phút (không qua một tài liệu CMS nào có webhook để invalidate),
  nên câu trả lời cũ là *sai về nội dung* — tệ hơn cả không trả lời (`personal_cached` trong simulator); (3) stale-if-error không áp dụng được: "đơn của tôi đang ở đâu" đã cũ vài phút là thông tin gây hại. Chỉ cache nội dung dùng chung, có nguồn tài liệu để invalidate và có TTL.
- **Trong lúc mọi provider sập, dashboard vẫn xanh nhờ cache — alert dựa trên số nào?** Phải đo *sức khỏe provider*, không phải sức khỏe phía user: (a) tỉ lệ thành công/lỗi của lớp *client → provider* (bỏ qua cache hit): ở C1, 100% attempt tới provider lỗi trong t=240–360 trong khi `faq_availability` nhìn còn đẹp;
  (b) **`stale_served` rate** và tỉ lệ `Serve(stale=True)`/FAQ (> 0 kéo dài = đang sống bằng đồ cũ; ở C1 `stale_served = 157`); (c) trạng thái breaker (số provider ở OPEN, thời gian OPEN) và `no_provider_available`/`GiveUp`;
  (d) availability của *traffic không cache được* (tool call/câu cá nhân): ở C1 chỉ **83.0%** trong khi tổng thể 0.9124; (e) canary/synthetic call bỏ qua cache định kỳ mỗi 30–60 s. SLO của người dùng (có cache) và SLO của provider (không cache) phải tách riêng, và burn-rate alert chạy trên SLI không cache để cache không che mất sự cố.

## 9. Ghi chú nộp bài và giới hạn

- **Kiểm chứng:** `make test` (82 test), `make lint` (ruff), `make baseline compare workflows slo cache plot`, `python scripts/grade.py --seeds 25,26,27` đều chạy thành công trong môi trường Cloud của phiên làm việc sau `pip install -e ".[dev,plot]"` (chưa thử trên một máy sạch riêng biệt). File bị cấm sửa (`sim/`, `naive_client.py`, `workflows/{services,runner,naive_executor}.py`, `slo/{data,scoring}.py`, `configs/scenarios*.yaml`, `tests/`) không đổi (so sánh sha256 trước/sau).
- **Trường `Commit:` ở đầu report** là commit chứa code + cấu hình + artifact (`reports/` trừ `REPORT.md`); `REPORT.md` được commit ngay sau đó vì một commit không thể chứa hash của chính nó.
- **Điểm tự động cục bộ 84.0/88** — thiếu 4 điểm `slo_hidden` (giảng viên chấm bằng dữ liệu ẩn). Đây không phải là kết quả của bộ tape ẩn thật, chỉ là các tape public + các biến thể do tôi tự dựng.
- **Điều chỉnh so với starter:** `slow_call_s` 5,0 → 3,0 và khối `cache:` (0,80/600/0 → 0,92/60/300). Phần còn lại của khối `client:` giữ giá trị starter vì sweep ở mục 2 cho thấy chúng đều nằm trong vùng PASS với biên an toàn.
- **Tên repo:** quy tắc README §8 là `Track3-Day25-<MSV>-<Họ-Và-Tên>` tức `Track3-Day25-2A202602849-Le-Duc-Hung`; repo hiện tại có tên `K4-L3L4-Track3-Day25-LeDucHung-2A202602849-Circuit-Breakers-Caching-Reliability`. Tôi không có công cụ để đổi tên repo từ phiên làm việc này nên chưa đổi.
