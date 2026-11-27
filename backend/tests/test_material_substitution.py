"""材料替代批量采纳全链路测试。

覆盖需求点：
* 批量采纳只能选择同一方案内的建议；原清单行/替代规格/核验单全程保留；
* 单位不一致退回复核，禁止沿用旧单位数值；
* 生效结果同步方案待审清单并生成工艺变更记录（变更签证）；
* 待复核/核验退回材料禁止施工方领用，迟到退回回执同样冻结；
* 重复提交已生效替换幂等只生效一次，不新增材料行；
* 可独立施工清单行互不阻塞，被拒绝行修订后可再次提交，领用记录不消失。
"""
from __future__ import annotations

import copy

import pytest

from app.seed import SEED_ROWS
from app.services.change_order import ChangeOrderService
from app.services.material_verify import MaterialVerifyService
from app.services.material_substitution import (
    MaterialSubstitutionService,
    STATUS_EFFECTIVE,
    STATUS_PENDING,
    STATUS_RECHECK,
    STATUS_REJECTED,
)
from app.store import store

sub_service = MaterialSubstitutionService()
verify_service = MaterialVerifyService()
change_service = ChangeOrderService()

DEMO_PLAN_ID = 4


@pytest.fixture(autouse=True)
def reset_store():
    store._idempotent_log.clear()
    store._resource_locks.clear()
    for name in list(store._tables.keys()):
        if name in SEED_ROWS:
            store._tables[name] = copy.deepcopy(SEED_ROWS[name])
        else:
            store._tables[name] = []
    yield


def _suggest(line_no: str, verify_id: int, unit: str = "kg", qty: int = 500) -> dict:
    """基于 demo 方案（id=4）的原清单行登记替代建议。"""
    values = {
        "方案ID": DEMO_PLAN_ID,
        "清单行号": line_no,
        "替代材料名称": f"替代-{line_no}",
        "替代规格型号": f"ALT-{line_no}-SPEC",
        "替代用量": qty,
        "替代单位": unit,
        "核验单ID": verify_id,
    }
    return sub_service.suggest(values)


def _new_verify(material: str, status: str = "已签认", unit_note: str = "") -> dict:
    rows = store.rows("material_verify")
    entry = {
        "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
        "status": status,
        "pending": status != "已签认",
        "abnormal": status == "已退回",
        "材料名称": material,
        "规格型号": f"{material}-规格{unit_note}",
        "供应商": "测试供应商",
        "送检批次": f"BATCH-{material}",
        "检测报告": f"RPT-{material}",
        "核验人": "测试核验员",
        "核验结果": status,
        "备注说明": "",
    }
    rows.append(entry)
    return entry


# ═══════════════════════════════════════════════════════════════════
# 1. 原清单行、替代规格、核验单在建议中完整保留
# ═══════════════════════════════════════════════════════════════════

def test_suggest_keeps_original_line_spec_and_verify():
    row = _suggest("CL-01", verify_id=4, unit="片", qty=2000)
    assert row["原材料名称"] == "青瓦"
    assert row["原规格型号"] == "28cm x 18cm"
    assert row["原用量"] == 2000
    assert row["原单位"] == "片"
    assert row["替代材料名称"] == "替代-CL-01"
    assert row["替代规格型号"] == "ALT-CL-01-SPEC"
    assert row["核验单ID"] == 4
    assert row["status"] == STATUS_PENDING
    # 原方案的结构化清单行没有被改动
    plan = store.find("restoration_plan", DEMO_PLAN_ID)
    line = next(l for l in plan["plan_lines"] if l["line_no"] == "CL-01")
    assert line["材料名称"] == "青瓦"
    assert line["单位"] == "片"


def test_suggest_must_attach_to_existing_plan_line():
    with pytest.raises(ValueError) as exc:
        _suggest("CL-99", verify_id=4)
    assert "清单行" in str(exc.value)


# ═══════════════════════════════════════════════════════════════════
# 2. 批量采纳只允许同一方案；部分成功并逐行回执
# ═══════════════════════════════════════════════════════════════════

def test_batch_adopt_rejects_cross_plan_selection():
    other_plan_rows = store.rows("restoration_plan")
    other = other_plan_rows[0]
    other["plan_lines"] = [
        {"line_no": "X-1", "材料名称": "别的材料", "规格型号": "S", "用量": 1, "单位": "kg",
         "可独立施工": True}
    ]
    foreign = sub_service.suggest({
        "方案ID": other["id"],
        "清单行号": "X-1",
        "替代材料名称": "外来料",
        "替代规格型号": "F-SPEC",
        "替代用量": 1,
        "替代单位": "kg",
        "核验单ID": 4,
    })
    with pytest.raises(ValueError) as exc:
        sub_service.batch_adopt(DEMO_PLAN_ID, [1, foreign["id"]])
    assert "同一方案" in str(exc.value)


def test_batch_adopt_partial_success_with_receipt():
    # 种子建议：#1 青瓦（可生效）、#4 糯米灰浆单位不一致（退回复核）、#5 石灰核验已退回（退回复核）
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [1, 4, 5])
    effective_ids = [item["替代建议ID"] for item in receipt["生效"]]
    recheck_ids = [item["替代建议ID"] for item in receipt["退回复核"]]
    assert effective_ids == [1]
    assert set(recheck_ids) == {4, 5}

    tile = store.find("material_substitution", 1)
    assert tile["status"] == STATUS_EFFECTIVE
    assert tile["批次号"]
    assert tile["变更签证ID"] is not None

    grout = store.find("material_substitution", 4)
    assert grout["status"] == STATUS_RECHECK
    assert "单位不一致" in grout["复核原因"]
    # 退回行不允许领用，且禁止清单列入回执
    assert "CL-04" in receipt["禁止领用清单行"]


# ═══════════════════════════════════════════════════════════════════
# 3. 单位不一致退回复核，绝不沿用旧单位数值
# ═══════════════════════════════════════════════════════════════════

def test_unit_mismatch_never_reuses_old_value():
    row = _suggest("CL-02", verify_id=4, unit="桶", qty=20)
    eligible, reason = sub_service.evaluate_eligibility(row)
    assert eligible is False
    assert "单位不一致" in reason
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [row["id"]])
    updated = store.find("material_substitution", row["id"])
    assert updated["status"] == STATUS_RECHECK
    assert updated["原用量"] == 500 and updated["原单位"] == "kg"
    # 替代侧仍保留自己单位下的数量，系统没有把 500kg 写成 500桶
    assert updated["替代用量"] == 20 and updated["替代单位"] == "桶"
    assert not receipt["生效"]


# ═══════════════════════════════════════════════════════════════════
# 4. 生效同步方案待审清单 + 工艺变更记录（变更签证）
# ═══════════════════════════════════════════════════════════════════

def test_effective_syncs_plan_pending_list_and_change_order():
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [1, 2])
    assert receipt["变更签证ID"] is not None
    change = store.find("change_order", receipt["变更签证ID"])
    assert change["status"] == "已签认"
    assert "材料替代工艺变更" in change["变更事项"]
    assert set(receipt["批次号"])  # 批次号非空
    # 变更记录写明涉及的清单行，供方案审核使用
    assert "CL-01" in change["变更原因"] and "CL-02" in change["变更原因"]

    plan = store.find("restoration_plan", DEMO_PLAN_ID)
    pending_lines = {item["清单行号"] for item in plan["substitution_pending"]}
    assert pending_lines == {"CL-01", "CL-02"}
    for item in plan["substitution_pending"]:
        assert item["变更签证ID"] == receipt["变更签证ID"]
        assert item["核验单ID"] in (4, 5)


# ═══════════════════════════════════════════════════════════════════
# 5. 待复核/未生效材料禁止领用；生效后可以领用
# ═══════════════════════════════════════════════════════════════════

def test_requisition_blocked_until_effective():
    # 种子 #4 单位不一致 → 待复核
    sub_service.batch_adopt(DEMO_PLAN_ID, [4])
    with pytest.raises(ValueError) as exc:
        sub_service.requisition(4, receiver="施工方张师傅")
    assert "不得领用" in str(exc.value) or "禁止领用" in str(exc.value)

    # 未采纳的建议同样不能领用
    with pytest.raises(ValueError):
        sub_service.requisition(1)

    # 生效后可以领用
    sub_service.batch_adopt(DEMO_PLAN_ID, [1])
    record = sub_service.requisition(1, receiver="施工方张师傅", quantity=2000)
    assert record["领用单位"] == "片"
    assert record["核验单ID"] == 4


# ═══════════════════════════════════════════════════════════════════
# 6. 石灰退回回执迟到：已生效也冻结，审批入口能说明资格
# ═══════════════════════════════════════════════════════════════════

def test_late_verify_return_freezes_effective_substitution():
    # 石灰替代（种子 #2，核验单 #5 已签认）先采纳生效并领用一次
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [2])
    assert [i["替代建议ID"] for i in receipt["生效"]] == [2]
    sub_service.requisition(2, receiver="施工方李师傅", quantity=100)

    # 迟到的退回回执：对核验单 5 执行退回动作
    verify_service.run_action(5, "退回材料")

    lime = store.find("material_substitution", 2)
    assert lime["status"] == STATUS_RECHECK
    assert lime["退回回执"] is True
    assert "退回回执" in lime["复核原因"]

    # 施工方不能继续领用这批待复核石灰
    with pytest.raises(ValueError) as exc:
        sub_service.requisition(2, receiver="施工方李师傅")
    assert "待复核" in str(exc.value)

    # 方案审批入口逐行说明资格与领用限制
    view = sub_service.plan_eligibility(DEMO_PLAN_ID)
    lime_view = next(i for i in view["替代建议"] if i["替代建议ID"] == 2)
    assert lime_view["允许领用"] is False
    assert lime_view["退回回执"] is True
    assert lime_view["核验单状态"] == "已退回"
    assert any(i["清单行号"] == "CL-02" for i in view["待复核清单"])

    # 已经发生的领用记录仍然留在方案里，没有消失
    plan = store.find("restoration_plan", DEMO_PLAN_ID)
    archived = [r for r in plan["requisition_archive"] if r["清单行号"] == "CL-02"]
    assert len(archived) == 1 and archived[0]["领用人"] == "施工方李师傅"
    assert len(lime["领用记录"]) == 1


# ═══════════════════════════════════════════════════════════════════
# 7. 可独立施工清单行互不阻塞：一条退回不影响另一条采纳
# ═══════════════════════════════════════════════════════════════════

def test_independent_lines_one_returning_one_adopted():
    # CL-01（可独立施工，核验#4 已签认）与 CL-02 下挂退回核验#6 的建议 #5 同时提交
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [1, 5])
    assert [i["替代建议ID"] for i in receipt["生效"]] == [1]
    assert [i["替代建议ID"] for i in receipt["退回复核"]] == [5]

    tile = store.find("material_substitution", 1)
    returned_lime = store.find("material_substitution", 5)
    assert tile["status"] == STATUS_EFFECTIVE
    assert returned_lime["status"] == STATUS_RECHECK
    # 生效行可领用，退回行不可领用
    assert sub_service.requisition(1, receiver="瓦工班组")["清单行号"] == "CL-01"
    with pytest.raises(ValueError):
        sub_service.requisition(5)


# ═══════════════════════════════════════════════════════════════════
# 8. 重复提交已生效替换幂等：只生效一次、不新增材料
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_adopt_is_idempotent_and_adds_no_material():
    first = sub_service.batch_adopt(DEMO_PLAN_ID, [1, 2])
    change_count_after_first = len(store.rows("change_order"))
    sub_count_after_first = len(store.rows("material_substitution"))
    first_batch = first["批次号"]

    second = sub_service.batch_adopt(DEMO_PLAN_ID, [1, 2, 1])  # 含重复选择
    assert second["生效"] == []
    assert {i["替代建议ID"] for i in second["幂等跳过"]} == {1, 2}
    # 没有新批次、没有新变更签证、没有新增替代行
    assert second["批次号"] == ""
    assert second["变更签证ID"] is None
    assert len(store.rows("change_order")) == change_count_after_first
    assert len(store.rows("material_substitution")) == sub_count_after_first

    tile = store.find("material_substitution", 1)
    assert tile["批次号"] == first_batch  # 仍归属首个批次


# ═══════════════════════════════════════════════════════════════════
# 9. 被拒绝清单行修订后可再次提交；已领用记录不消失
# ═══════════════════════════════════════════════════════════════════

def test_rejected_line_can_be_revised_and_resubmitted():
    sub_service.batch_adopt(DEMO_PLAN_ID, [1])
    sub_service.requisition(1, receiver="瓦工班组", quantity=500)

    # 审核拒绝该清单行替换（依据工艺变更记录）
    rejected = sub_service.reject(1, reason="替代瓦件色泽与原状不符")
    assert rejected["status"] == STATUS_REJECTED
    plan = store.find("restoration_plan", DEMO_PLAN_ID)
    assert all(item["清单行号"] != "CL-01" for item in plan["substitution_pending"])
    # 领用事实保留在方案归档中
    assert any(r["清单行号"] == "CL-01" for r in plan["requisition_archive"])
    assert len(rejected["领用记录"]) == 1

    # 申请人回到方案：换一批重新签认的核验材料并修订
    new_verify = _new_verify("仿古青瓦-复验", status="已签认")
    revised = sub_service.revise(1, {
        "替代材料名称": "仿古青瓦（复验批次）",
        "替代规格型号": "30cm x 20cm 特级品",
        "核验单ID": new_verify["id"],
    })
    assert revised["status"] == STATUS_PENDING
    assert revised["退回回执"] is False
    # 原清单行快照没有被修订动作破坏
    assert revised["原材料名称"] == "青瓦" and revised["原单位"] == "片"

    # 再次批量采纳：只生效一次，不额外添一条材料
    before = len(store.rows("material_substitution"))
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [1])
    assert [i["替代建议ID"] for i in receipt["生效"]] == [1]
    assert len(store.rows("material_substitution")) == before
    again = store.find("material_substitution", 1)
    assert again["status"] == STATUS_EFFECTIVE
    assert again["变更签证ID"] != revised.get("变更签证ID") or again["批次号"]
    # 历史领用记录仍在同一条建议与方案归档中
    assert len(again["领用记录"]) == 1
    plan = store.find("restoration_plan", DEMO_PLAN_ID)
    assert len([r for r in plan["requisition_archive"] if r["清单行号"] == "CL-01"]) == 1


# ═══════════════════════════════════════════════════════════════════
# 9b. 已拒绝行未修订前不能借批量采纳直接重新生效
# ═══════════════════════════════════════════════════════════════════

def test_rejected_line_must_be_revised_before_readopt():
    sub_service.batch_adopt(DEMO_PLAN_ID, [1])
    sub_service.reject(1, reason="替代瓦件色泽与原状不符")

    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [1])
    assert receipt["生效"] == []
    assert [i["替代建议ID"] for i in receipt["拒绝待修订"]] == [1]
    assert store.find("material_substitution", 1)["status"] == STATUS_REJECTED

    # 修订后重新提交即可生效
    sub_service.revise(1, {"替代材料名称": "仿古青瓦（复验）", "核验单ID": 4})
    receipt2 = sub_service.batch_adopt(DEMO_PLAN_ID, [1])
    assert [i["替代建议ID"] for i in receipt2["生效"]] == [1]
    assert store.find("material_substitution", 1)["status"] == STATUS_EFFECTIVE


# ═══════════════════════════════════════════════════════════════════
# 10. 待复核行修订后（单位补齐一致）重新采纳可生效
# ═══════════════════════════════════════════════════════════════════def test_recheck_line_fixed_unit_can_be_adopted_again():
    sub_service.batch_adopt(DEMO_PLAN_ID, [4])  # 单位不一致 → 待复核
    row = store.find("material_substitution", 4)
    assert row["status"] == STATUS_RECHECK

    revised = sub_service.revise(4, {"替代单位": "kg", "替代用量": 300})
    assert revised["status"] == STATUS_PENDING
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [4])
    assert [i["替代建议ID"] for i in receipt["生效"]] == [4]
    assert store.find("material_substitution", 4)["status"] == STATUS_EFFECTIVE


# ═══════════════════════════════════════════════════════════════════
# 11. 核验单未签认（核验中）的建议同样退回复核
# ═══════════════════════════════════════════════════════════════════

def test_unverified_material_goes_back_to_recheck():
    verifying = _new_verify("待核验木料", status="核验中")
    row = _suggest("CL-03", verify_id=verifying["id"], unit="kg", qty=80)
    receipt = sub_service.batch_adopt(DEMO_PLAN_ID, [row["id"]])
    assert receipt["生效"] == []
    assert receipt["退回复核"][0]["替代建议ID"] == row["id"]
    assert store.find("material_substitution", row["id"])["status"] == STATUS_RECHECK
