import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
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

export default api
