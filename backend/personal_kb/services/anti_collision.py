"""Semantic Anti-Collision Engine: Detects contradictions with Negative Constraints.

Scans incoming proposals before approval to prevent violation of core architectural
and business guardrails (e.g. float for money, hardcoded coefficients, hard delete,
direct modification of locked timesheets).
"""

import logging
import re
from dataclasses import dataclass

from personal_kb.services.projects import project_of

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConflictCheckResult:
    conflict_detected: bool
    rule_id: str | None = None
    reason: str | None = None


# Authoritative rules mapped to detection patterns
GUARDRAIL_RULES = [
    {
        "rule_id": "NC-HR-001",
        "name": "Cấm dùng float/double cho tiền tệ & lương thưởng",
        "projects": ["Demo-Core", "ALL"],
        "patterns": [
            r"\b(float|double)\b.*(salary|lương|tiền|amount|pay|net_pay|gross_pay|tax|thuế|allowance|phụ cấp)",
            r"(salary|lương|tiền|amount|pay|net_pay|gross_pay|tax|thuế|allowance|phụ cấp).*\b(float|double)\b",
            r"(kiểu\s+dữ\s+liệu\s+số\s+thực|kiểu\s+float|dùng\s+float|chuyển\s+sang\s+float)",
        ],
        "reason": (
            "Vi phạm NC-HR-001: Mọi trường liên quan đến tiền tệ, lương thưởng bắt buộc dùng kiểu Decimal / "
            "Numeric(18,2). Tuyệt đối cấm float/double do rủi ro sai số dấu phẩy động."
        ),
    },
    {
        "rule_id": "NC-HR-010",
        "name": "Cấm Hard Delete hồ sơ nhân sự",
        "projects": ["Demo-Core", "ALL"],
        "patterns": [
            r"DELETE\s+FROM\s+employees\b",
            r"xóa\s+vĩnh\s+viễn\s+(nhân\s+viên|hồ\s+sơ|nhân\s+sự)",
            r"hard\s+delete.*(employee|nhân\s+viên|nhân\s+sự)",
            r"xóa\s+cứng.*(employee|nhân\s+viên|nhân\s+sự)",
        ],
        "reason": (
            "Vi phạm NC-HR-010: Cấm thực thi hard delete trên bảng employees. Mọi hoạt động chấm dứt hợp đồng hoặc "
            "thôi việc bắt buộc dùng Soft Delete (status='TERMINATED', is_deleted=true, deleted_at)."
        ),
    },
    {
        "rule_id": "NC-HR-020",
        "name": "Cấm hardcode hệ số ca đêm và làm thêm giờ",
        "projects": ["Demo-Core", "ALL"],
        "patterns": [
            r"(\*|\=)\s*1\.3\b.*(ca\s+đêm|night_shift|night|hệ\s+số)",
            r"(ca\s+đêm|night_shift|night).*(gán|mặc\s+định|hardcode).*1\.3\b",
            r"(\*|\=)\s*(1\.5|2\.0|3\.0)\b.*(làm\s+thêm|overtime|ot)",
            r"(giảm\s+trừ\s+bản\s+thân|personal_deduction).*(gán|hardcode).*11000000",
        ],
        "reason": (
            "Vi phạm NC-HR-020: Các hệ số ca đêm (>=1.3) và làm thêm giờ (1.5, 2.0, 3.0) hoặc mức giảm trừ gia cảnh "
            "phải truy xuất động từ cấu hình (System Configuration / Policy Engine), cấm hardcode vào mã nguồn."
        ),
    },
    {
        "rule_id": "NC-HR-021",
        "name": "Cấm sửa trực tiếp kỳ công đã LOCKED",
        "projects": ["Demo-Core", "ALL"],
        "patterns": [
            r"UPDATE\s+timesheets\s+SET.*status\s*=\s*['\"]LOCKED['\"]",
            r"(chỉnh\s+sửa|cập\s+nhật|ghi\s+đè)\s+trực\s+tiếp\s+kỳ\s+công\s+(đã\s+khóa|đã\s+chốt|locked)",
            r"(modify|edit|update)\s+locked\s+timesheet",
        ],
        "reason": (
            "Vi phạm NC-HR-021: Khi kỳ công đã chuyển sang trạng thái LOCKED, mọi sửa đổi phải tạo phiếu điều chỉnh "
            "công (timesheet_adjustments) và được phê duyệt riêng, cấm ghi đè trực tiếp."
        ),
    },
    {
        "rule_id": "NC-PKB-001",
        "name": "Cấm lộ secrets / credentials và bypass human gate",
        "projects": ["Personal-KB", "ALL"],
        "patterns": [
            r"(bypass|bỏ\s+qua)\s+(human\s+gate|phê\s+duyệt|kiểm\s+duyệt)",
            r"(auto[-_]?approve\s*=\s*true|tự\s+động\s+duyệt\s+không\s+cần\s+người)",
            r"(hardcode|gán\s+cứng)\s+(token|api_key|secret|password)",
        ],
        "reason": (
            "Vi phạm NC-PKB-001: Mọi thay đổi tri thức bắt buộc qua Human Gate (phê duyệt có trách nhiệm). Cấm cấu "
            "hình tự động duyệt hoặc nhúng secret vào spec."
        ),
    },
    {
        "rule_id": "NC-PKB-010",
        "name": "Cấm Context Window Bloat trong MCP Tools",
        "projects": ["Personal-KB", "ALL"],
        "patterns": [
            r"(bỏ\s+giới\s+hạn\s+top-3|không\s+giới\s+hạn\s+guardrails|nạp\s+toàn\s+bộ\s+urd)",
            r"limit\s*=\s*(100|1000|None|all)\s+guardrails",
        ],
        "reason": (
            "Vi phạm NC-PKB-010: Tuân thủ nghiêm ngặt luật Top-3 Hard Limit (< 180 tokens) cho guardrails để bảo vệ "
            "Context Window."
        ),
    },
]


def detect_conflicts(
    *,
    spec_id: str,
    proposed_content: str,
    section: str = "",
    project: str = "",
) -> ConflictCheckResult:
    """Analyze proposed content for direct contradictions with architectural and business negative constraints."""
    if not proposed_content:
        return ConflictCheckResult(conflict_detected=False)

    full_text = f"{section}\n{proposed_content}"
    clean_text = full_text.strip()

    # Determine project context from spec_id or explicit project
    proj_context = (project.strip() or project_of(spec_id)).upper()

    for rule in GUARDRAIL_RULES:
        rule_projects = [p.upper() for p in rule["projects"]]
        if "ALL" not in rule_projects and proj_context not in rule_projects and "ALL" != proj_context:
            continue

        for pattern in rule["patterns"]:
            if re.search(pattern, clean_text, re.IGNORECASE):
                log.warning(
                    "[AntiCollision] Conflict detected for %s against rule %s: %s",
                    spec_id,
                    rule["rule_id"],
                    rule["name"],
                )
                return ConflictCheckResult(
                    conflict_detected=True,
                    rule_id=rule["rule_id"],
                    reason=rule["reason"],
                )

    return ConflictCheckResult(conflict_detected=False)
