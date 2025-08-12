import React from 'react'

type State = { hasError: boolean, message?: string }
export class ErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  constructor(props: any){ super(props); this.state = { hasError: false } }
  static getDerivedStateFromError(err: any){ return { hasError: true, message: String(err?.message || err) } }
  componentDidCatch(err: any, info: any){ console.error('ErrorBoundary', err, info) }
  render(){
    if(this.state.hasError){
      return (
        <div className="container my-8">
          <div className="card">
            <h2 className="text-xl font-semibold mb-2">页面出现错误</h2>
            <p className="text-sm text-gray-600">{this.state.message}</p>
            <div className="mt-3">
              <button className="btn" onClick={()=> location.reload()}>刷新页面</button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
