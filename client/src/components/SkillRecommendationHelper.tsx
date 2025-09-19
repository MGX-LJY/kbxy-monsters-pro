import React from 'react'

interface Skill {
  id?: number
  name: string
  element?: string | null
  kind?: string | null
  power?: number | null
  description?: string
  selected?: boolean
}

interface SkillRecommendationHelperProps {
  skills: Skill[]
  onUpdateSkills: (updatedSkills: Skill[]) => void
}

export const SkillRecommendationHelper: React.FC<SkillRecommendationHelperProps> = ({
  skills,
  onUpdateSkills
}) => {
  // 统计推荐技能数量
  const recommendedCount = skills.filter(skill => skill.selected).length
  const totalCount = skills.length

  // 全选推荐
  const selectAll = () => {
    const updated = skills.map(skill => ({ ...skill, selected: true }))
    onUpdateSkills(updated)
  }

  // 全不选
  const selectNone = () => {
    const updated = skills.map(skill => ({ ...skill, selected: false }))
    onUpdateSkills(updated)
  }

  // 反选
  const toggleAll = () => {
    const updated = skills.map(skill => ({ ...skill, selected: !skill.selected }))
    onUpdateSkills(updated)
  }

  // 智能推荐 - 区分攻击技能和辅助技能
  const smartRecommend = () => {
    // 分离攻击技能和辅助技能
    const attackSkills: Array<{skill: Skill, index: number}> = []
    const supportSkills: Array<{skill: Skill, index: number}> = []
    
    skills.forEach((skill, index) => {
      if (skill.power && skill.power > 0) {
        attackSkills.push({ skill, index })
      } else {
        supportSkills.push({ skill, index })
      }
    })
    
    // 1. 攻击技能：选择威力最大的前2个
    attackSkills.sort((a, b) => (b.skill.power || 0) - (a.skill.power || 0))
    const selectedAttackIndices = new Set(
      attackSkills.slice(0, 2).map(({ index }) => index)
    )
    
    // 2. 辅助技能：按策略价值评分
    const scoredSupportSkills = supportSkills.map(({ skill, index }) => {
      let score = 0
      const text = `${skill.name} ${skill.description || ''}`.toLowerCase()
      
      // 防御类关键词 (提升己方防御能力)
      const defenseKeywords = [
        '防御', '抗性', '护盾', '减伤', '免疫', '格挡', '回避', '闪避',
        '治疗', '恢复', 'hp', 'mp', '生命', '法力', '庇护', '保护',
        '防护', '抗', '免', '盾', '愈', '复活'
      ]
      
      // 削弱类关键词 (削弱敌方能力)
      const debuffKeywords = [
        '降低', '减少', '削弱', '下降', '攻击', '法术', '命中', '速度',
        '眩晕', '麻痹', '睡眠', '中毒', '燃烧', '冰冻', '封印',
        '减攻', '减防', '减速', '减命中', '控制', '沉默', '束缚'
      ]
      
      // 检查防御类关键词
      const defenseMatches = defenseKeywords.filter(keyword => text.includes(keyword))
      if (defenseMatches.length > 0) {
        score += 3 + defenseMatches.length // 基础3分 + 匹配关键词数
      }
      
      // 检查削弱类关键词
      const debuffMatches = debuffKeywords.filter(keyword => text.includes(keyword))
      if (debuffMatches.length > 0) {
        score += 3 + debuffMatches.length // 基础3分 + 匹配关键词数
      }
      
      // 其他辅助技能基础分
      if (defenseMatches.length === 0 && debuffMatches.length === 0) {
        score += 1
      }
      
      // 描述详细度加分 (说明技能复杂度高)
      const descLength = (skill.description || '').length
      if (descLength > 50) score += 1
      
      return { skill, index, score }
    })
    
    // 按评分排序，选择前几个辅助技能
    scoredSupportSkills.sort((a, b) => b.score - a.score)
    const selectedSupportIndices = new Set(
      scoredSupportSkills.slice(0, Math.min(3, scoredSupportSkills.length)).map(({ index }) => index)
    )
    
    // 更新技能选择状态
    const updated = skills.map((skill, index) => ({
      ...skill,
      selected: selectedAttackIndices.has(index) || selectedSupportIndices.has(index)
    }))
    
    onUpdateSkills(updated)
  }

  // 按威力推荐 - 选择威力最高的几个技能
  const recommendByPower = () => {
    // 过滤有威力值的技能并排序
    const skillsWithPower = skills
      .map((skill, index) => ({ skill, index }))
      .filter(({ skill }) => skill.power && skill.power > 0)
      .sort((a, b) => (b.skill.power || 0) - (a.skill.power || 0))
    
    // 选择威力最高的前3-4个技能
    const topCount = Math.min(4, Math.max(2, skillsWithPower.length))
    const topSkillIndices = new Set(
      skillsWithPower.slice(0, topCount).map(({ index }) => index)
    )
    
    const updated = skills.map((skill, index) => ({
      ...skill,
      selected: topSkillIndices.has(index)
    }))
    
    onUpdateSkills(updated)
  }

  // 推荐辅助技能 - 选择防御和削弱类辅助技能
  const recommendSupport = () => {
    const supportSkills = skills
      .map((skill, index) => ({ skill, index }))
      .filter(({ skill }) => !skill.power || skill.power <= 0)
      
    const scoredSupportSkills = supportSkills.map(({ skill, index }) => {
      let score = 0
      const text = `${skill.name} ${skill.description || ''}`.toLowerCase()
      
      // 防御类关键词 (提升己方防御能力) 
      const defenseKeywords = [
        '防御', '抗性', '护盾', '减伤', '免疫', '格挡', '回避', '闪避',
        '治疗', '恢复', 'hp', 'mp', '生命', '法力', '庇护', '保护'
      ]
      
      // 削弱类关键词 (削弱敌方能力)
      const debuffKeywords = [
        '降低', '减少', '削弱', '下降', '攻击', '法术', '命中', '速度',
        '眩晕', '麻痹', '睡眠', '中毒', '燃烧', '冰冻', '封印'
      ]
      
      const defenseMatches = defenseKeywords.filter(keyword => text.includes(keyword))
      const debuffMatches = debuffKeywords.filter(keyword => text.includes(keyword))
      
      if (defenseMatches.length > 0) score += 3 + defenseMatches.length
      if (debuffMatches.length > 0) score += 3 + debuffMatches.length
      if (defenseMatches.length === 0 && debuffMatches.length === 0) score += 1
      
      return { skill, index, score }
    })
    
    scoredSupportSkills.sort((a, b) => b.score - a.score)
    const selectedIndices = new Set(
      scoredSupportSkills.slice(0, Math.min(4, scoredSupportSkills.length)).map(({ index }) => index)
    )
    
    const updated = skills.map((skill, index) => ({
      ...skill,
      selected: selectedIndices.has(index)
    }))
    
    onUpdateSkills(updated)
  }

  if (totalCount === 0) return null

  return (
    <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-blue-800">推荐技能选择</span>
          <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
            {recommendedCount}/{totalCount}
          </span>
        </div>
        <div className="text-xs text-blue-600">
          快速操作 ⚡
        </div>
      </div>
      
      {/* 基础操作 */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <button
          type="button"
          onClick={selectAll}
          className="px-3 py-1.5 text-xs bg-green-500 text-white rounded hover:bg-green-600 transition-colors"
          title="将所有技能设为推荐"
        >
          ✓ 全选
        </button>
        
        <button
          type="button"
          onClick={selectNone}
          className="px-3 py-1.5 text-xs bg-gray-500 text-white rounded hover:bg-gray-600 transition-colors"
          title="取消所有推荐技能"
        >
          ✗ 全不选
        </button>
        
        <button
          type="button"
          onClick={toggleAll}
          className="px-3 py-1.5 text-xs bg-purple-500 text-white rounded hover:bg-purple-600 transition-colors"
          title="反转所有技能的推荐状态"
        >
          ⟲ 反选
        </button>
      </div>
      
      {/* 智能推荐 */}
      <div className="grid grid-cols-1 gap-2 mb-2">
        <button
          type="button"
          onClick={smartRecommend}
          className="px-3 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors font-medium"
          title="攻击技能选前2强，辅助技能选防御+削弱类"
        >
          🎯 策略推荐（攻击前2 + 防御削弱辅助）
        </button>
      </div>
      
      {/* 专项推荐 */}
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={recommendByPower}
          className="px-3 py-1.5 text-xs bg-orange-500 text-white rounded hover:bg-orange-600 transition-colors"
          title="选择威力最高的攻击技能"
        >
          ⚡ 攻击技能
        </button>
        
        <button
          type="button"
          onClick={recommendSupport}
          className="px-3 py-1.5 text-xs bg-teal-500 text-white rounded hover:bg-teal-600 transition-colors"
          title="选择防御和削弱类辅助技能"
        >
          🛡️ 辅助技能
        </button>
      </div>
      
      {recommendedCount > 0 && (
        <div className="mt-2 text-xs text-blue-600 text-center">
          已选择 {recommendedCount} 个推荐技能
        </div>
      )}
    </div>
  )
}

export default SkillRecommendationHelper