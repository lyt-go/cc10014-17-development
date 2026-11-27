# 古建筑修缮管理平台

文保工程师、工匠和监理共同管理古建筑修缮工序，审核修缮方案，签收变更后按确认版施工。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 建筑勘查 | `building_survey` | 勘查记录 | 建筑名称、勘查部位、病害类型 |
| 修缮方案 | `restoration_plan` | 修缮方案 | 方案编号、对应勘查、修缮工艺 |
| 材料核验 | `material_verify` | 材料核验单 | 材料名称、规格型号、供应商 |
| 材料替代 | `material_substitution` | 材料替代建议 | 原清单行、替代规格、核验单ID、替代状态、批次号 |
| 工匠分配 | `craftsman_assign` | 工匠分配单 | 工匠姓名、技艺类别、资质等级 |
| 工序编排 | `work_sequence` | 工序卡 | 工序名称、前置工序、所需工匠 |
| 质量检查 | `quality_inspect` | 检查记录 | 检查工序、检查项目、技术标准 |
| 历史图纸 | `historical_drawing` | 历史图纸 | 图纸编号、绘制年代、绘制内容 |
| 构件登记 | `component_registry` | 构件档案 | 构件名称、所属建筑、材质类型 |
| 环境监测 | `env_monitor` | 监测数据 | 监测位置、温度读数、湿度读数 |
| 修缮日志 | `restoration_log` | 施工日志 | 施工日期、对应工序、施工内容 |
| 验收记录 | `acceptance_record` | 验收报告 | 验收工序、验收标准、验收结论 |
| 修缮支出 | `funding_use` | 支出记录 | 支出项目、支出类别、预算金额 |
| 档案归档 | `archive_mgmt` | 修缮档案 | 档案名称、档案类别、形成日期 |
| 专家评审 | `expert_review` | 评审意见 | 评审方案、专家姓名、专业领域 |
| 安全交底 | `safety_briefing` | 交底记录 | 交底工序、危险源、防护措施 |
| 施工排期 | `construction_schedule` | 排期计划 | 计划工序、开始日期、结束日期 |
| 变更签证 | `change_order` | 变更签证单 | 变更事项、变更原因、影响工序 |
| 竣工总结 | `completion_summary` | 竣工报告 | 修缮项目、开工日期、竣工日期 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 材料替代批量采纳

工程师在「替代批量采纳」工作台（路由 `/material-substitution`）从材料核验中为
同一修缮方案选择多条替代建议，批量提交后逐行回执：

- 一条替代必须挂靠并保留原清单行（材料/规格/用量/单位快照）、替代规格和对应核验单，
  原清单行任何环节都不被覆盖。
- 核验单已签认且用量单位一致才生效；核验未签认（含退回中）或单位不一致的建议
  退回复核，单位不一致时绝不沿用旧单位数值。
- 每个生效批次生成一条工艺变更记录（`change_order` 变更签证），确认结果同步到
  方案的 `substitution_pending` 待审清单，审核时据此操作；待复核行进入
  `substitution_recheck` 并标明禁止领用。
- 核验单退回（含已生效后的迟到退回回执）联动替代建议转待复核并冻结领用；
  施工方只能领用 `已生效` 且核验仍有效的材料，已发生的领用记录归档在方案
  `requisition_archive` 中，拒绝或退回都不会删除。
- 重复提交已生效替换幂等跳过，只生效一次、不新增材料行；被拒绝/待复核的清单行
  修订替代侧信息（原清单行不可改）后可重新提交。
- 可独立施工的清单行互不阻塞：同批中一条退回不影响另一条采纳。

专用接口（见 `backend/app/routers/substitution.py`）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/material-substitution/plans/{plan_id}/batch-adopt` | 批量采纳，返回逐行回执 |
| GET | `/api/material-substitution/plans/{plan_id}/eligibility` | 方案审批资格视图 |
| POST | `/api/material-substitution/{id}/requisition` | 施工方领用（待复核自动拦截） |
| POST | `/api/material-substitution/{id}/reject` | 审核拒绝清单行替换 |
| POST | `/api/material-substitution/{id}/revise` | 申请人修订后重新提交 |

领域：应用开发
子方向：web前端/全栈开发
