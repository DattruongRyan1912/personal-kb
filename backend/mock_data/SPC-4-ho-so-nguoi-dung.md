---
id: SPC-4
title: Quản lý hồ sơ người dùng
owner: Phạm Gia Huy
status: APPROVED
---
# 1. Tổng quan

Người dùng xem và sửa hồ sơ của chính mình; quản trị viên (role `admin`) xem hồ sơ của mọi người và khoá tài khoản.
Mọi thay đổi hồ sơ được ghi vào `audit_logs`.

# 2. Phân quyền

| Hành động | member | admin |
|---|---|---|
| Xem hồ sơ của mình | Có | Có |
| Sửa họ tên, avatar, số điện thoại | Có | Có |
| Xem hồ sơ người khác | Không | Có |
| Đổi role | Không | Có |
| Khoá / mở khoá tài khoản | Không | Có |

# 3. API

## 3.1 PATCH /api/v1/users/me

Sửa hồ sơ của người đang đăng nhập. Cập nhật bảng `users`, ghi `audit_logs`.

```json
{
  "full_name": "Phạm Gia Huy",
  "phone": "+84 912 345 678",
  "avatar_url": "https://cdn.example.com/avatars/huy.png"
}
```

## 3.2 POST /api/v1/admin/users/{id}/lock

Chỉ `admin`. Đặt `users.status = LOCKED`, thu hồi mọi phiên trong `login_sessions` của người đó (xem SPC-1) và ghi
`audit_logs`.

```sql
BEGIN;
UPDATE users SET status = 'LOCKED', updated_at = now() WHERE id = :user_id;
DELETE FROM login_sessions WHERE user_id = :user_id;
INSERT INTO audit_logs (actor_id, action, target_id) VALUES (:admin_id, 'USER_LOCKED', :user_id);
COMMIT;
```

# 4. Ràng buộc

- Số điện thoại theo định dạng E.164.
- Avatar tối đa 2 MB, chỉ PNG hoặc JPEG.
- Không ai được tự đổi role của chính mình.
