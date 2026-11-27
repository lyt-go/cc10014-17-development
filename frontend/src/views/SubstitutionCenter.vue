<template>
  <section class="page substitution-page">
    <header class="page-head">
      <div>
        <h2>材料替代批量采纳</h2>
        <p class="page-desc">
          工程师从材料核验中为同一修缮方案批量采纳替代建议；原清单行、替代规格与核验单全程保留，
          确认结果同步方案待审清单并生成工艺变更记录。
        </p>
      </div>
    </header>

    <div class="plan-bar">
      <label class="plan-select">
        <span>选择修缮方案</span>
        <select v-model.number="planId" data-testid="plan-select" @change="loadEligibility">
          <option v-for="plan in plans" :key="Number(plan.id)" :value="Number(plan.id)">
            {{ plan['方案编号'] }}（{{ plan.status }}）
          </option>
        </select>
      </label>
      <button class="btn" type="button" data-testid="refresh" @click="loadEligibility">刷新资格</button>
      <span v-if="eligibility" class="plan-meta">
        可生效 {{ eligibility.可生效行数 }} 行 · 待复核 {{ eligibility.待复核行数 }} 行 ·
        已拒绝 {{ eligibility.已拒绝行数 }} 行
      </span>
    </div>

    <div v-if="errorMessage" class="banner error" data-testid="error-banner">{{ errorMessage }}</div>

    <div v-if="lastReceipt" class="banner receipt" data-testid="receipt">
      <strong>批次 {{ lastReceipt.批次号 || '（无新生效）' }} 处理回执：</strong>
      生效 {{ lastReceipt.生效.length }} 条，
      退回复核 {{ lastReceipt.退回复核.length }} 条，
      幂等跳过 {{ lastReceipt.幂等跳过.length }} 条，
      拒绝待修订 {{ lastReceipt.拒绝待修订.length }} 条。
      <template v-if="lastReceipt.变更签证ID">
        工艺变更记录（变更签证#{{ lastReceipt.变更签证ID }}）已同步到方案待审清单。
      </template>
      <template v-if="lastReceipt.禁止领用清单行.length">
        <em>禁止领用清单行：{{ lastReceipt.禁止领用清单行.join('、') }}</em>
      </template>
    </div>

    <div v-if="eligibility" class="stat-row">
      <article class="stat-card">
        <span class="stat-label">待审清单（已生效）</span>
        <strong class="stat-value">{{ eligibility.待审清单.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待复核（禁止领用）</span>
        <strong class="stat-value warn">{{ eligibility.待复核行数 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可独立施工清单行</span>
        <strong class="stat-value">{{ independentCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已归档领用记录</span>
        <strong class="stat-value">{{ eligibility.领用归档.length }}</strong>
      </article>
    </div>

    <div class="batch-bar">
      <label>
        <input
          type="checkbox"
          data-testid="select-all"
          :checked="allVisibleSelected"
          :disabled="!eligibility || eligibility.替代建议.length === 0"
          @change="toggleAll"
        />
        全选当前方案
      </label>
      <span class="selected-hint">已选 {{ selectedIds.length }} 条（仅可提交同一方案内的建议）</span>
      <button
        class="btn primary"
        type="button"
        data-testid="batch-adopt"
        :disabled="!selectedIds.length || submitting"
        @click="submitBatch"
      >
        {{ submitting ? '提交中…' : '批量采纳选中建议' }}
      </button>
    </div>

    <table v-if="eligibility" class="data-table substitution-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>清单行</th>
          <th>原清单行（保留）</th>
          <th>替代规格与用量</th>
          <th>核验单</th>
          <th>替代状态</th>
          <th>资格 / 复核说明</th>
          <th>领用与操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in eligibility.替代建议"
          :key="item.替代建议ID"
          :data-testid="`sub-row-${item.替代建议ID}`"
          :data-status="item.替代状态"
          :class="{
            effective: item.已经生效,
            recheck: item.替代状态 === '待复核',
            rejected: item.替代状态 === '已拒绝',
          }"
        >
          <td>
            <input
              type="checkbox"
              :data-testid="`select-${item.替代建议ID}`"
              :value="item.替代建议ID"
              v-model="selectedIds"
            />
          </td>
          <td>
            <strong>{{ item.清单行号 }}</strong>
            <span v-if="item.可独立施工" class="tag tag-indep">可独立施工</span>
            <span v-else class="tag tag-dep">非独立施工</span>
          </td>
          <td class="orig-cell">
            {{ item.原材料名称 }} / {{ item.原规格型号 }}<br />
            <small>原用量 {{ item.原用量 }} {{ item.原单位 }}</small>
          </td>
          <td>
            {{ item.替代材料名称 }} / {{ item.替代规格型号 }}<br />
            <small :class="{ 'unit-warn': item.替代单位 !== item.原单位 }">
              替代用量 {{ item.替代用量 }} {{ item.替代单位 }}
              <template v-if="item.替代单位 !== item.原单位">（单位不一致）</template>
            </small>
          </td>
          <td>
            核验单#{{ item.核验单ID }}
            <br />
            <small :class="item.核验单状态 === '已签认' ? 'verify-ok' : 'verify-bad'">
              {{ item.核验单状态 }}
            </small>
            <span v-if="item.退回回执" class="tag tag-late">退回回执</span>
          </td>
          <td>
            <span class="status-pill" :data-status="item.替代状态">{{ item.替代状态 }}</span>
            <div v-if="item.批次号" class="batch-ref">
              批次{{ item.批次号 }}
              <template v-if="item.变更签证ID"> / 签证#{{ item.变更签证ID }}</template>
            </div>
          </td>
          <td class="reason-cell">
            <template v-if="item.已经生效">核验签认、单位一致，替换已生效</template>
            <template v-else-if="item.有资格生效">有资格生效，可随批次采纳</template>
            <template v-else>{{ item.资格说明 || item.复核原因 || item.拒绝原因 || '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`requisition-${item.替代建议ID}`"
              :disabled="!item.允许领用"
              :title="item.允许领用 ? '' : '待复核/未生效材料禁止领用'"
              @click="requisition(item)"
            >
              领用（{{ item.已领用次数 }}）
            </button>
            <button
              v-if="item.已经生效"
              class="link danger"
              type="button"
              :data-testid="`reject-${item.替代建议ID}`"
              @click="reject(item)"
            >
              拒绝替换
            </button>
            <button
              v-if="item.替代状态 === '待复核' || item.替代状态 === '已拒绝'"
              class="link"
              type="button"
              :data-testid="`revise-${item.替代建议ID}`"
              @click="openRevise(item)"
            >
              修订重提
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="eligibility && eligibility.替代建议.length === 0" class="empty-state">
      该方案暂无材料替代建议。
    </div>

    <section v-if="eligibility && eligibility.领用归档.length" class="archive-block">
      <h3>方案内实际领用记录（拒绝或退回均不删除）</h3>
      <ul>
        <li v-for="(record, idx) in eligibility.领用归档" :key="idx">
          {{ record['领用时间'] }} · {{ record['清单行号'] }} · {{ record['材料名称'] }}
          （{{ record['规格型号'] }}）· 领用 {{ record['领用数量'] }} {{ record['领用单位'] }}
          · 领用人 {{ record['领用人'] }}
        </li>
      </ul>
    </section>

    <div v-if="showRevise" class="modal-backdrop" data-testid="revise-modal">
      <form class="modal" @submit.prevent="submitRevise">
        <h3>修订替代建议 #{{ reviseForm.id }}（清单行 {{ reviseForm.清单行号 }}）</h3>
        <p class="modal-hint">只能修订替代侧信息与核验单；原清单行材料、规格和单位不允许修改。</p>
        <label class="create-field">
          <span>替代材料名称</span>
          <input v-model="reviseForm.替代材料名称" required />
        </label>
        <label class="create-field">
          <span>替代规格型号</span>
          <input v-model="reviseForm.替代规格型号" required />
        </label>
        <label class="create-field">
          <span>替代用量（须按原单位 {{ reviseForm.原单位 }} 重新核算）</span>
          <input v-model="reviseForm.替代用量" required />
        </label>
        <label class="create-field">
          <span>替代单位</span>
          <input v-model="reviseForm.替代单位" required />
        </label>
        <label class="create-field">
          <span>核验单ID</span>
          <input v-model.number="reviseForm.核验单ID" type="number" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showRevise = false">取消</button>
          <button class="btn primary" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '保存并回到待采纳' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else>批量采纳按行回执：合格即生效，单位不一致或核验未签认一律退回复核。</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { listEntries } from '@/api/backend-service'
import {
  batchAdopt,
  fetchPlanEligibility,
  rejectSubstitution,
  requisitionMaterial,
  reviseSubstitution,
  type BatchReceipt,
  type EligibilityItem,
  type PlanEligibility,
} from '@/api/substitution'
import type { EntryRow } from '@/data/types'

type ReviseForm = {
  id: number
  清单行号: string
  原单位: string
  替代材料名称: string
  替代规格型号: string
  替代用量: number | string
  替代单位: string
  核验单ID: number
}

const emptyReviseForm: ReviseForm = {
  id: 0,
  清单行号: '',
  原单位: '',
  替代材料名称: '',
  替代规格型号: '',
  替代用量: '',
  替代单位: '',
  核验单ID: 0,
}

const plans = ref<EntryRow[]>([])
const planId = ref(4)
const eligibility = ref<PlanEligibility | null>(null)
const selectedIds = ref<number[]>([])
const errorMessage = ref('')
const submitting = ref(false)
const lastReceipt = ref<BatchReceipt | null>(null)
const showRevise = ref(false)
const reviseForm = ref<ReviseForm>({ ...emptyReviseForm })

const independentCount = computed(() =>
  (eligibility.value?.替代建议 ?? []).filter((item) => item.可独立施工).length,
)

const allVisibleSelected = computed(() => {
  const items = eligibility.value?.替代建议 ?? []
  return items.length > 0 && items.every((item) => selectedIds.value.includes(item.替代建议ID))
})

function toggleAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedIds.value = checked
    ? (eligibility.value?.替代建议 ?? []).map((item) => item.替代建议ID)
    : []
}

async function loadPlans() {
  try {
    const payload = await listEntries('restoration_plan', {})
    plans.value = payload.items
    if (!plans.value.some((plan) => Number(plan.id) === planId.value) && plans.value.length) {
      planId.value = Number(plans.value[0].id)
    }
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '修缮方案列表读取失败'
  }
}

async function loadEligibility() {
  errorMessage.value = ''
  lastReceipt.value = null
  try {
    eligibility.value = await fetchPlanEligibility(planId.value)
    selectedIds.value = []
  } catch (e) {
    eligibility.value = null
    errorMessage.value = e instanceof Error ? e.message : '资格视图读取失败'
  }
}

async function submitBatch() {
  if (!selectedIds.value.length) return
  submitting.value = true
  errorMessage.value = ''
  try {
    const result = await batchAdopt(planId.value, [...selectedIds.value])
    lastReceipt.value = result.receipt
    await loadEligibility()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '批量采纳失败'
  } finally {
    submitting.value = false
  }
}

async function requisition(item: EligibilityItem) {
  const receiver = window.prompt(`施工方领用清单行 ${item.清单行号} 的替代材料，请输入领用人`, '施工方')
  if (!receiver) return
  try {
    await requisitionMaterial(item.替代建议ID, receiver)
    await loadEligibility()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '领用失败'
  }
}

async function reject(item: EligibilityItem) {
  const reason = window.prompt(`拒绝清单行 ${item.清单行号} 的替换，请填写审核意见`, '工艺变更审核未通过')
  if (!reason) return
  try {
    await rejectSubstitution(item.替代建议ID, reason)
    await loadEligibility()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '拒绝失败'
  }
}

function openRevise(item: EligibilityItem) {
  reviseForm.value = {
    id: item.替代建议ID,
    清单行号: item.清单行号,
    原单位: item.原单位,
    替代材料名称: item.替代材料名称,
    替代规格型号: item.替代规格型号,
    替代用量: item.替代用量,
    替代单位: item.替代单位,
    核验单ID: item.核验单ID,
  }
  showRevise.value = true
}

async function submitRevise() {
  submitting.value = true
  try {
    await reviseSubstitution(reviseForm.value.id, {
      替代材料名称: reviseForm.value.替代材料名称,
      替代规格型号: reviseForm.value.替代规格型号,
      替代用量: reviseForm.value.替代用量,
      替代单位: reviseForm.value.替代单位,
      核验单ID: reviseForm.value.核验单ID,
    })
    showRevise.value = false
    await loadEligibility()
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '修订失败'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadPlans()
  await loadEligibility()
})
</script>

<style scoped>
.plan-bar { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.plan-select { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.plan-select select { padding: 6px 10px; border: 1px solid var(--border-color, #e2e8f0); border-radius: 4px; min-width: 260px; }
.plan-meta { color: var(--text-secondary, #4a5568); font-size: 13px; }
.banner { border-radius: 6px; padding: 10px 14px; margin-bottom: 14px; font-size: 13px; line-height: 1.7; }
.banner.receipt { background: #f0fff4; border: 1px solid #9ae6b4; }
.banner.error { background: #fff5f5; border: 1px solid #feb2b2; color: #c53030; }
.banner em { color: #c53030; font-style: normal; margin-left: 8px; }
.batch-bar { display: flex; align-items: center; gap: 18px; padding: 10px 0; border-top: 1px solid var(--border-color, #e2e8f0); border-bottom: 1px solid var(--border-color, #e2e8f0); margin-bottom: 12px; }
.selected-hint { color: var(--text-secondary, #4a5568); font-size: 13px; flex: 1; }
.substitution-table td, .substitution-table th { vertical-align: top; font-size: 13px; }
.substitution-table tr.effective { background: #f0fff4; }
.substitution-table tr.recheck { background: #fffaf0; }
.substitution-table tr.rejected { background: #fff5f5; }
.tag { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 12px; margin-left: 6px; }
.tag-indep { background: #bee3f8; color: #2a4365; }
.tag-dep { background: #edf2f7; color: #4a5568; }
.tag-late { background: #fed7d7; color: #9b2c2c; }
.status-pill { padding: 2px 10px; border-radius: 12px; background: #edf2f7; font-size: 12px; white-space: nowrap; }
.status-pill[data-status='已生效'] { background: #c6f6d5; color: #22543d; }
.status-pill[data-status='待复核'] { background: #feebc8; color: #7b341e; }
.status-pill[data-status='已拒绝'] { background: #fed7d7; color: #822727; }
.batch-ref { font-size: 12px; color: var(--text-secondary, #4a5568); margin-top: 4px; }
.unit-warn, .verify-bad { color: #c05621; font-weight: 600; }
.verify-ok { color: #2f855a; }
.reason-cell { max-width: 280px; line-height: 1.6; }
.orig-cell { max-width: 220px; line-height: 1.6; }
.row-actions { white-space: nowrap; }
.link.danger { color: #c53030; }
.link:disabled { color: #a0aec0; cursor: not-allowed; }
.archive-block { margin-top: 20px; padding: 14px 18px; background: #f7fafc; border: 1px solid var(--border-color, #e2e8f0); border-radius: 6px; }
.archive-block h3 { margin: 0 0 8px; font-size: 14px; }
.archive-block ul { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.9; color: #2d3748; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, .35); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 8px; padding: 24px; width: 520px; max-height: 85vh; overflow-y: auto; }
.modal-hint { font-size: 12px; color: var(--text-secondary, #4a5568); margin: 4px 0 14px; }
.create-field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
.create-field span { font-size: 13px; color: var(--text-secondary, #4a5568); }
.create-field input { padding: 6px 8px; border: 1px solid var(--border-color, #e2e8f0); border-radius: 4px; font-size: 13px; }
.stat-value.warn { color: #c05621; }
.empty-state { text-align: center; padding: 32px; color: var(--text-secondary, #4a5568); }
</style>
