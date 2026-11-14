#!/usr/bin/env python3
"""CLI utility to manage, inspect, approve, and reject Personal-KB proposals.

Can be run directly via:
    python3 scripts/manage_proposals.py list
    python3 scripts/manage_proposals.py show <proposal_id>
    python3 scripts/manage_proposals.py approve <proposal_id> [--force] [--reviewer "Ryan Truong"]
    python3 scripts/manage_proposals.py reject <proposal_id> [--note "Reason"] [--reviewer "Ryan Truong"]
"""

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Auto re-exec with venv python if running under system python without backend dependencies
REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
if sys.prefix == sys.base_prefix and VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

sys.path.insert(0, str(REPO_ROOT / "backend"))

from personal_kb.services.proposals import (
    ProposalConflictError,
    ProposalNotFoundError,
    ProposalStore,
    apply_to_spec,
    file_hash,
    resolve_spec_path,
)

KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
API_BASE = os.environ.get("PERSONAL_KB_API", "http://localhost:8000")


def get_token() -> str | None:
    try:
        from personal_kb.core.config import get_settings
        from personal_kb.core.dev_tokens import DEV_EMAIL, DEV_USER_ID, mint_dev_token
        return mint_dev_token(get_settings(), user_id=DEV_USER_ID, email=DEV_EMAIL, minutes=60)
    except Exception:
        return None


def is_backend_alive() -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(f"{API_BASE}/health", headers={"User-Agent": "kb-cli"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def cmd_list(args):
    store = ProposalStore(KNOWLEDGE_DIR)
    status_filter = None if args.status == "ALL" else args.status
    proposals = store.list_all(status=status_filter)
    if not proposals:
        print(f"Không có đề xuất nào có trạng thái '{args.status}'.")
        return

    print(f"\n{'ID':<30} | {'SPEC':<12} | {'STATUS':<10} | {'CONFLICT':<8} | {'TIÊU ĐỀ'}")
    print("-" * 90)
    for p in sorted(proposals, key=lambda x: x.created_at, reverse=True):
        conflict_str = "⚠️ CÓ" if p.conflict_detected else "✓ Không"
        print(f"{p.id:<30} | {p.spec_id:<12} | {p.status:<10} | {conflict_str:<8} | {p.title}")
    print(f"\nTổng cộng: {len(proposals)} đề xuất.\n")


def cmd_show(args):
    store = ProposalStore(KNOWLEDGE_DIR)
    prop = store.get(args.proposal_id)
    if not prop:
        print(f"❌ Không tìm thấy đề xuất: {args.proposal_id}")
        sys.exit(1)

    print("\n" + "=" * 80)
    print(f"📄 CHI TIẾT ĐỀ XUẤT: {prop.id}")
    print("=" * 80)
    print(f"Tiêu đề:         {prop.title}")
    print(f"Target Spec ID:  {prop.spec_id} (Dự án: {prop.project_id})")
    print(f"Hành động:       {prop.action} -> Section: ## {prop.section}")
    print(f"Trạng thái:      {prop.status}")
    print(f"Ngày tạo:        {prop.created_at}")
    if prop.reviewed_at:
        print(f"Người duyệt:     {prop.reviewed_by} ({prop.reviewed_at})")
    if prop.review_note:
        print(f"Ghi chú duyệt:   {prop.review_note}")

    if prop.conflict_detected:
        print(f"\n⚠️ CẢNH BÁO XUNG ĐỘT (Conflict Detected):")
        print(f"  Mã quy chuẩn:  {prop.conflict_rule_id}")
        print(f"  Lý do vi phạm: {prop.conflict_reason}")
    else:
        print("\n✓ Trạng thái an toàn: Không phát hiện vi phạm Negative Constraints.")

    print(f"\n💡 Lý do đề xuất (Rationale):")
    print(f"  {prop.rationale}")

    print(f"\n📝 Nội dung Markdown đề xuất (Proposed Content):")
    print("-" * 80)
    print(prop.proposed_content)
    print("-" * 80 + "\n")


def cmd_approve(args):
    proposal_id = args.proposal_id
    reviewer = args.reviewer
    force = args.force

    # 1. Thử gọi API nếu backend đang chạy
    if is_backend_alive():
        token = get_token()
        if token:
            import urllib.request
            url = f"{API_BASE}/api/v1/proposals/{proposal_id}/approve"
            data = json.dumps({"reviewer": reviewer, "force": force}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    print(f"✓ [API] Đã phê duyệt đề xuất {proposal_id} thành công!")
                    print(f"  Trạng thái:   {res_data.get('status')}")
                    print(f"  Người duyệt:  {res_data.get('reviewed_by')}")
                    print(f"  Tài liệu:     {res_data.get('spec_id')}")
                    print("  Hệ thống đã tự động cập nhật Markdown file và re-ingest vào pgvector/cache.")
                    return
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8")
                print(f"❌ [API Error {e.code}]: {err_body}")
                sys.exit(1)
            except Exception as e:
                print(f"⚠️ Lỗi kết nối API: {e}. Đang chuyển sang chế độ cập nhật trực tiếp...")

    # 2. Chế độ offline/local: Cập nhật trực tiếp Markdown file và proposal JSON
    store = ProposalStore(KNOWLEDGE_DIR)
    prop = store.get(proposal_id)
    if not prop:
        print(f"❌ Không tìm thấy đề xuất: {proposal_id}")
        sys.exit(1)
    if prop.status != "PENDING":
        print(f"❌ Đề xuất {proposal_id} đã ở trạng thái {prop.status}")
        sys.exit(1)

    spec_file = resolve_spec_path(KNOWLEDGE_DIR, prop.spec_id)
    current_hash = file_hash(spec_file)

    # Kiểm tra OCC
    if not force and prop.base_hash and current_hash != prop.base_hash:
        print(f"❌ LỖI XUNG ĐỘT OCC: Tài liệu {prop.spec_id} đã bị chỉnh sửa kể từ khi tạo đề xuất.")
        print(f"  Base Hash: {prop.base_hash[:8]} | Hiện tại: {current_hash[:8] if current_hash else 'None'}")
        print("  Dùng cờ --force nếu bạn chắc chắn muốn ghi đè.")
        sys.exit(1)

    # Kiểm tra Negative Constraints
    if not force and prop.conflict_detected:
        print(f"❌ BỊ CHẶN BỞI NEGATIVE CONSTRAINT [{prop.conflict_rule_id}]: {prop.conflict_reason}")
        print("  Dùng cờ --force nếu bạn chắc chắn muốn bỏ qua cảnh báo.")
        sys.exit(1)

    # Áp dụng nội dung vào Markdown spec file (cùng code với ProposalStore.approve)
    apply_to_spec(prop, spec_file)

    # Cập nhật trạng thái proposal
    prop.status = "APPROVED"
    prop.reviewed_at = datetime.now(UTC).isoformat()
    prop.reviewed_by = reviewer
    prop_path = store._proposal_path(proposal_id)
    prop_path.write_text(json.dumps(prop.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✓ Đã phê duyệt và áp dụng đề xuất {proposal_id} thành công!")
    print(f"  File đã sửa: {spec_file}")
    print(f"  Người duyệt: {reviewer}")
    print(f"  Thời gian:   {prop.reviewed_at}")
    print("  (Lưu ý: Chạy './scripts/ingest.sh' nếu cần đồng bộ hóa vector store)")


def cmd_reject(args):
    proposal_id = args.proposal_id
    reviewer = args.reviewer
    note = args.note

    if is_backend_alive():
        token = get_token()
        if token:
            import urllib.request
            url = f"{API_BASE}/api/v1/proposals/{proposal_id}/reject"
            data = json.dumps({"reviewer": reviewer, "note": note}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    print(f"✓ [API] Đã từ chối đề xuất {proposal_id} thành công.")
                    return
            except Exception as e:
                print(f"⚠️ API error: {e}, fallback local reject...")

    store = ProposalStore(KNOWLEDGE_DIR)
    try:
        prop = store.reject(proposal_id, reviewer=reviewer, note=note)
        print(f"✓ Đã từ chối đề xuất {proposal_id}.")
        print(f"  Người từ chối: {reviewer}")
        print(f"  Lý do/Ghi chú: {note or 'Không có ghi chú'}")
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Quản trị phê duyệt đề xuất tri thức Personal-KB")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="Liệt kê đề xuất")
    p_list.add_argument("--status", choices=["PENDING", "APPROVED", "REJECTED", "ALL"], default="PENDING")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = subparsers.add_parser("show", help="Xem chi tiết đề xuất")
    p_show.add_argument("proposal_id", help="Mã đề xuất (VD: PROP-SEED-001)")
    p_show.set_defaults(func=cmd_show)

    # approve
    p_app = subparsers.add_parser("approve", help="Phê duyệt đề xuất")
    p_app.add_argument("proposal_id", help="Mã đề xuất cần duyệt")
    p_app.add_argument("--reviewer", default="Ryan Truong", help="Tên người duyệt")
    p_app.add_argument("--force", action="store_true", help="Bỏ qua cảnh báo OCC hoặc Negative Constraints")
    p_app.set_defaults(func=cmd_approve)

    # reject
    p_rej = subparsers.add_parser("reject", help="Từ chối đề xuất")
    p_rej.add_argument("proposal_id", help="Mã đề xuất cần từ chối")
    p_rej.add_argument("--reviewer", default="Ryan Truong", help="Tên người từ chối")
    p_rej.add_argument("--note", default=None, help="Lý do từ chối")
    p_rej.set_defaults(func=cmd_reject)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
