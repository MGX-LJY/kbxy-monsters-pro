// client/src/types.ts

/** ===== Derived（派生五维） ===== */
export interface Derived {
  offense: number
  survive: number
  control: number
  tempo: number
  pp_pressure: number
}

/** ===== Monster（已适配新后端） =====
 * - name_final → name
 * - 新增 possess/new_type/type/method
 * - 新增 created_at/updated_at（ISO 字符串）
 */
export interface Monster {
  id: number
  name: string
  element?: string | null
  role?: string | null

  // 原始六维（直接来自数据库列）
  hp: number
  speed: number
  attack: number
  defense: number
  magic: number
  resist: number

  // 拥有/获取相关
  possess?: boolean
  new_type?: boolean | null
  type?: string | null
  method?: string | null

  tags: string[]
  explain_json?: Record<string, any>
  derived?: Derived

  created_at?: string | null
  updated_at?: string | null
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

/** ===== Import Wizard ===== */

export type ImportPreviewRow = Record<
  string,
  string | number | boolean | null | undefined
>

export interface ImportPreviewResp {
  columns: string[]
  total_rows: number
  hints?: string[]
  sample: ImportPreviewRow[]
}

export interface ImportCommitResp {
  inserted: number
  updated: number
  skipped: number
  errors?: Array<Record<string, unknown>>
}

/** ===== Collections（收藏夹相关，便于前端对接） ===== */

export interface Collection {
  id: number
  name: string
  color?: string | null
  items_count: number
  last_used_at?: string | null
  created_at: string
  updated_at: string
}

export interface CollectionListResp {
  items: Collection[]
  total: number
  has_more: boolean
  etag: string
}

export type CollectionAction = 'add' | 'remove' | 'set'

export interface CollectionBulkSetReq {
  collection_id?: number
  name?: string
  ids: number[]
  action?: CollectionAction
}

export interface CollectionBulkSetResp {
  ok: boolean
  collection_id: number
  affected: number
  action: CollectionAction
}

export interface CollectionCreateReq {
  name: string
  color?: string | null
}

export interface CollectionUpdateReq {
  name?: string
  color?: string | null
}