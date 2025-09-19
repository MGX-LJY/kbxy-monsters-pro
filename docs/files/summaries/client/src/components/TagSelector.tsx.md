# client/src/components/TagSelector.tsx

## 概述
React标签选择器组件，提供直观的怪物技能标签管理界面。支持AI智能推荐、分类浏览、搜索过滤和多种交互方式，使用React Query进行数据管理和缓存。

## 核心功能

### 标签管理
- **多选支持**: 支持选择多个技能标签，以空格分隔存储
- **实时预览**: 已选标签实时显示，支持点击删除
- **格式验证**: 仅支持buf_/deb_/util_前缀的标签格式
- **批量操作**: 支持一键清空所有已选标签

### AI智能推荐
- **基于怪物ID**: 根据特定怪物生成智能标签建议
- **动态刷新**: 支持重新获取AI建议
- **差异显示**: 区分已选和未选的建议标签
- **批量应用**: 一键应用所有AI建议

### 交互式浏览
- **可展开界面**: 点击展开/收起完整标签浏览器
- **分类过滤**: 按增强类/削弱类/特殊类筛选标签
- **实时搜索**: 支持按标签代码或显示名称搜索
- **网格布局**: 响应式网格显示所有可选标签

## 数据接口

### TypeScript类型定义
```typescript
interface TagI18n {
  [code: string]: string // 标签代码到显示名称的映射
}

interface TagSchema {
  groups: {
    [category: string]: string[] // 分类到标签列表的映射
  }
  default: string
}

interface TagSelectorProps {
  value: string // 当前选中标签（空格分隔字符串）
  onChange: (newTags: string) => void // 标签变更回调
  monsterId?: number // 怪物ID（用于AI建议）
  placeholder?: string // 搜索框占位符
  className?: string // 额外CSS类名
}
```

### API端点
- **GET /tags/i18n**: 获取标签国际化显示名称
- **GET /tags/schema**: 获取标签分类结构
- **POST /tags/monsters/{id}/suggest**: 获取特定怪物的AI标签建议

### React Query缓存策略
- **标签元数据**: 5分钟缓存时间（i18n和schema）
- **AI建议**: 实时获取，无缓存（staleTime: 0）
- **自动重试**: 默认React Query重试机制

## 组件结构

### 已选标签区域
- **标签徽章**: 彩色显示已选标签，支持悬停删除
- **空状态**: 未选择时显示提示文字
- **清空按钮**: 有选择时显示"清空所有"选项

### AI建议区域
```tsx
{monsterId && aiSuggestions.length > 0 && (
  <div className="mb-3">
    <div className="flex items-center justify-between">
      <label className="label text-sm">🤖 AI 建议</label>
      <button onClick={() => refetchSuggestions()}>重新建议</button>
    </div>
    <div className="flex flex-wrap gap-1 p-2 bg-blue-50 rounded border border-blue-200">
      {/* AI建议标签 */}
    </div>
  </div>
)}
```

### 可展开浏览器
- **展开控制**: 点击按钮展开/收起完整标签浏览器
- **搜索过滤**: 实时搜索标签代码和显示名称
- **分类筛选**: 下拉选择特定标签类别
- **响应式网格**: 自适应屏幕大小的标签网格布局

### 高级编辑模式
- **手动输入**: 直接编辑标签字符串的文本框
- **格式提示**: 说明支持的标签格式和分隔符
- **兜底机制**: 当UI交互不足时的手动编辑选项

## 样式系统

### 标签颜色分类
```typescript
const getTagColor = (code: string) => {
  if (code.startsWith('buf_')) return 'bg-green-100 text-green-800 border-green-200' // 增强类-绿色
  if (code.startsWith('deb_')) return 'bg-red-100 text-red-800 border-red-200'       // 削弱类-红色
  if (code.startsWith('util_')) return 'bg-blue-100 text-blue-800 border-blue-200'   // 特殊类-蓝色
  return 'bg-gray-100 text-gray-800 border-gray-200'                                // 默认-灰色
}
```

### 状态样式
- **已选状态**: 环形外框(ring-2 ring-offset-1 ring-blue-400)突出显示
- **悬停效果**: 所有可交互元素都有悬停状态
- **响应式布局**: grid-cols-1 sm:grid-cols-2 lg:grid-cols-3

### 分类图标
- **增强类**: 🔥 火焰图标
- **削弱类**: 💀 骷髅图标  
- **特殊类**: ⚡ 闪电图标

## 核心算法

### 标签解析
```typescript
const selectedTags = useMemo(() => {
  return value.split(/[\s,，、;；]+/)  // 支持多种分隔符
    .map(s => s.trim())
    .filter(t => t && (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_')))
}, [value])
```

### 标签过滤
```typescript
const filteredTags = useMemo(() => {
  let allTags = [] // 从schema收集所有标签
  
  // 分类过滤
  if (selectedCategory !== 'all') {
    allTags = allTags.filter(tag => tag.category === selectedCategory)
  }
  
  // 搜索过滤
  if (searchTerm) {
    const term = searchTerm.toLowerCase()
    allTags = allTags.filter(tag => 
      tag.code.toLowerCase().includes(term) ||
      tag.displayName.toLowerCase().includes(term)
    )
  }
  
  return allTags.sort((a, b) => a.displayName.localeCompare(b.displayName, 'zh'))
}, [schema, i18n, selectedCategory, searchTerm])
```

### 标签切换
```typescript
const toggleTag = (code: string) => {
  const currentTags = selectedTags
  const isSelected = currentTags.includes(code)
  
  let newTags: string[]
  if (isSelected) {
    newTags = currentTags.filter(t => t !== code) // 移除
  } else {
    newTags = [...currentTags, code] // 添加
  }
  
  onChange(newTags.join(' '))
}
```

## 用户体验

### 交互反馈
- **视觉状态**: 清晰的选中/未选中状态区分
- **操作提示**: 悬停时显示操作说明
- **计数显示**: 实时显示搜索结果数量
- **空状态处理**: 无结果时提供清除搜索选项

### 性能优化
- **useMemo缓存**: 标签解析和过滤结果缓存
- **数据缓存**: React Query管理API数据缓存
- **懒加载**: 标签浏览器按需展开
- **虚拟滚动**: 大量标签时的滚动区域限制

### 可访问性
- **键盘导航**: 支持Tab键导航所有交互元素
- **屏幕阅读器**: 语义化HTML和适当的标签
- **对比度**: 遵循WCAG颜色对比度标准

## 集成使用

### 基础用法
```tsx
<TagSelector
  value={monsterTags}
  onChange={setMonsterTags}
  monsterId={monster.id}
  placeholder="搜索技能标签..."
  className="mb-4"
/>
```

### 高级配置
- **环境变量**: VITE_API_BASE配置API基础URL
- **国际化**: 通过i18n接口支持多语言显示
- **主题定制**: 通过Tailwind CSS类名定制样式

这个组件提供了完整的标签管理解决方案，结合了现代React最佳实践和直观的用户交互设计。