---
id: SPC-3
title: Đăng ký tài khoản và email chào mừng
owner: Lê Thu Hà
status: APPROVED
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
| Bảng ghi | `email_outbox` |
| Bảng đọc | `email_templates` |
| Nhà cung cấp | Amazon SES (qua worker outbox) |

```json
{
  "template": "welcome_verify",
  "to": "ha.le@example.com",
  "variables": { "full_name": "Lê Thu Hà", "verify_url": "https://app.example.com/verify?t=..." }
}
```

API không gửi email trực tiếp: nó ghi một dòng vào `email_outbox` (trạng thái `QUEUED`); worker outbox gửi qua SES và
cập nhật trạng thái `SENT` hoặc `FAILED` (thử lại tối đa 3 lần).

# 3. Xác thực email

## 3.1 GET /api/v1/auth/verify

Khi người dùng bấm link, hệ thống kiểm tra token trong `email_verifications` (sống 24 giờ, dùng một lần), sau đó đặt
`users.status = ACTIVE` và `users.email_verified_at = now()`.

```python
async def verify(token: str) -> None:
    record = await verifications.consume(sha256(token))  # None nếu hết hạn hoặc đã dùng
    if record is None:
        raise InvalidVerificationToken()
    await users.activate(record.user_id, verified_at=now())
```
