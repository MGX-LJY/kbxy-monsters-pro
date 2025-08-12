// 基本类型与后端保持一致

export interface Derived {
  offense: number
  survive: number
  control: number
  tempo: number
  pp_pressure: number
}

export interface Monster {
  id: number
  name_final: string
  element?: string | null
  role?: string | null

  // 原始六维：直接来自数据库列
  hp: number
  speed: number
  attack: number
  defense: number
  magic: number
  resist: number

  tags: string[]
  explain_json?: Record<string, any>
  derived?: Derived
}

export interface MonsterListResp {
  items: Monster[]
  total: number
  has_more: boolean
  etag: string
}

export interface TagCount {
  name: string
  count: number
}

export interface StatsDTO {
  total: number
  with_skills: number
  tags_total: number
}