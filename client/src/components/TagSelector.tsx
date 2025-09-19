import React, { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

// API types
interface TagI18n {
  [code: string]: string
}

interface TagSchema {
  groups: {
    [category: string]: string[]
  }
  default: string
}

// Component props
interface TagSelectorProps {
  value: string // Current tags as space-separated string
  onChange: (newTags: string) => void
  monsterId?: number // For AI suggestions
  placeholder?: string
  className?: string
}

// API base URL
const baseURL = import.meta.env?.VITE_API_BASE ?? 'http://localhost:8000'

// Fetch tag metadata
const fetchTagI18n = async (): Promise<TagI18n> => {
  const response = await fetch(`${baseURL}/tags/i18n`)
  const data = await response.json()
  return data.i18n || {}
}

const fetchTagSchema = async (): Promise<TagSchema> => {
  const response = await fetch(`${baseURL}/tags/schema`)
  return await response.json()
}

const fetchAISuggestions = async (monsterId: number): Promise<string[]> => {
  const response = await fetch(`${baseURL}/tags/monsters/${monsterId}/suggest`, {
    method: 'POST'
  })
  const data = await response.json()
  return data.tags || []
}

export const TagSelector: React.FC<TagSelectorProps> = ({
  value,
  onChange,
  monsterId,
  placeholder = "搜索或选择标签...",
  className = ""
}) => {
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('all')
  const [isExpanded, setIsExpanded] = useState(false)
  
  // Parse current selected tags
  const selectedTags = useMemo(() => {
    return value.split(/[\s,，、;；]+/)
      .map(s => s.trim())
      .filter(t => t && (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_')))
  }, [value])

  // Fetch tag metadata
  const { data: i18n = {} } = useQuery({
    queryKey: ['tags', 'i18n'],
    queryFn: fetchTagI18n,
    staleTime: 5 * 60 * 1000 // 5 minutes
  })

  const { data: schema } = useQuery({
    queryKey: ['tags', 'schema'],
    queryFn: fetchTagSchema,
    staleTime: 5 * 60 * 1000
  })

  // Fetch AI suggestions if monsterId provided
  const { data: aiSuggestions = [], refetch: refetchSuggestions } = useQuery({
    queryKey: ['tags', 'suggestions', monsterId],
    queryFn: () => monsterId ? fetchAISuggestions(monsterId) : Promise.resolve([]),
    enabled: !!monsterId,
    staleTime: 0 // Always fresh for suggestions
  })

  // Get category display name
  const getCategoryName = (category: string) => {
    const names: Record<string, string> = {
      '增强类': '🔥 增强类',
      '削弱类': '💀 削弱类', 
      '特殊类': '⚡ 特殊类'
    }
    return names[category] || category
  }

  // Get tag color by category
  const getTagColor = (code: string) => {
    if (code.startsWith('buf_')) return 'bg-green-100 text-green-800 border-green-200'
    if (code.startsWith('deb_')) return 'bg-red-100 text-red-800 border-red-200'
    if (code.startsWith('util_')) return 'bg-blue-100 text-blue-800 border-blue-200'
    return 'bg-gray-100 text-gray-800 border-gray-200'
  }

  // Filter and search tags
  const filteredTags = useMemo(() => {
    if (!schema) return []
    
    let allTags: Array<{code: string, category: string, displayName: string}> = []
    
    // Collect all tags with their categories
    Object.entries(schema.groups).forEach(([category, codes]) => {
      codes.forEach(code => {
        allTags.push({
          code,
          category,
          displayName: i18n[code] || code
        })
      })
    })

    // Filter by category
    if (selectedCategory !== 'all') {
      allTags = allTags.filter(tag => tag.category === selectedCategory)
    }

    // Filter by search term
    if (searchTerm) {
      const term = searchTerm.toLowerCase()
      allTags = allTags.filter(tag => 
        tag.code.toLowerCase().includes(term) ||
        tag.displayName.toLowerCase().includes(term)
      )
    }

    return allTags.sort((a, b) => a.displayName.localeCompare(b.displayName, 'zh'))
  }, [schema, i18n, selectedCategory, searchTerm])

  // Toggle tag selection
  const toggleTag = (code: string) => {
    const currentTags = selectedTags
    const isSelected = currentTags.includes(code)
    
    let newTags: string[]
    if (isSelected) {
      newTags = currentTags.filter(t => t !== code)
    } else {
      newTags = [...currentTags, code]
    }
    
    onChange(newTags.join(' '))
  }

  // Apply AI suggestions
  const applyAISuggestions = () => {
    const currentTags = new Set(selectedTags)
    aiSuggestions.forEach(tag => currentTags.add(tag))
    onChange(Array.from(currentTags).join(' '))
  }

  // Clear all tags
  const clearAll = () => {
    onChange('')
  }

  return (
    <div className={`tag-selector ${className}`}>
      {/* Selected Tags Display */}
      <div className="mb-3">
        <label className="label">已选标签</label>
        <div className="min-h-[2.5rem] p-2 border rounded-lg bg-gray-50 flex flex-wrap gap-1">
          {selectedTags.length > 0 ? (
            selectedTags.map(code => (
              <span
                key={code}
                className={`inline-flex items-center px-2 py-1 rounded text-xs border cursor-pointer hover:opacity-75 ${getTagColor(code)}`}
                onClick={() => toggleTag(code)}
                title="点击删除"
              >
                {i18n[code] || code}
                <span className="ml-1 text-xs">×</span>
              </span>
            ))
          ) : (
            <span className="text-gray-400 text-sm">未选择标签</span>
          )}
        </div>
        {selectedTags.length > 0 && (
          <button
            type="button"
            onClick={clearAll}
            className="text-xs text-red-600 hover:text-red-800 mt-1"
          >
            清空所有
          </button>
        )}
      </div>

      {/* AI Suggestions */}
      {monsterId && aiSuggestions.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center justify-between">
            <label className="label text-sm">🤖 AI 建议</label>
            <button
              type="button"
              onClick={() => refetchSuggestions()}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              重新建议
            </button>
          </div>
          <div className="flex flex-wrap gap-1 p-2 bg-blue-50 rounded border border-blue-200">
            {aiSuggestions.map(code => (
              <span
                key={code}
                className={`inline-flex items-center px-2 py-1 rounded text-xs border cursor-pointer hover:opacity-75 ${
                  selectedTags.includes(code) 
                    ? 'bg-blue-200 text-blue-900 border-blue-300' 
                    : 'bg-white text-blue-800 border-blue-300'
                }`}
                onClick={() => toggleTag(code)}
                title={selectedTags.includes(code) ? '点击移除' : '点击添加'}
              >
                {i18n[code] || code}
                {selectedTags.includes(code) ? ' ✓' : ' +'}
              </span>
            ))}
            <button
              type="button"
              onClick={applyAISuggestions}
              className="ml-2 px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              全部应用
            </button>
          </div>
        </div>
      )}

      {/* Expandable Tag Browser */}
      <div className="mb-3">
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center justify-between w-full p-2 text-left border rounded-lg hover:bg-gray-50"
        >
          <span className="label">浏览所有标签</span>
          <span className={`transform transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
            ▼
          </span>
        </button>
        
        {isExpanded && (
          <div className="mt-2 border rounded-lg">
            {/* Search and Filter */}
            <div className="p-3 border-b bg-gray-50">
              <div className="flex gap-2 mb-2">
                <input
                  type="text"
                  placeholder={placeholder}
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="flex-1 px-3 py-1 text-sm border rounded"
                />
                <select
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  className="px-3 py-1 text-sm border rounded"
                >
                  <option value="all">所有类别</option>
                  {schema && Object.keys(schema.groups).map(category => (
                    <option key={category} value={category}>
                      {getCategoryName(category)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="text-xs text-gray-600">
                找到 {filteredTags.length} 个标签
                {searchTerm && ` | 搜索: "${searchTerm}"`}
                {selectedCategory !== 'all' && ` | 类别: ${getCategoryName(selectedCategory)}`}
              </div>
            </div>

            {/* Tag Grid */}
            <div className="p-3 max-h-60 overflow-y-auto">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1">
                {filteredTags.map(({ code, displayName }) => {
                  const isSelected = selectedTags.includes(code)
                  return (
                    <button
                      key={code}
                      type="button"
                      onClick={() => toggleTag(code)}
                      className={`text-left p-2 text-sm rounded border transition-colors ${
                        isSelected
                          ? `${getTagColor(code)} ring-2 ring-offset-1 ring-blue-400`
                          : 'bg-white border-gray-200 hover:bg-gray-50'
                      }`}
                      title={`${code} - 点击${isSelected ? '移除' : '添加'}`}
                    >
                      <div className="font-medium">{displayName}</div>
                      <div className="text-xs text-gray-500">{code}</div>
                    </button>
                  )
                })}
              </div>
              
              {filteredTags.length === 0 && (
                <div className="text-center text-gray-500 py-8">
                  <div className="text-sm">未找到匹配的标签</div>
                  {searchTerm && (
                    <button
                      type="button"
                      onClick={() => setSearchTerm('')}
                      className="text-xs text-blue-600 hover:text-blue-800 mt-1"
                    >
                      清除搜索
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Legacy Input (as fallback) */}
      <div>
        <label className="label text-sm">高级编辑（手动输入）</label>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="buf_atk_up deb_def_down util_multi..."
          className="input text-sm font-mono"
        />
        <div className="text-xs text-gray-500 mt-1">
          支持空格/逗号分隔，仅保留 buf_*/deb_*/util_* 格式
        </div>
      </div>
    </div>
  )
}

export default TagSelector