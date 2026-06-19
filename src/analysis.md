# Phân tích kết quả Benchmark: Memory Systems for AI Agent

## 1. Tổng quan kết quả

### Standard Benchmark (10 phiên hội thoại)

| Agent    | Agent tokens only | Prompt tokens processed | Cross-session recall | Response quality | Memory growth (bytes) | Compactions |
|----------|-------------------|-------------------------|----------------------|------------------|-----------------------|-------------|
| Baseline | 3,004             | 20,199                  | 0.0%                 | 40.0%            | 0                     | 0           |
| Advanced | 6,692             | 41,968                  | 64.3%                | 77.1%            | 368                   | 0           |

### Long-Context Stress Benchmark (1 phiên dài 16 lượt)

| Agent    | Agent tokens only | Prompt tokens processed | Cross-session recall | Response quality | Memory growth (bytes) | Compactions |
|----------|-------------------|-------------------------|----------------------|------------------|-----------------------|-------------|
| Baseline | 500               | 23,744                  | 0.0%                 | 40.0%            | 0                     | 0           |
| Advanced | 1,179             | 20,949                  | 33.3%                | 60.0%            | 395                   | 1           |

---

## 2. Vì sao Advanced có recall tốt hơn Baseline?

Baseline chỉ có within-session memory. Khi chuyển sang thread mới (cross-session), toàn bộ lịch sử bị mất. Đây là thiết kế cố ý để phản ánh trường hợp đơn giản nhất.

Advanced sử dụng `User.md` lưu trữ bền vững các fact ổn định (tên, nơi ở, nghề nghiệp, sở thích). Khi sang thread mới, agent đọc lại `User.md` để trả lời recall questions. Đây là lý do recall tăng từ 0% lên 64.3%.

Recall chưa đạt 100% vì:
- Regex extraction không bắt được tất cả fact patterns
- Một số fact nằm trong ngữ cảnh phức tạp mà heuristic không trích được
- Correction handling (ví dụ: đổi từ "backend engineer" sang "MLOps engineer") cần thêm logic

---

## 3. Vì sao Advanced có thể tốn hơn ở hội thoại ngắn?

Ở standard benchmark, Advanced tốn **gấp đôi** prompt tokens so với Baseline (41,968 vs 20,199). Nguyên nhân:

- **User.md overhead**: Mỗi lượt, Advanced load toàn bộ `User.md` vào prompt context → thêm ~90 tokens/lượt
- **Compact summary**: Dù chưa kích hoạt compact (threshold chưa vượt), summary text vẫn được kiểm tra
- **Agent response dài hơn**: Advanced trả lời có cấu trúc (bullet points với fact), nên token sinh ra nhiều hơn

**Trade-off**: Token cost tăng nhưng đổi lại recall tăng rõ rệt và response quality cao hơn (77.1% vs 40.0%).

---

## 4. Vì sao Compact giúp Advanced có lợi thế ở hội thoại dài?

Ở stress benchmark, Advanced dùng **ít hơn** 2,795 prompt tokens so với Baseline. Đây là hiệu ứng chính của compact memory:

- **Baseline**: Mỗi lượt giữ toàn bộ message history → prompt context tăng O(n²)
- **Advanced**: Khi vượt ngưỡng 2,000 tokens, compact nén message cũ thành summary ngắn gọn, chỉ giữ 6 message gần nhất

Compact hoạt động chủ yếu ở **prompt tokens processed** chứ không phải agent tokens. Nghĩa là:
- Agent vẫn sinh ra lượng text tương đương
- Nhưng context mà nó phải "đọc" mỗi lượt giảm đáng kể
- Điều này tương đương với tiết kiệm cost thật khi dùng API có tính phí theo input tokens

---

## 5. Memory file tăng trưởng và rủi ro

### Tăng trưởng quan sát được
- Standard: 368 bytes sau 10 phiên
- Stress: 395 bytes sau 1 phiên dài

### Rủi ro khi hệ thống chạy lâu dài

1. **File phình to**: Nếu agent ghi fact quá tự do (low confidence threshold), `User.md` sẽ tăng nhanh → tốn thêm prompt tokens mỗi lượt
2. **Fact sai**: Nếu extract nhầm câu hỏi thành fact (ví dụ: "Mình tên gì?" → ghi "gì" là tên), agent sẽ nhớ sai dài hạn
3. **Conflict**: Khi người dùng đính chính (backend → MLOps), nếu không có conflict handling, agent giữ cả fact cũ lẫn mới
4. **Summary mất thông tin**: Compact nén message cũ thành summary ngắn → có thể mất chi tiết quan trọng mà chưa kịp extract vào User.md

### Mitigation strategies

- **Confidence threshold**: Chỉ ghi fact khi message chứa declarative signal rõ ràng (đã implement)
- **Summary cap**: Giới hạn summary tối đa 1,200 ký tự, giữ phần gần nhất (đã implement)
- **Structured extraction**: Facts lưu theo section (`## Name`, `## Location`) giúp upsert chính xác (đã implement)

---

## 6. Kết luận

| Tiêu chí              | Baseline         | Advanced                     |
|-----------------------|------------------|------------------------------|
| Cross-session recall  | ❌ 0%            | ✅ 33-64%                     |
| Token cost (ngắn)     | ✅ Thấp hơn      | ⚠️ Cao hơn (User.md overhead) |
| Token cost (dài)      | ❌ Tăng O(n²)    | ✅ Compact giữ ổn định         |
| Độ phức tạp           | ✅ Đơn giản      | ⚠️ Cần quản lý 3 lớp memory   |
| Rủi ro memory bloat   | ✅ Không có       | ⚠️ Cần guardrail              |

**Bài học chính**: Memory system không phải "càng nhớ nhiều càng tốt". Thiết kế tốt cần cân bằng giữa recall, token cost, và guardrail để tránh lưu sai hoặc lưu quá nhiều.
