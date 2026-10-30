import { Component } from 'react'

// Keeps a failure in one part of the page (the map, a chart panel) from blanking the whole app:
// that part shows a short notice with "Try again"; the header, navigation and other panels stay usable.
// Technical details go to the console only.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error(`[${this.props.name ?? 'Panel'}] failed to render:`, error, info?.componentStack)
  }

  componentDidUpdate(prev) {
    // a new selection (season, tab, location...) gets a fresh attempt
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" style={{height: '100%', minHeight: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
                                borderRadius: 12, border: '1px solid var(--border-primary)', background: 'var(--bg-surface)'}}>
        <div style={{maxWidth: 420, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 15, lineHeight: 1.6, color: 'var(--text-body)'}}>
          <strong style={{fontSize: 17, color: 'var(--heading)'}}>{this.props.title ?? 'This part of the page could not be shown'}</strong>
          <span>{this.props.message ?? 'The rest of the dashboard still works. Try again, or choose another view.'}</span>
          <div>
            <button type="button" onClick={() => this.setState({ error: null })}
              style={{minHeight: 40, padding: '0 16px', borderRadius: 8, border: '1px solid var(--btn-primary)', background: 'var(--btn-primary)',
                      color: '#fff', fontWeight: 600, fontSize: 14, cursor: 'pointer'}}>
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }
}
