/** 材料替代批量采纳专用接口：与后端 routers/substitution.py 对齐。 */
import { request } from './client'

export type LineSummary = {
  替代建议ID: number
  清单行号: string
  原材料名称: string
  原规格型号: string
  替代材料名称: string
  替代规格型号: string
  替代用量: number | string
  替代单位: string
  核验单ID: number
  替代状态: string
  说明: string
}

export type BatchReceipt = {
  方案ID: number
  方案编号: string
  操作人: string
  处理时间: string
  生效: LineSummary[]
  退回复核: LineSummary[]
  幂等跳过: LineSummary[]
  拒绝待修订: LineSummary[]
  批次号: string
  变更签证ID: number | null
  禁止领用清单行: string[]
}

export type EligibilityItem = {
  替代建议ID: number
  清单行号: string
  可独立施工: boolean
  原材料名称: string
  原规格型号: string
  原用量: number | string
  原单位: string
  替代材料名称: string
  替代规格型号: string
  替代用量: number | string
  替代单位: string
  核验单ID: number
  核验单状态: string
  替代状态: string
  有资格生效: boolean
  已经生效: boolean
  资格说明: string
  批次号: string
  变更签证ID: number | null
  复核原因: string
  拒绝原因: string
  退回回执: boolean
  允许领用: boolean
  已领用次数: number
}

export type PlanEligibility = {
  方案ID: number
  方案编号: string
  方案状态: string
  原清单行: Record<string, unknown>[]
  待审清单: Record<string, unknown>[]
  待复核清单: Record<string, unknown>[]
  替代建议: EligibilityItem[]
  可生效行数: number
  待复核行数: number
  已拒绝行数: number
  领用归档: Record<string, unknown>[]
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(payload) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail ?? '请求失败')
  return data as T
}

export async function fetchPlanEligibility(planId: number): Promise<PlanEligibility> {
  const response = await request(`/api/material-substitution/plans/${planId}/eligibility`)
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail ?? '方案资格视图读取失败')
  }
  return await response.json()
}

export async function batchAdopt(
  planId: number,
  substitutionIds: number[],
  applicant?: string,
): Promise<{ ok: boolean; message: string; receipt: BatchReceipt }> {
  return postJson(`/api/material-substitution/plans/${planId}/batch-adopt`, {
    substitution_ids: substitutionIds,
    applicant: applicant ?? null,
  })
}

export async function requisitionMaterial(
  substitutionId: number,
  receiver: string,
): Promise<{ ok: boolean; message: string; entry: Record<string, unknown> }> {
  return postJson(`/api/material-substitution/${substitutionId}/requisition`, {
    receiver,
    quantity: null,
  })
}

export async function rejectSubstitution(
  substitutionId: number,
  reason: string,
): Promise<{ ok: boolean; message: string; entry: Record<string, unknown> }> {
  return postJson(`/api/material-substitution/${substitutionId}/reject`, { reason })
}

export async function reviseSubstitution(
  substitutionId: number,
  values: Record<string, string | number>,
): Promise<{ ok: boolean; message: string; entry: Record<string, unknown> }> {
  return postJson(`/api/material-substitution/${substitutionId}/revise`, { values })
}
