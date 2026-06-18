import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-8 max-w-2xl">
          <div className="bg-sev-critical/10 border border-sev-critical/30 rounded-lg p-5">
            <h2 className="font-semibold text-sev-critical mb-2">Page error</h2>
            <pre className="text-xs text-ink-muted whitespace-pre-wrap break-all bg-surface rounded p-3">
              {this.state.error.message}
              {'\n\n'}
              {this.state.error.stack}
            </pre>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-4 px-4 py-2 text-sm bg-brand text-white rounded hover:bg-brand-hover"
            >
              Retry
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
