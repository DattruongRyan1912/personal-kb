---
id: SPC-5
title: Từ điển dữ liệu — bảng users
owner: Nguyễn Minh Anh
status: APPROVED
---
# 1. Tổng quan

Từ điển dữ liệu của bảng `users`, bảng trung tâm mà các luồng đăng nhập (SPC-1), thanh toán (SPC-2), đăng ký (SPC-3)
và hồ sơ (SPC-4) cùng đọc hoặc ghi. Mọi thay đổi cột phải cập nhật spec này trước.

# 2. Bảng users

## 2.1 Danh sách cột

| # | Cột | Kiểu | Null | Mặc định | Ghi bởi | Mô tả |
|---|---|---|---|---|---|---|
| 1 | id | uuid | Không | gen_random_uuid() | SPC-3 | Khoá chính |
| 2 | email | citext | Không | — | SPC-3 | Email công ty, duy nhất |
| 3 | password_hash | text | Không | — | SPC-3 | Argon2id |
| 4 | full_name | text | Không | — | SPC-3, SPC-4 | Họ tên |
| 5 | phone | text | Có | null | SPC-4 | Định dạng E.164 |
| 6 | avatar_url | text | Có | null | SPC-4 | URL ảnh đại diện |
| 7 | role | text | Không | 'member' | SPC-4 | member hoặc admin |
| 8 | status | text | Không | 'PENDING_VERIFICATION' | SPC-3, SPC-4 | PENDING_VERIFICATION, ACTIVE, LOCKED |
| 9 | email_verified_at | timestamptz | Có | null | SPC-3 | Thời điểm xác thực email |
| 10 | failed_login_count | int | Không | 0 | SPC-1 | Số lần đăng nhập sai liên tiếp |
| 11 | locked_until | timestamptz | Có | null | SPC-1 | Khoá tạm đến thời điểm này |
| 12 | last_login_at | timestamptz | Có | null | SPC-1 | Lần đăng nhập thành công gần nhất |
| 13 | reward_points | int | Không | 0 | SPC-2 | Điểm thưởng từ thanh toán |
| 14 | locale | text | Không | 'vi-VN' | SPC-4 | Ngôn ngữ giao diện |
| 15 | timezone | text | Không | 'Asia/Ho_Chi_Minh' | SPC-4 | Múi giờ |
| 16 | marketing_opt_in | boolean | Không | false | SPC-3 | Đồng ý nhận email marketing |
| 17 | created_at | timestamptz | Không | now() | SPC-3 | Thời điểm tạo |
| 18 | updated_at | timestamptz | Không | now() | Trigger | Cập nhật lần cuối |
| 19 | deleted_at | timestamptz | Có | null | SPC-4 | Xoá mềm |
| 20 | version | int | Không | 1 | Trigger | Khoá lạc quan |

## 2.2 Chỉ mục và ràng buộc

```sql
CREATE UNIQUE INDEX users_email_key ON users (email) WHERE deleted_at IS NULL;
CREATE INDEX users_status_idx ON users (status);
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('member', 'admin'));
ALTER TABLE users ADD CONSTRAINT users_reward_points_check CHECK (reward_points >= 0);
```

# 3. Bảng liên quan

| Bảng | Khoá ngoại tới users | Spec sở hữu |
|---|---|---|
| login_sessions | user_id | SPC-1 |
| payments | user_id | SPC-2 |
| orders | user_id | SPC-2 |
| email_verifications | user_id | SPC-3 |
| audit_logs | actor_id, target_id | SPC-4 |
