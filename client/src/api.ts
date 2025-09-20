/// <reference types="vite/client" />
import axios from 'axios'

const baseURL = import.meta.env?.VITE_API_BASE ?? 'http://localhost:8000'

const api = axios.create({
  baseURL,
  timeout: 15000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const traceId = err?.response?.headers?.['x-trace-id']
    if (traceId) {
      ;(err as any).__traceId = traceId
      console.warn('trace_id:', traceId)
    }
    return Promise.reject(err)
  }
)

// Backup API
export const backupApi = {
  // 获取备份配置
  getConfig: () => api.get('/backup/config'),
  
  // 更新备份配置
  updateConfig: (config: any) => api.post('/backup/config', config),
  
  // 创建备份
  createBackup: (data: { name?: string; description?: string } = {}) => 
    api.post('/backup/create', data),
  
  // 获取备份列表
  listBackups: () => api.get('/backup/list'),
  
  // 获取特定备份信息
  getBackupInfo: (backupName: string) => api.get(`/backup/${backupName}/info`),
  
  // 还原备份
  restoreBackup: (backupName: string) => api.post(`/backup/${backupName}/restore`),
  
  // 删除备份
  deleteBackup: (backupName: string) => api.delete(`/backup/${backupName}`),
  
  // 触发自动备份
  triggerAutoBackup: () => api.post('/backup/auto-backup'),
  
  // 获取备份状态
  getStatus: () => api.get('/backup/status'),
}

// App Settings API
export const settingsApi = {
  // 获取所有设置
  getSettings: () => api.get('/app-settings/'),
  
  // 批量更新设置
  updateSettings: (settings: any) => 
    api.put('/app-settings/', { settings }),
  
  // 更新单个设置
  updateSetting: (key: string, value: any) =>
    api.put(`/app-settings/${key}`, { key, value }),
  
  // 获取特定设置
  getSetting: (key: string) => api.get(`/app-settings/${key}`),
  
  // 重置设置
  resetSettings: () => api.post('/app-settings/reset'),
}

export default api