// client/src/types.ts
export type Derived = {
  offense: number
  survive: number
  control: number
  tempo: number
  pp: number
  tags: string[]
  role_suggested?: string | null
}

export type Monster = {
  id: number
  name_final: string
  element?: string | null
  role?: string | null

  // 旧五维字段（保留，但列表不展示它们）
  base_offense: number
  base_survive: number
  base_control: number
  base_tempo: number
  base_pp: number

  tags: string[]
  explain_json: Record<string, any>

  // 新增：后端实时返回的派生五维
  derived: Derived
}

export type MonsterListResp = {
  items: Monster[]
  total: number
  has_more: boolean
  etag: string
}

export type ImportPreviewResp = {
  columns: string[]
  total_rows: number
  sample: Record<string, string>[]
  hints: string[]
}

export type ImportCommitResp = {
  inserted: number
  updated: number
  skipped: number
  errors: Array<Record<string, any>>
}

export type TagCount = { name: string, count: number }