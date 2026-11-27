"""材料替代领域服务。

工程师在材料核验中为修缮方案清单行挑选替代材料，本服务承载批量采纳的全部规则：

* 一条替代必须保留原来的清单行（材料/规格/用量/单位）、替代规格和对应核验单；
* 批量采纳只允许选择同一方案内的建议，逐条判定资格、支持部分生效；
* 核验单未签认（含退回中）或用量单位不一致的建议退回复核，绝不沿用旧单位数值；
* 生效结果同步到方案待审清单，并为每个批次生成一条工艺变更记录（变更签证）；
* 重复提交已生效替换只幂等跳过一次，不新增材料行；
* 待复核/被拒绝的建议禁止领用，被拒绝行修订后可再次提交，领用记录永久留在方案内。
"""
from __future__ import annotations

import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# ── 替代建议状态 ──
STATUS_PENDING = "待采纳"
STATUS_RECHECK = "待复核"
STATUS_EFFECTIVE = "已生效"
STATUS_REJECTED = "已拒绝"

# 修订时允许工程师修改的替代侧字段（原清单行字段永不在此列）
REVISABLE_FIELDS = [
    "替代材料名称",
    "替代规格型号",
    "替代用量",
    "替代单位",
    "核验单ID",
]


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class MaterialSubstitutionService(BaseModuleService):
    MODULE = "material_substitution"
    ENTITY = "材料替代建议"
    OPERATION_TERM = "批量采纳"
    LIST_FIELDS = [
        "方案ID",
        "清单行号",
        "原材料名称",
        "原规格型号",
        "原用量",
        "原单位",
        "替代材料名称",
        "替代规格型号",
        "替代用量",
        "替代单位",
        "核验单ID",
        "复核原因",
        "备注说明",
    ]
    REQUIRED_FIELDS = [
        "方案ID",
        "清单行号",
        "替代材料名称",
        "替代规格型号",
        "替代用量",
        "替代单位",
        "核验单ID",
    ]
    # 状态流转全部走本服务的专用方法（批量采纳/拒绝/修订），不开放通用动作
    STATUS_ORDER = [STATUS_PENDING, STATUS_RECHECK, STATUS_EFFECTIVE, STATUS_REJECTED]
    ACTION_RULES: dict[str, str] = {}

    # ── 基础登记 ──
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            return self.suggest(values), []
        except ValueError as exc:
            return None, [str(exc)]

    def suggest(self, values: dict[str, Any]) -> dict[str, Any]:
        """登记一条替代建议；原清单行信息从方案 plan_lines 原样复制保留。"""
        missing = [
            field for field in self.REQUIRED_FIELDS
            if str(values.get(field) or "").strip() == ""
        ]
        if missing:
            raise ValueError(f"缺少必填字段：{'、'.join(missing)}")

        plan_id = int(values["方案ID"])
        plan = store.find("restoration_plan", plan_id)
        if plan is None:
            raise ValueError(f"修缮方案 {plan_id} 不存在，无法登记替代建议")

        line_no = str(values["清单行号"]).strip()
        original_line = self._find_plan_line(plan, line_no)
        if original_line is None:
            raise ValueError(
                f"方案{plan.get('方案编号', plan_id)}中不存在清单行「{line_no}」，"
                "替代建议必须挂靠在原有清单行上"
            )

        verify_id = int(values["核验单ID"])
        verify = store.find("material_verify", verify_id)
        if verify is None:
            raise ValueError(f"材料核验单 {verify_id} 不存在，替代建议必须对应核验单")

        rows = store.rows(self.MODULE)
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": STATUS_PENDING,
            "pending": True,
            "abnormal": False,
            "方案ID": plan_id,
            "清单行号": line_no,
            "可独立施工": bool(original_line.get("可独立施工", False)),
            # 原清单行快照：采纳/拒绝/退回都不允许覆盖这一段
            "原材料名称": original_line.get("材料名称", ""),
            "原规格型号": original_line.get("规格型号", ""),
            "原用量": original_line.get("用量", ""),
            "原单位": original_line.get("单位", ""),
            "替代材料名称": str(values["替代材料名称"]).strip(),
            "替代规格型号": str(values["替代规格型号"]).strip(),
            "替代用量": values["替代用量"],
            "替代单位": str(values["替代单位"]).strip(),
            "核验单ID": verify_id,
            "批次号": "",
            "变更签证ID": None,
            "复核原因": "",
            "拒绝原因": "",
            "退回回执": False,
            "生效时间": "",
            "领用记录": [],
            "备注说明": str(values.get("备注说明", "") or ""),
        }
        rows.append(entry)
        return entry

    # ── 资格判定 ──
    def evaluate_eligibility(
        self, row: dict[str, Any]
    ) -> tuple[bool, str]:
        """返回 (是否有资格生效, 原因)。判定永远基于最新核验单状态实时计算。"""
        verify_id = int(row.get("核验单ID", 0))
        verify = store.find("material_verify", verify_id)
        if verify is None:
            return False, f"核验单#{verify_id}不存在，无法确认替代材料资格"
        if verify.get("status") != "已签认":
            return False, (
                f"核验单#{verify_id}当前状态为「{verify.get('status', '')}」，"
                "未签认（核验中/已退回）的替代材料暂不可采纳"
            )

        original_unit = str(row.get("原单位", "")).strip()
        substitute_unit = str(row.get("替代单位", "")).strip()
        if not substitute_unit:
            return False, "替代材料未填写用量单位，退回复核后补齐单位再提交"
        if substitute_unit != original_unit:
            # 单位不一致：只允许退回复核，禁止把原单位下的数值直接搬过去
            return False, (
                f"用量单位不一致：原清单行「{original_unit}」，替代材料「{substitute_unit}」；"
                "退回复核，不得沿用旧单位的数值"
            )
        return True, ""

    # ── 批量采纳 ──
    def batch_adopt(
        self,
        plan_id: int,
        substitution_ids: list[int],
        applicant: str | None = None,
    ) -> dict[str, Any]:
        """批量采纳同一方案下的多条替代建议，返回逐行回执。"""
        plan = store.find("restoration_plan", plan_id)
        if plan is None:
            raise ValueError(f"修缮方案 {plan_id} 不存在")

        # 去重但保持顺序，重复选择同一条不会产生两次处理
        ids = list(dict.fromkeys(int(sid) for sid in substitution_ids))
        if not ids:
            raise ValueError("至少选择一条替代建议再提交批量采纳")

        selected: list[dict[str, Any]] = []
        for sid in ids:
            row = store.find(self.MODULE, sid)
            if row is None:
                raise ValueError(f"材料替代建议 {sid} 不存在或已归档")
            if int(row.get("方案ID", -1)) != plan_id:
                raise ValueError(
                    f"替代建议#{sid}不属于方案「{plan.get('方案编号', plan_id)}」，"
                    "一次批量采纳只能处理同一方案内的建议"
                )
            selected.append(row)

        receipt: dict[str, Any] = {
            "方案ID": plan_id,
            "方案编号": plan.get("方案编号", ""),
            "操作人": applicant or "文保工程师",
            "处理时间": _today(),
            "生效": [],
            "退回复核": [],
            "幂等跳过": [],
            "拒绝待修订": [],
            "批次号": "",
            "变更签证ID": None,
            "禁止领用清单行": [],
        }

        newly_effective: list[dict[str, Any]] = []
        for row in selected:
            line_no = row.get("清单行号", "")
            # 已生效且核验未被退回：幂等跳过，不新增材料、不重复生成变更记录
            if row.get("status") == STATUS_EFFECTIVE and not row.get("退回回执"):
                receipt["幂等跳过"].append(self._line_summary(row, "替换已生效，重复提交只生效一次"))
                continue

            # 已拒绝行必须先由申请人修订（回应审核意见）才能再次提交
            if row.get("status") == STATUS_REJECTED:
                receipt["拒绝待修订"].append(
                    self._line_summary(
                        row,
                        f"该清单行替换已被拒绝（{row.get('拒绝原因', '')}），"
                        "请先修订替代建议再提交",
                    )
                )
                continue

            eligible, reason = self.evaluate_eligibility(row)
            if not eligible:
                row["status"] = STATUS_RECHECK
                row["pending"] = True
                row["abnormal"] = True
                row["复核原因"] = reason
                receipt["退回复核"].append(self._line_summary(row, reason))
                continue

            row["status"] = STATUS_EFFECTIVE
            row["pending"] = False
            row["abnormal"] = False
            row["复核原因"] = ""
            row["退回回执"] = False
            row["生效时间"] = _today()
            newly_effective.append(row)
            receipt["生效"].append(self._line_summary(row, "核验单已签认且用量单位一致"))

        if newly_effective:
            batch_no = self._next_batch_no(plan)
            change_order_id = self._create_change_order(plan, newly_effective, batch_no, receipt["操作人"])
            for row in newly_effective:
                row["批次号"] = batch_no
                row["变更签证ID"] = change_order_id
            receipt["批次号"] = batch_no
            receipt["变更签证ID"] = change_order_id

        self._sync_plan_lists(plan)
        receipt["禁止领用清单行"] = [
            item["清单行号"] for item in receipt["退回复核"]
        ]
        return receipt

    # ── 领用控制 ──
    def requisition(
        self,
        substitution_id: int,
        receiver: str | None = None,
        quantity: Any = None,
    ) -> dict[str, Any]:
        """施工方领用替代材料。只有已生效且核验仍然有效的建议可以领用。"""
        row = store.find(self.MODULE, substitution_id)
        if row is None:
            raise ValueError(f"材料替代建议 {substitution_id} 不存在")

        if row.get("退回回执") or row.get("status") == STATUS_RECHECK:
            raise ValueError(
                f"清单行{row.get('清单行号')}的替代材料正在待复核"
                f"（{row.get('复核原因', '核验退回')}），施工方不得领用该批材料"
            )
        if row.get("status") != STATUS_EFFECTIVE:
            raise ValueError(
                f"清单行{row.get('清单行号')}替代建议状态为「{row.get('status')}」，"
                "尚未生效，不能领用"
            )

        verify = store.find("material_verify", int(row["核验单ID"]))
        if verify is None or verify.get("status") != "已签认":
            # 兜底：核验单在生效后被退回，立即冻结领用
            raise ValueError(
                f"关联核验单#{row.get('核验单ID')}已不再是已签认状态，该批待复核材料禁止领用"
            )

        record = {
            "领用记录ID": max((r.get("领用记录ID", 0) for r in row.get("领用记录", [])), default=0) + 1,
            "领用时间": _today(),
            "领用人": (receiver or "施工方").strip(),
            "领用数量": quantity if quantity not in (None, "") else row.get("替代用量"),
            "领用单位": row.get("替代单位"),
            "清单行号": row.get("清单行号"),
            "材料名称": row.get("替代材料名称"),
            "规格型号": row.get("替代规格型号"),
            "核验单ID": row.get("核验单ID"),
            "批次号": row.get("批次号"),
        }
        row.setdefault("领用记录", []).append(record)

        # 领用事实同步归档到原方案：任何后续驳回/退回都不会抹掉这段记录
        plan = store.find("restoration_plan", int(row["方案ID"]))
        if plan is not None:
            archive_record = dict(record)
            archive_record["方案编号"] = plan.get("方案编号", "")
            archive_record["原清单材料"] = row.get("原材料名称")
            archive_record["原清单规格"] = row.get("原规格型号")
            plan.setdefault("requisition_archive", []).append(archive_record)
        return record

    # ── 审核拒绝与申请人修订 ──
    def reject(self, substitution_id: int, reason: str | None = None) -> dict[str, Any]:
        """方案审核时依据工艺变更记录拒绝某条清单行替换。"""
        row = store.find(self.MODULE, substitution_id)
        if row is None:
            raise ValueError(f"材料替代建议 {substitution_id} 不存在")
        if row.get("status") != STATUS_EFFECTIVE:
            raise ValueError(
                f"清单行{row.get('清单行号')}当前为「{row.get('status')}」，"
                "只有已生效进入待审清单的替换可以被拒绝"
            )
        row["status"] = STATUS_REJECTED
        row["pending"] = True
        row["abnormal"] = True
        row["拒绝原因"] = (reason or "方案审核未通过该清单行替换").strip()
        plan = store.find("restoration_plan", int(row["方案ID"]))
        if plan is not None:
            self._sync_plan_lists(plan)
        return row

    def revise(self, substitution_id: int, values: dict[str, Any]) -> dict[str, Any]:
        """申请人回到方案后修订被拒绝/待复核的建议；原清单行字段不允许修改。"""
        row = store.find(self.MODULE, substitution_id)
        if row is None:
            raise ValueError(f"材料替代建议 {substitution_id} 不存在")
        if row.get("status") not in (STATUS_RECHECK, STATUS_REJECTED):
            raise ValueError(
                f"清单行{row.get('清单行号')}当前为「{row.get('status')}」，"
                "只有待复核或已拒绝的建议可以修订"
            )
        for field in REVISABLE_FIELDS:
            if field in values and str(values[field] or "").strip() != "":
                row[field] = int(values[field]) if field == "核验单ID" else values[field]

        if "核验单ID" in values:
            verify = store.find("material_verify", int(row["核验单ID"]))
            if verify is None:
                raise ValueError(f"材料核验单 {row['核验单ID']} 不存在")
            row["退回回执"] = False

        row["status"] = STATUS_PENDING
        row["pending"] = True
        row["abnormal"] = False
        row["复核原因"] = ""
        row["拒绝原因"] = ""
        row["批次号"] = ""
        row["变更签证ID"] = None
        return row

    # ── 方案侧视图 ──
    def plan_eligibility(self, plan_id: int) -> dict[str, Any]:
        """方案审批入口：说明每条清单替换的资格、工艺变更记录与领用限制。"""
        plan = store.find("restoration_plan", plan_id)
        if plan is None:
            raise ValueError(f"修缮方案 {plan_id} 不存在")

        substitutions = [
            row for row in store.rows(self.MODULE)
            if int(row.get("方案ID", -1)) == plan_id
        ]
        items: list[dict[str, Any]] = []
        for row in substitutions:
            eligible, reason = self.evaluate_eligibility(row)
            verify = store.find("material_verify", int(row.get("核验单ID", 0)))
            items.append({
                "替代建议ID": row.get("id"),
                "清单行号": row.get("清单行号"),
                "可独立施工": row.get("可独立施工", False),
                "原材料名称": row.get("原材料名称"),
                "原规格型号": row.get("原规格型号"),
                "原用量": row.get("原用量"),
                "原单位": row.get("原单位"),
                "替代材料名称": row.get("替代材料名称"),
                "替代规格型号": row.get("替代规格型号"),
                "替代用量": row.get("替代用量"),
                "替代单位": row.get("替代单位"),
                "核验单ID": row.get("核验单ID"),
                "核验单状态": verify.get("status") if verify else "核验单不存在",
                "替代状态": row.get("status"),
                "有资格生效": (
                    eligible and row.get("status") == STATUS_PENDING
                ),
                "已经生效": row.get("status") == STATUS_EFFECTIVE and not row.get("退回回执"),
                "资格说明": reason,
                "批次号": row.get("批次号", ""),
                "变更签证ID": row.get("变更签证ID"),
                "复核原因": row.get("复核原因", ""),
                "拒绝原因": row.get("拒绝原因", ""),
                "退回回执": row.get("退回回执", False),
                "允许领用": (
                    row.get("status") == STATUS_EFFECTIVE
                    and not row.get("退回回执")
                    and eligible
                ),
                "已领用次数": len(row.get("领用记录", [])),
            })

        return {
            "方案ID": plan_id,
            "方案编号": plan.get("方案编号", ""),
            "方案状态": plan.get("status", ""),
            "原清单行": plan.get("plan_lines", []),
            "待审清单": plan.get("substitution_pending", []),
            "待复核清单": plan.get("substitution_recheck", []),
            "替代建议": items,
            "可生效行数": sum(1 for item in items if item["有资格生效"] or item["已经生效"]),
            "待复核行数": sum(1 for item in items if item["替代状态"] == STATUS_RECHECK),
            "已拒绝行数": sum(1 for item in items if item["替代状态"] == STATUS_REJECTED),
            "领用归档": plan.get("requisition_archive", []),
        }

    def mark_verify_returned(self, verify_id: int) -> list[dict[str, Any]]:
        """核验单退回（含迟到回执）时联动冻结相关替代建议。"""
        affected: list[dict[str, Any]] = []
        for row in store.rows(self.MODULE):
            if int(row.get("核验单ID", -1)) != verify_id:
                continue
            row["退回回执"] = True
            if row.get("status") == STATUS_EFFECTIVE:
                row["previous_status"] = STATUS_EFFECTIVE
            if row.get("status") != STATUS_REJECTED:
                row["status"] = STATUS_RECHECK
                row["pending"] = True
                row["abnormal"] = True
            row["复核原因"] = (
                f"关联核验单#{verify_id}已退回（退回回执），"
                "该批材料转为待复核，禁止继续领用"
            )
            affected.append(dict(row))
            plan = store.find("restoration_plan", int(row.get("方案ID", 0)))
            if plan is not None:
                self._sync_plan_lists(plan)
        return affected

    # ── 内部辅助 ──
    @staticmethod
    def _find_plan_line(plan: dict[str, Any], line_no: str) -> dict[str, Any] | None:
        for line in plan.get("plan_lines", []):
            if str(line.get("line_no", "")) == line_no:
                return line
        return None

    @staticmethod
    def _next_batch_no(plan: dict[str, Any]) -> str:
        seq = int(plan.get("substitution_batch_seq", 0)) + 1
        plan["substitution_batch_seq"] = seq
        return f"B{plan.get('id', 'X')}-{seq}"

    @staticmethod
    def _line_summary(row: dict[str, Any], note: str) -> dict[str, Any]:
        return {
            "替代建议ID": row.get("id"),
            "清单行号": row.get("清单行号"),
            "原材料名称": row.get("原材料名称"),
            "原规格型号": row.get("原规格型号"),
            "替代材料名称": row.get("替代材料名称"),
            "替代规格型号": row.get("替代规格型号"),
            "替代用量": row.get("替代用量"),
            "替代单位": row.get("替代单位"),
            "核验单ID": row.get("核验单ID"),
            "替代状态": row.get("status"),
            "说明": note,
        }

    def _create_change_order(
        self,
        plan: dict[str, Any],
        effective_rows: list[dict[str, Any]],
        batch_no: str,
        applicant: str,
    ) -> int:
        """每个生效批次生成一条工艺变更记录，供方案审核使用。"""
        change_rows = store.rows("change_order")
        new_id = max((int(row.get("id", 0)) for row in change_rows), default=0) + 1
        line_desc = "、".join(
            f"{row.get('清单行号')}（{row.get('原材料名称')}→{row.get('替代材料名称')}）"
            for row in effective_rows
        )
        change_order = {
            "id": new_id,
            "status": "已签认",
            "pending": False,
            "abnormal": False,
            "变更事项": f"方案{plan.get('方案编号', plan.get('id'))}材料替代工艺变更（批次{batch_no}）",
            "变更原因": f"材料核验通过后批量采纳替代建议，涉及清单行：{line_desc}",
            "影响工序": plan.get("修缮工艺", ""),
            "费用增减": 0,
            "提出人": applicant,
            "审批人": "方案审批待审（工艺变更记录）",
            "签认日期": _today(),
            "备注说明": (
                f"批次{batch_no}；替代建议ID："
                f"{','.join(str(row['id']) for row in effective_rows)}"
            ),
            "方案ID": plan.get("id"),
            "批次号": batch_no,
            "替代建议IDs": [row["id"] for row in effective_rows],
        }
        change_rows.append(change_order)
        return new_id

    def _sync_plan_lists(self, plan: dict[str, Any]) -> None:
        """把确认结果同步到方案待审清单；待复核行单独列示并标明禁止领用。"""
        related = [
            row for row in store.rows(self.MODULE)
            if int(row.get("方案ID", -1)) == int(plan.get("id", -1))
        ]
        plan["substitution_pending"] = [
            {
                "清单行号": row.get("清单行号"),
                "原材料名称": row.get("原材料名称"),
                "原规格型号": row.get("原规格型号"),
                "替代材料名称": row.get("替代材料名称"),
                "替代规格型号": row.get("替代规格型号"),
                "替代用量": row.get("替代用量"),
                "替代单位": row.get("替代单位"),
                "核验单ID": row.get("核验单ID"),
                "批次号": row.get("批次号"),
                "变更签证ID": row.get("变更签证ID"),
                "生效时间": row.get("生效时间"),
            }
            for row in related
            if row.get("status") == STATUS_EFFECTIVE and not row.get("退回回执")
        ]
        plan["substitution_recheck"] = [
            {
                "清单行号": row.get("清单行号"),
                "替代材料名称": row.get("替代材料名称"),
                "核验单ID": row.get("核验单ID"),
                "复核原因": row.get("复核原因"),
                "退回回执": row.get("退回回执", False),
                "禁止领用": True,
            }
            for row in related
            if row.get("status") == STATUS_RECHECK
        ]
