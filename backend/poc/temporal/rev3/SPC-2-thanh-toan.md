---
id: SPC-2
title: Luồng thanh toán đơn hàng
owner: Trần Quốc Bảo
status: APPROVED
version: 3
---
# 1. Tổng quan

Spec này mô tả luồng thanh toán một đơn hàng qua cổng VNPay. Đơn hàng chuyển trạng thái
`PENDING → PAID` chỉ khi nhận được IPN hợp lệ từ cổng thanh toán; redirect của trình duyệt không bao giờ là bằng chứng
thanh toán.

## 1.1 Các bên tham gia

- Người mua (role `member`).
- Dịch vụ Order (sở hữu bảng `orders`).
- Dịch vụ Payment (sở hữu bảng `payment_transactions`).
- Cổng VNPay (bên ngoài).

# 2. API

## 2.1 POST /api/v1/payments/checkout

Tạo một giao dịch và trả về URL thanh toán VNPay. Yêu cầu đăng nhập (xem SPC-1).

| Thuộc tính | Giá trị |
|---|---|
| Auth | Bearer access token |
| Bảng đọc | `orders`, `users` |
| Bảng ghi | `payment_transactions` |
| Idempotency | Header `Idempotency-Key` bắt buộc |

```json
{
  "order_id": "ORD-2026-000123",
  "return_url": "https://app.example.com/orders/ORD-2026-000123"
}
```

## 2.2 POST /api/v1/payments/vnpay/ipn

Endpoint nhận IPN từ VNPay. Kiểm tra chữ ký HMAC-SHA512 trước mọi xử lý.

| Bước | Hành động | Bảng |
|---|---|---|
| 1 | Kiểm tra chữ ký `vnp_SecureHash` | — |
| 2 | Tìm giao dịch theo `vnp_TxnRef` | `payment_transactions` |
| 3 | So khớp số tiền với `orders.total_amount` | `orders` |
| 4 | Cập nhật `payment_transactions.status = SUCCEEDED` | `payment_transactions` |
| 5 | Cập nhật `orders.status = PAID` | `orders` |
| 6 | Cộng điểm thưởng `users.reward_points` | `users` |

# 3. Quy tắc nghiệp vụ

## 3.1 Chống xử lý trùng

IPN có thể đến nhiều lần. Bước 4–6 chạy trong một transaction và chỉ khi `payment_transactions.status = PENDING`:

```sql
UPDATE payment_transactions
   SET status = 'SUCCEEDED', paid_at = now()
 WHERE id = :payment_id
   AND status = 'PENDING'
RETURNING order_id, amount;
```

Nếu câu lệnh không cập nhật dòng nào, IPN là bản lặp và hệ thống trả `RspCode = 02` cho VNPay mà không làm gì thêm.

## 3.2 Điểm thưởng

Mỗi 10.000 VND thanh toán thành công cộng 1 điểm vào `users.reward_points`. Hoàn tiền trừ lại điểm tương ứng.
