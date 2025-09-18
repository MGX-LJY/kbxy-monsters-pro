import React, { useEffect, useMemo, useState } from 'react'
import SideDrawer from './SideDrawer'
import TagSelector from './TagSelector'
import api from '../api'

type SkillRow = { name: string; description: string }

type Props = {
  open: boolean
  editId?: number
  onClose: () => void
  onCreated?: (monsterId: number) => void
  onUpdated?: (monsterId: number) => void
}

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v))

export default function AddMonsterDrawer({ open, editId, onClose, onCreated, onUpdated }: Props) {
  const isEdit = !!editId
  const [nameFinal, setNameFinal] = useState('')
  const [element, setElement] = useState('')
  const [role, setRole] = useState('')
  const [type, setType] = useState('')

  // 六维
  const [hp, setHp] = useState(100)
  const [speed, setSpeed] = useState(100)
  const [attack, setAttack] = useState(100)
  const [defense, setDefense] = useState(100)
  const [magic, setMagic] = useState(100)
  const [resist, setResist] = useState(100)

  const [tagsInput, setTagsInput] = useState('')
  const [skills, setSkills] = useState<SkillRow[]>([{ name: '', description: '' }])
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [extractRaw, setExtractRaw] = useState('')
  const [extracting, setExtracting] = useState(false)

  const sum = useMemo(() => hp + speed + attack + defense + magic + resist, [hp, speed, attack, defense, magic, resist])

  const base_offense = attack
  const base_survive = hp
  const base_control = (defense + magic) / 2
  const base_tempo = speed
  const base_pp = resist

  const addSkill = () => setSkills(prev => [...prev, { name: '', description: '' }])
  const removeSkill = (idx: number) => setSkills(prev => prev.filter((_, i) => i !== idx))
  const updateSkill = (idx: number, key: keyof SkillRow, val: string) =>
    setSkills(prev => prev.map((s, i) => (i === idx ? { ...s, [key]: val } : s)))

  const resetAll = () => {
    setNameFinal(''); setElement(''); setRole(''); setType('')
    setHp(100); setSpeed(100); setAttack(100); setDefense(100); setMagic(100); setResist(100)
    setTagsInput(''); setSkills([{ name: '', description: '' }]); setErr(null); setExtractRaw('')
  }

  // 编辑模式：加载详情 + 技能
  useEffect(() => {
    const load = async () => {
      if (!open || !isEdit || !editId) return
      try {
        const [detail, sk] = await Promise.all([
          api.get(`/monsters/${editId}`),
          api.get(`/monsters/${editId}/skills`)
        ])
        const d = detail.data
        setNameFinal(d.name_final || d.name || '')
        setElement(d.element || '')
        setRole(d.role || '')
        setType(d.type || '')
        // 原始六维如有则用原始，否则用折算
        const raw = d.explain_json?.raw_stats
        if (raw) {
          setHp(raw.hp ?? 100); setSpeed(raw.speed ?? 100); setAttack(raw.attack ?? 100)
          setDefense(raw.defense ?? 100); setMagic(raw.magic ?? 100); setResist(raw.resist ?? 100)
        } else {
          setHp(d.base_survive ?? 100); setSpeed(d.base_tempo ?? 100); setAttack(d.base_offense ?? 100)
          // 没有单独防御/法术，只能从 control 反推，这里保持为 (control, control)
          setDefense(d.base_control ?? 100); setMagic(d.base_control ?? 100); setResist(d.base_pp ?? 100)
        }
        setTagsInput((d.tags || []).join(' '))
        const arr = (sk.data || []).map((s: any) => ({ name: s.name || '', description: s.description || '' }))
        setSkills(arr.length ? arr : [{ name: '', description: '' }])
      } catch (e) {
        // ignore
      }
    }
    load()
  }, [open, isEdit, editId])

  const onSubmit = async () => {
    if (!nameFinal.trim()) { setErr('请填写名称'); return }
    setSubmitting(true); setErr(null)
    try {
      const payload = {
        name_final: nameFinal.trim(),
        element: element || null,
        role: role || null,
        type: type || null,
        base_offense, base_survive, base_control, base_tempo, base_pp,
        tags: tagsInput.split(/[\s,，、;；]+/).map(s => s.trim()).filter(Boolean),
        skills: skills
          .filter(s => s.name.trim())
          .map(s => ({ name: s.name.trim(), description: s.description?.trim() || '' })),
      }
      if (isEdit && editId) {
        const res = await api.put(`/monsters/${editId}`, payload)
        onUpdated?.(res.data?.id)
      } else {
        const res = await api.post('/monsters', payload)
        onCreated?.(res.data?.id)
      }
      resetAll()
      onClose()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const extractFromText = async () => {
    if (!extractRaw.trim()) return
    setExtracting(true)
    try {
      const { data } = await api.post('/utils/extract', { text: extractRaw })
      if (data?.name && !nameFinal) setNameFinal(data.name)
      if (data?.stats) {
        const s = data.stats
        if (typeof s.hp === 'number') setHp(s.hp)
        if (typeof s.speed === 'number') setSpeed(s.speed)
        if (typeof s.attack === 'number') setAttack(s.attack)
        if (typeof s.defense === 'number') setDefense(s.defense)
        if (typeof s.magic === 'number') setMagic(s.magic)
        if (typeof s.resist === 'number') setResist(s.resist)
      }
      const arr: SkillRow[] = (data?.skills || []).filter((s:any)=>s?.name)
      if (arr.length) {
        setSkills(prev => {
          const names = new Set(prev.map(p => p.name.trim()))
          const merged = [...prev]
          arr.forEach(it => {
            if (names.has(it.name.trim())) {
              merged.forEach(m => { if (m.name.trim() === it.name.trim()) m.description = it.description || m.description })
            } else {
              merged.push({ name: it.name.trim(), description: it.description || '' })
            }
          })
          return merged
        })
      }
      setExtractRaw('')
    } catch (e:any) {
      setErr(e?.response?.data?.detail || '识别失败')
    } finally {
      setExtracting(false)
    }
  }

  return (
    <SideDrawer open={open} onClose={onClose} title={isEdit ? '编辑宠物' : '新增宠物'}>
      <div className="space-y-5">
        {/* 智能识别 */}
        <div className="card p-3 space-y-2">
          <label className="label">智能识别（粘贴原文，自动提取六维 + 技能）</label>
          <textarea
            className="input h-24"
            placeholder="例：岚羽箭雕 115 113 120 107 96 94  疾袭贯羽 72 风 物理 165 5 无视对手防御提升的效果..."
            value={extractRaw}
            onChange={e => setExtractRaw(e.target.value)}
          />
          <div className="flex justify-end">
            <button className="btn" onClick={extractFromText} disabled={extracting}>
              {extracting ? '识别中...' : '识别并填入'}
            </button>
          </div>
        </div>

        {/* 基本信息 */}
        <div className="card p-3 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="md:col-span-2">
              <label className="label">名称</label>
              <input className="input" value={nameFinal} onChange={e => setNameFinal(e.target.value)} placeholder="如：九天战猫" />
            </div>
            <div>
              <label className="label">元素</label>
              <select className="select" value={element} onChange={e => setElement(e.target.value)}>
                <option value="">未设置</option>
                <option value="金">金</option>
                <option value="木">木</option>
                <option value="水">水</option>
                <option value="火">火</option>
                <option value="土">土</option>
              </select>
            </div>
            <div>
              <label className="label">定位</label>
              <select className="select" value={role} onChange={e => setRole(e.target.value)}>
                <option value="">未设置</option>
                <option value="主攻">主攻</option>
                <option value="控制">控制</option>
                <option value="辅助">辅助</option>
                <option value="坦克">坦克</option>
                <option value="通用">通用</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="label">获取分类</label>
              <select className="select" value={type} onChange={e => setType(e.target.value)}>
                <option value="">未设置</option>
                <option value="无双宠物">无双宠物</option>
                <option value="神宠">神宠</option>
                <option value="珍宠">珍宠</option>
                <option value="罗盘宠物">罗盘宠物</option>
                <option value="BOSS宠物">BOSS宠物</option>
                <option value="可捕捉宠物">可捕捉宠物</option>
                <option value="VIP宠物">VIP宠物</option>
                <option value="商城宠物">商城宠物</option>
                <option value="任务宠物">任务宠物</option>
                <option value="超进化宠物">超进化宠物</option>
                <option value="活动宠物">活动宠物</option>
                <option value="其他宠物">其他宠物</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <TagSelector
                value={tagsInput}
                onChange={setTagsInput}
                placeholder="如：强攻 控场 PP压制"
                className="w-full"
              />
            </div>
          </div>
        </div>

        {/* 六维 */}
        <div className="card p-3 space-y-3">
          <h4 className="font-semibold">基础种族值（六维）</h4>
          <div className="space-y-3">
            {[
              ['体力', hp, setHp],
              ['速度', speed, setSpeed],
              ['攻击', attack, setAttack],
              ['防御', defense, setDefense],
              ['法术', magic, setMagic],
              ['抗性', resist, setResist],
            ].map(([label, val, setter]: any) => (
              <div key={label} className="grid grid-cols-6 gap-2 items-center">
                <div className="text-sm text-gray-600">{label}</div>
                <input
                  type="range" min={50} max={150} step={1}
                  value={val}
                  onChange={e => (setter as any)(clamp(parseInt(e.target.value,10), 0, 999))}
                  className="col-span-4"
                />
                <input
                  className="input py-1"
                  value={val}
                  onChange={e => (setter as any)(clamp(parseInt(e.target.value || '0', 10), 0, 999))}
                />
              </div>
            ))}
          </div>
          <div className="p-2 bg-gray-50 rounded text-sm text-center">
            六维总和：<b>{sum}</b>
          </div>
          <div className="text-xs text-gray-500">
            * 提交时换算为：攻={base_offense} 生={base_survive} 控={(base_control).toFixed(1)} 速={base_tempo} PP={base_pp}
          </div>
        </div>

        {/* 技能 */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="font-semibold">技能（可添加多个）</h4>
            <button className="btn" onClick={addSkill}>+ 添加技能</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {skills.map((s, idx) => (
              <div key={idx} className="card p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <input className="input flex-1" value={s.name} onChange={e => updateSkill(idx, 'name', e.target.value)} placeholder={`技能 ${idx+1} 名称`} />
                  <button className="btn" onClick={() => removeSkill(idx)} disabled={skills.length === 1}>删除</button>
                </div>
                <textarea className="input h-24" value={s.description} onChange={e => updateSkill(idx, 'description', e.target.value)} placeholder="技能描述" />
              </div>
            ))}
          </div>
        </div>

        {err && <div className="text-red-600 text-sm">{err}</div>}

        <div className="flex justify-end gap-2">
          <button className="btn" onClick={() => { resetAll(); onClose() }}>取消</button>
          <button className="btn primary" onClick={onSubmit} disabled={submitting}>
            {submitting ? '提交中...' : (isEdit ? '保存修改' : '保存')}
          </button>
        </div>
      </div>
    </SideDrawer>
  )
}