---
id: SPC-1
title: Luồng đăng nhập
owner: Nguyễn Minh Anh
status: APPROVED
---
# 1. Tổng quan

Spec này mô tả luồng đăng nhập bằng email và mật khẩu cho ứng dụng web nội bộ. Người dùng đăng nhập thành công nhận một
access token (JWT, sống 15 phút) và một refresh token (sống 7 ngày) lưu trong cookie HttpOnly.

## 1.1 Phạm vi

- Đăng nhập bằng email + mật khẩu.
- Khoá tài khoản tạm thời sau 5 lần sai liên tiếp.
- Ghi nhận thời điểm đăng nhập gần nhất vào bảng `users`.

Ngoài phạm vi: đăng nhập Google (xem SPC-6, chưa viết), quên mật khẩu.

# 2. API

## 2.1 POST /api/v1/auth/login

| Thuộc tính | Giá trị |
|---|---|
| Method | POST |
| Path | /api/v1/auth/login |
| Auth | Không |
| Rate limit | 10 request / phút / IP |
| Bảng đọc | `users` |
| Bảng ghi | `users`, `login_sessions` |

Request:

```json
{
  "email": "an.nguyen@example.com",
  "password": "********"
}
```

Response 200:

```json
{
  "access_token": "eyJhbGciOi...",
  "expires_in": 900,
  "user": { "id": "7b1e...", "email": "an.nguyen@example.com", "role": "member" }
}
```

## 2.2 Mã lỗi

| HTTP | error | Khi nào |
|---|---|---|
| 401 | INVALID_CREDENTIALS | Sai email hoặc mật khẩu |
| 423 | ACCOUNT_LOCKED | Đã sai 5 lần liên tiếp, khoá 15 phút |
| 429 | RATE_LIMITED | Vượt 10 request / phút |

# 3. Luồng xử lý

## 3.1 Kiểm tra mật khẩu

Mật khẩu được so sánh bằng Argon2id. Mỗi lần sai, `users.failed_login_count` tăng 1; đủ 5 lần thì đặt
`users.locked_until = now() + 15 phút`. Đăng nhập đúng thì đặt lại bộ đếm và cập nhật `users.last_login_at`.

```python
async def login(email: str, password: str) -> Session:
    user = await users.find_by_email(email)
    if user is None or not argon2.verify(user.password_hash, password):
        if user:
            await users.increment_failed_login(user.id)  # khoá khi đạt 5
        raise InvalidCredentials()

    if user.locked_until and user.locked_until > now():
        raise AccountLocked(until=user.locked_until)

    await users.mark_login(user.id, at=now())  # last_login_at, failed_login_count = 0
    return await sessions.create(user.id, ttl=timedelta(days=7))
```

## 3.2 Lưu phiên đăng nhập

Mỗi lần đăng nhập thành công tạo một dòng trong `login_sessions` (user_id, refresh_token_hash, expires_at, user_agent).
Refresh token chỉ lưu dạng hash SHA-256.
