---
id: SPC-3
title: Đăng ký tài khoản và email chào mừng
owner: Lê Thu Hà
status: APPROVED
version: 2
---
# 1. Tổng quan

Người dùng tự đăng ký tài khoản bằng email công ty. Sau khi tạo tài khoản, hệ thống gửi email xác thực kèm lời chào
mừng. Tài khoản chỉ đăng nhập được (SPC-1) khi email đã được xác thực.

# 2. API

## 2.1 POST /api/v1/auth/register

| Thuộc tính | Giá trị |
|---|---|
| Auth | Không |
| Bảng ghi | `users`, `email_verifications` |
| Gọi tiếp | POST /api/v1/notifications/email |

```json
{
  "email": "ha.le@example.com",
  "password": "********",
  "full_name": "Lê Thu Hà"
}
```

Chỉ chấp nhận email thuộc domain `example.com`. Tài khoản mới có `users.status = PENDING_VERIFICATION`.

## 2.2 POST /api/v1/notifications/email (API gửi mail)

API nội bộ của dịch vụ Notification, được API đăng ký gọi để gửi email chào mừng và link xác thực.

| Thuộc tính | Giá trị |
|---|---|
| Auth | Service token nội bộ |
| Bảng ghi | `notification_queue` |
| Bảng đọc | `email_templates` |
| Nhà cung cấp | Amazon SES (qua worker outbox) |

```json
{
  "template": "welcome_verify",
  "to": "ha.le@example.com",
  "variables": { "full_name": "Lê Thu Hà", "verify_url": "https://app.example.com/verify?t=..." }
}
```

API không gửi email trực tiếp: nó ghi một dòng vào `notification_queue` (trạng thái `QUEUED`); worker outbox gửi qua SES và
cập nhật trạng thái `SENT` hoặc `FAILED` (thử lại tối đa 3 lần).

# 3. Xác thực email

## 3.1 POST /api/v1/auth/verify-otp

Người dùng nhập mã OTP 6 số nhận qua email. Hệ thống kiểm tra mã trong `email_verifications` (sống 10 phút, sai tối đa
5 lần), sau đó đặt `users.status = ACTIVE` và `users.email_verified_at = now()`.

| Thuộc tính | Giá trị |
|---|---|
| Auth | Không |
| Bảng đọc | `email_verifications` |
| Bảng ghi | `users`, `email_verifications` |
