import { Component, ReactNode } from "react";

const RELOAD_KEY = "hm.chunkReload";

/** Keeps one broken section from blanking the app. A stale lazy chunk (the app was rebuilt
 *  while this tab was open) reloads the page once to pick up the new bundle. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    if (/dynamically imported module|Importing a module script failed|ChunkLoadError/i.test(error.message)) {
      // At most one automatic reload per 30s, so a chunk that is truly missing cannot loop.
      let last = 0;
      try { last = Number(sessionStorage.getItem(RELOAD_KEY) || 0); sessionStorage.setItem(RELOAD_KEY, String(Date.now())); } catch { return; }
      if (Date.now() - last > 30000) window.location.reload();
    }
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="alert down" role="alert">
        <b>This section failed to load.</b>
        <div className="muted" style={{ margin: "6px 0 10px" }}>{this.state.error.message}</div>
        <button className="btn sm" onClick={() => window.location.reload()}>Reload the console</button>
      </div>
    );
  }
}
