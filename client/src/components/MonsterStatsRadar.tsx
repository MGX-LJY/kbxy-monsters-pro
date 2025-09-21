import React, { useState, useEffect, useRef } from 'react'
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer } from 'recharts'
import { Monster } from '../types'
import api from '../api'

// 前端缓存
const rankingCache = new Map<number, any>()
const CACHE_EXPIRY_MS = 5 * 60 * 1000 // 5分钟

interface MonsterStatsRadarProps {
  monster: Monster
  className?: string
}

interface MonsterRanking {
  stat_name: string
  value: number
  percentile: number
  tier: string
  rank: number
  total_count: number
  is_outlier: boolean
}

const MonsterStatsRadar: React.FC<MonsterStatsRadarProps> = ({ 
  monster, 
  className = '' 
}) => {
  const [radarData, setRadarData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchRanking = async () => {
      if (!monster?.id) return
      
      try {
        setLoading(true)
        setError(null)
        
        // 检查缓存
        const cacheKey = monster.id
        const cached = rankingCache.get(cacheKey)
        const now = Date.now()
        
        if (cached && (now - cached.timestamp) < CACHE_EXPIRY_MS) {
          // 使用缓存数据
          setRadarData(cached.data)
          setLoading(false)
          return
        }
        
        const response = await api.get(`/stats/monster/${monster.id}/ranking`)
        const rankings: Record<string, MonsterRanking> = response.data
        
        // 转换为雷达图所需的格式
        const chartData = Object.entries(rankings).map(([statKey, ranking]) => ({
          stat: ranking.stat_name,
          value: ranking.value,
          percentile: ranking.percentile,
          fullMark: 100,
          tier: ranking.tier,
          rank: ranking.rank,
          total_count: ranking.total_count,
          is_outlier: ranking.is_outlier
        }))
        
        // 存储到缓存
        rankingCache.set(cacheKey, {
          data: chartData,
          timestamp: now
        })
        
        setRadarData(chartData)
      } catch (err: any) {
        console.error('Failed to fetch monster ranking:', err)
        setError('获取排名数据失败')
      } finally {
        setLoading(false)
      }
    }

    fetchRanking()
  }, [monster?.id])

  if (loading) {
    return (
      <div className={`flex items-center justify-center h-64 text-gray-500 ${className}`}>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
          正在计算排名...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`flex items-center justify-center h-64 text-red-500 ${className}`}>
        <div className="text-center">
          <div className="mb-2">⚠️ {error}</div>
          <button 
            className="text-sm text-blue-500 hover:text-blue-700"
            onClick={() => window.location.reload()}
          >
            重新加载
          </button>
        </div>
      </div>
    )
  }

  if (!radarData.length) {
    return (
      <div className={`flex items-center justify-center h-64 text-gray-500 ${className}`}>
        暂无排名数据
      </div>
    )
  }

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={radarData}>
          <PolarGrid gridType="polygon" />
          <PolarAngleAxis 
            dataKey="stat" 
            className="text-sm"
            tick={{ fontSize: 12, fill: '#374151' }}
          />
          <PolarRadiusAxis 
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: '#6B7280' }}
            tickCount={6}
          />
          <Radar
            name="排名百分比"
            dataKey="percentile"
            stroke="#3B82F6"
            fill="#3B82F6"
            fillOpacity={0.2}
            strokeWidth={2}
            dot={{ fill: '#3B82F6', strokeWidth: 2, r: 4 }}
          />
        </RadarChart>
      </ResponsiveContainer>
      
      {/* 数值详情 */}
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        {radarData.map(item => (
          <div key={item.stat} className="flex justify-between items-center p-2 bg-gray-50 rounded">
            <span className="font-medium">{item.stat}</span>
            <div className="text-right">
              <div className="font-bold text-blue-600">{item.value}</div>
              <div className="flex items-center gap-1">
                <span className={`px-1 py-0.5 rounded text-xs font-medium ${
                  item.tier === '顶级' ? 'bg-purple-100 text-purple-700' :
                  item.tier === '优秀' ? 'bg-blue-100 text-blue-700' :
                  item.tier === '良好' ? 'bg-green-100 text-green-700' :
                  item.tier === '一般' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-gray-100 text-gray-600'
                }`}>
                  {item.tier}
                </span>
                <span className="text-gray-500">{item.percentile}分</span>
                {item.is_outlier && <span className="text-purple-600 text-xs">👑</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default MonsterStatsRadar