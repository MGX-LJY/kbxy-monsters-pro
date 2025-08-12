export type Monster = {
  id: number
  name_final: string
  element?: string | null
  role?: string | null
  base_offense: number
  base_survive: number
  base_control: number
  base_tempo: number
  base_pp: number
  tags: string[]
  explain_json: Record<string, any>
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
