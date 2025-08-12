import React, { useMemo, useState } from 'react'
import api from '../api'
import { ImportPreviewResp, ImportCommitResp } from '../types'

export default function ImportWizard(){
  const [file, setFile] = useState<File | null>(null)
  const [step, setStep] = useState<1|2|3>(1)
  const [preview, setPreview] = useState<ImportPreviewResp | null>(null)
  const [result, setResult] = useState<ImportCommitResp | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submitPreview = async () => {
    if(!file) return
    setLoading(true); setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/import/preview', fd)
      setPreview(res.data)
      setStep(2)
    } catch (e: any) {
      const trace = e?.__traceId ? `（trace_id: ${e.__traceId}）` : ''
      setError(`预览失败：${e?.message || e}${trace}`)
    } finally { setLoading(false) }
  }

  const submitCommit = async () => {
    if(!file) return
    setLoading(true); setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/import/commit', fd, {
        headers: { 'Idempotency-Key': crypto.randomUUID() }
      })
      setResult(res.data)
      setStep(3)
    } catch (e: any) {
      const trace = e?.__traceId ? `（trace_id: ${e.__traceId}）` : ''
      setError(`提交失败：${e?.message || e}${trace}`)
    } finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <ol className="flex items-center gap-2 text-sm">
        <li className={step>=1 ? 'font-semibold' : 'text-gray-400'}>1. 上传</li>
        <span>→</span>
        <li className={step>=2 ? 'font-semibold' : 'text-gray-400'}>2. 预览</li>
        <span>→</span>
        <li className={step>=3 ? 'font-semibold' : 'text-gray-400'}>3. 提交导入</li>
      </ol>

      {error && <div className="p-2 border border-red-200 bg-red-50 text-red-700 text-sm rounded">{error}</div>}

      {step === 1 && (
        <div className="space-y-3">
          <input type="file" onChange={e => setFile(e.target.files?.[0] || null)} />
          <div className="text-xs text-gray-500">支持 CSV/TSV；编码 UTF-8；表头示例：name_final,element,role,base_offense,base_survive,base_control,base_tempo,base_pp,tags</div>
          <button className="btn btn-primary" disabled={!file || loading} onClick={submitPreview}>预览</button>
        </div>
      )}

      {step === 2 && preview && (
        <div className="space-y-3">
          <div className="text-sm text-gray-600">列：{preview.columns.join(', ')}</div>
          <div className="text-sm text-gray-600">总行数：{preview.total_rows}</div>
          {preview.hints?.length > 0 && <div className="text-sm text-red-600">提示：{preview.hints.join('；')}</div>}
          <div className="overflow-auto border rounded-xl">
            <table className="table">
              <thead><tr>{preview.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {preview.sample.map((row, i) => (
                  <tr key={i}>
                    {preview.columns.map(c => <td key={c}>{row[c]}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn" onClick={()=>setStep(1)}>返回修改</button>
            <button className="btn btn-primary" disabled={loading} onClick={submitCommit}>提交导入</button>
          </div>
        </div>
      )}

      {step === 3 && result && (
        <div className="space-y-2">
          <div className="text-sm">插入：<b>{result.inserted}</b> · 更新：<b>{result.updated}</b> · 跳过：<b>{result.skipped}</b></div>
          {result.errors?.length > 0 && <pre className="bg-gray-50 p-2 rounded text-xs overflow-auto">{JSON.stringify(result.errors, null, 2)}</pre>}
          <button className="btn" onClick={()=>setStep(1)}>继续导入</button>
        </div>
      )}
    </div>
  )
}
