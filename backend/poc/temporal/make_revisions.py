"""Builds the PoC-A revisions of the mock specs (#297); run from ai/backend: python poc/temporal/make_revisions.py

rev2: SPC-2 renames its table payments to payment_transactions and adds a refund API (admin only); SPC-3 renames
email_outbox to notification_queue and replaces link verification with an OTP API. rev3: SPC-2 drops the refund API
again (and SPC-5 is deleted, see labels.yaml). SPC-1, SPC-4 and SPC-5 never change. Every replacement must match
exactly once, so a drifting mock spec fails here instead of producing a silently wrong dataset.
"""

from pathlib import Path

HERE = Path(__file__).parent
MOCK = HERE.parents[1] / "mock_data"

REFUND = """## 2.3 POST /api/v1/payments/{id}/refund

Hoàn tiền một giao dịch đã thành công. Chỉ role `admin` được gọi.

| Thuộc tính | Giá trị |
|---|---|
| Auth | Bearer access token, role `admin` |
| Bảng ghi | `refunds`, `payment_transactions` |
| Bảng đọc | `orders` |

"""

OTP = """# 3. Xác thực email

## 3.1 POST /api/v1/auth/verify-otp

Người dùng nhập mã OTP 6 số nhận qua email. Hệ thống kiểm tra mã trong `email_verifications` (sống 10 phút, sai tối đa
5 lần), sau đó đặt `users.status = ACTIVE` và `users.email_verified_at = now()`.

| Thuộc tính | Giá trị |
|---|---|
| Auth | Không |
| Bảng đọc | `email_verifications` |
| Bảng ghi | `users`, `email_verifications` |
"""


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one {old!r}, found {text.count(old)}")
    return text.replace(old, new)


def spc_2_v2(text: str) -> str:
    text = replace_once(text, "status: APPROVED\n---", "status: APPROVED\nversion: 2\n---")
    text = replace_once(text, "(sở hữu bảng `payments`)", "(sở hữu bảng `payment_transactions`)")
    text = replace_once(text, "| Bảng ghi | `payments` |", "| Bảng ghi | `payment_transactions` |")
    text = replace_once(text, "`vnp_TxnRef` | `payments` |", "`vnp_TxnRef` | `payment_transactions` |")
    text = replace_once(
        text,
        "| 4 | Cập nhật `payments.status = SUCCEEDED` | `payments` |",
        "| 4 | Cập nhật `payment_transactions.status = SUCCEEDED` | `payment_transactions` |",
    )
    text = replace_once(text, "chỉ khi `payments.status = PENDING`", "chỉ khi `payment_transactions.status = PENDING`")
    text = replace_once(text, "UPDATE payments\n", "UPDATE payment_transactions\n")
    return replace_once(text, "# 3. Quy tắc nghiệp vụ", REFUND + "# 3. Quy tắc nghiệp vụ")


def spc_2_v3(text: str) -> str:
    text = replace_once(text, "version: 2\n", "version: 3\n")
    return replace_once(text, REFUND, "")


def spc_3_v2(text: str) -> str:
    text = replace_once(text, "status: APPROVED\n---", "status: APPROVED\nversion: 2\n---")
    text = replace_once(text, "| Bảng ghi | `email_outbox` |", "| Bảng ghi | `notification_queue` |")
    text = replace_once(text, "ghi một dòng vào `email_outbox`", "ghi một dòng vào `notification_queue`")
    head, marker, _ = text.partition("# 3. Xác thực email")
    if not marker:
        raise SystemExit("SPC-3 has no section '# 3. Xác thực email'")
    return head + OTP


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    spc_2 = (MOCK / "SPC-2-thanh-toan.md").read_text(encoding="utf-8")
    spc_3 = (MOCK / "SPC-3-dang-ky-email.md").read_text(encoding="utf-8")
    write(HERE / "rev2" / "SPC-2-thanh-toan.md", spc_2_v2(spc_2))
    write(HERE / "rev2" / "SPC-3-dang-ky-email.md", spc_3_v2(spc_3))
    write(HERE / "rev3" / "SPC-2-thanh-toan.md", spc_2_v3(spc_2_v2(spc_2)))
