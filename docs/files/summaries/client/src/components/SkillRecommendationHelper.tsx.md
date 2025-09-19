# client/src/components/SkillRecommendationHelper.tsx

## 概述
React技能推荐助手组件，为怪物技能管理提供智能推荐功能。基于技能威力、类型和描述内容进行智能分析，支持多种推荐策略和批量操作，帮助用户快速选择最有价值的推荐技能。

## 核心功能

### 智能推荐算法
- **策略推荐**: 攻击技能选前2强 + 防御削弱类辅助技能
- **威力优先**: 根据技能威力值选择最强攻击技能
- **辅助专选**: 专门识别和推荐防御、削弱类辅助技能
- **关键词分析**: 基于技能名称和描述进行语义分析

### 批量操作
- **全选/全不选**: 快速选择或取消所有技能
- **反选操作**: 反转当前所有技能的选择状态
- **计数显示**: 实时显示已选择技能数量

## 数据结构

### TypeScript接口定义
```typescript
interface Skill {
  id?: number           // 技能ID
  name: string          // 技能名称
  element?: string | null    // 元素属性
  kind?: string | null       // 技能类型
  power?: number | null      // 技能威力
  description?: string       // 技能描述
  selected?: boolean         // 是否被推荐选择
}

interface SkillRecommendationHelperProps {
  skills: Skill[]                                    // 技能列表
  onUpdateSkills: (updatedSkills: Skill[]) => void  // 技能更新回调
}
```

## 推荐策略算法

### 1. 策略推荐 (smartRecommend)
**综合策略**: 平衡攻击和辅助技能的选择

**攻击技能选择**:
```typescript
// 按威力排序，选择前2个最强攻击技能
const attackSkills = skills.filter(skill => skill.power && skill.power > 0)
attackSkills.sort((a, b) => (b.power || 0) - (a.power || 0))
const selectedAttackIndices = attackSkills.slice(0, 2)
```

**辅助技能评分系统**:
```typescript
// 防御类关键词（提升己方能力）
const defenseKeywords = [
  '防御', '抗性', '护盾', '减伤', '免疫', '格挡', '回避', '闪避',
  '治疗', '恢复', 'hp', 'mp', '生命', '法力', '庇护', '保护',
  '防护', '抗', '免', '盾', '愈', '复活'
]

// 削弱类关键词（削弱敌方能力）
const debuffKeywords = [
  '降低', '减少', '削弱', '下降', '攻击', '法术', '命中', '速度',
  '眩晕', '麻痹', '睡眠', '中毒', '燃烧', '冰冻', '封印',
  '减攻', '减防', '减速', '减命中', '控制', '沉默', '束缚'
]

// 评分规则
let score = 0
const defenseMatches = defenseKeywords.filter(keyword => text.includes(keyword))
const debuffMatches = debuffKeywords.filter(keyword => text.includes(keyword))

if (defenseMatches.length > 0) score += 3 + defenseMatches.length
if (debuffMatches.length > 0) score += 3 + debuffMatches.length
if (descLength > 50) score += 1  // 描述详细度加分
```

### 2. 威力推荐 (recommendByPower)
**纯攻击导向**: 选择威力值最高的技能

```typescript
const skillsWithPower = skills
  .filter(skill => skill.power && skill.power > 0)
  .sort((a, b) => (b.power || 0) - (a.power || 0))

const topCount = Math.min(4, Math.max(2, skillsWithPower.length))
const selectedSkills = skillsWithPower.slice(0, topCount)
```

### 3. 辅助推荐 (recommendSupport)
**辅助专精**: 专门选择防御和削弱类技能

```typescript
const supportSkills = skills.filter(skill => !skill.power || skill.power <= 0)

// 使用相同的关键词评分系统，但只针对辅助技能
const scoredSupportSkills = supportSkills.map(skill => {
  // 计算防御和削弱类关键词匹配度
  return { skill, index, score }
})

const selectedSupport = scoredSupportSkills
  .sort((a, b) => b.score - a.score)
  .slice(0, Math.min(4, supportSkills.length))
```

## 用户界面

### 状态显示区域
```tsx
<div className="flex items-center justify-between mb-3">
  <div className="flex items-center gap-2">
    <span className="text-sm font-medium text-blue-800">推荐技能选择</span>
    <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
      {recommendedCount}/{totalCount}
    </span>
  </div>
  <div className="text-xs text-blue-600">快速操作 ⚡</div>
</div>
```

### 基础操作按钮
- **✓ 全选**: 绿色按钮，将所有技能设为推荐
- **✗ 全不选**: 灰色按钮，取消所有推荐技能  
- **⟲ 反选**: 紫色按钮，反转所有技能的推荐状态

### 智能推荐按钮
```tsx
<button
  onClick={smartRecommend}
  className="px-3 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
  title="攻击技能选前2强，辅助技能选防御+削弱类"
>
  🎯 策略推荐（攻击前2 + 防御削弱辅助）
</button>
```

### 专项推荐按钮
- **⚡ 攻击技能**: 橙色按钮，选择威力最高的攻击技能
- **🛡️ 辅助技能**: 青色按钮，选择防御和削弱类辅助技能

## 关键词匹配系统

### 防御类技能识别
**目标**: 识别提升己方防御能力的技能
**关键词类别**:
- **防御属性**: 防御、抗性、护盾、减伤、免疫、格挡、回避、闪避
- **恢复能力**: 治疗、恢复、hp、mp、生命、法力、复活
- **保护效果**: 庇护、保护、防护、抗、免、盾、愈

### 削弱类技能识别
**目标**: 识别削弱敌方能力的技能
**关键词类别**:
- **数值削弱**: 降低、减少、削弱、下降、减攻、减防、减速、减命中
- **状态控制**: 眩晕、麻痹、睡眠、沉默、束缚、封印
- **持续伤害**: 中毒、燃烧、冰冻

### 评分权重系统
```typescript
// 基础分数分配
if (defenseMatches.length > 0) score += 3 + defenseMatches.length  // 防御类: 基础3分+匹配数
if (debuffMatches.length > 0) score += 3 + debuffMatches.length    // 削弱类: 基础3分+匹配数
if (bothEmpty) score += 1                                          // 其他辅助: 基础1分
if (descLength > 50) score += 1                                    // 描述详细: +1分
```

## 组件响应式设计

### 网格布局
- **基础操作**: `grid-cols-3` 三列布局（全选、全不选、反选）
- **智能推荐**: `grid-cols-1` 单列布局（突出主要功能）
- **专项推荐**: `grid-cols-2` 双列布局（攻击、辅助）

### 颜色主题
- **主容器**: 蓝色主题 (`bg-blue-50 border-blue-200`)
- **全选**: 绿色 (`bg-green-500`)
- **全不选**: 灰色 (`bg-gray-500`)
- **反选**: 紫色 (`bg-purple-500`)
- **策略推荐**: 蓝色 (`bg-blue-500`)
- **攻击技能**: 橙色 (`bg-orange-500`)
- **辅助技能**: 青色 (`bg-teal-500`)

### 交互反馈
- **悬停效果**: 所有按钮都有hover状态变化
- **过渡动画**: `transition-colors` 平滑颜色过渡
- **工具提示**: title属性提供详细操作说明
- **状态显示**: 实时显示已选择技能数量

## 使用场景

### 新怪物录入
- **快速配置**: 一键设置推荐技能组合
- **策略平衡**: 自动平衡攻击和辅助技能比例
- **关键词识别**: 基于技能描述智能分类

### 怪物数据整理
- **批量操作**: 快速调整大量技能的推荐状态
- **专项优化**: 针对特定类型技能进行推荐调整
- **数据验证**: 确保推荐技能的合理性

### 战术分析
- **攻击策略**: 识别最具威胁的攻击技能
- **防御策略**: 找出重要的防御和恢复技能
- **控制策略**: 识别关键的削弱和控制技能

这个组件通过智能算法和直观界面，大大简化了技能推荐的管理流程，提升了数据录入的效率和准确性。