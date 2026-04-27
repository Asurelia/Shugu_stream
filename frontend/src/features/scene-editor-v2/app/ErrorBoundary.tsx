/**
 * ErrorBoundary local au Scene Editor v2.
 *
 * Si un workspace 3D crash (Three.js, VRM, WebGL lost context, etc.), le shell
 * (topbar/sidebar/statusbar) reste utilisable et l'utilisateur peut switch de
 * workspace ou recharger.
 */

import { Component, type ReactNode, type ErrorInfo } from "react";

type Props = { children: ReactNode; fallback?: (error: Error, retry: () => void) => ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (typeof console !== "undefined") {
      console.error("[scene-editor-v2] caught error:", error, info.componentStack);
    }
  }

  retry = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback(this.state.error, this.retry);
      return (
        <div role="alert" className="sev2-error">
          <div className="sev2-error-title">Le workspace a planté.</div>
          <div className="sev2-error-msg">{this.state.error.message}</div>
          <button type="button" className="lgb lgb-ghost lgb-sm" onClick={this.retry}>
            Réessayer
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
