import { Component, type ErrorInfo, type ReactNode } from "react";

type BoundaryState = { failed: boolean; reference: string };

export class AppErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { failed: false, reference: "" };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true, reference: createReference() };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("DripCut UI failure", {
      reference: this.state.reference,
      error,
      componentStack: info.componentStack,
    });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="app-crash" role="alert">
        <span>DripCut</span>
        <h1>We could not open this screen.</h1>
        <p>Your project is still safe. Reload DripCut to try this screen again.</p>
        <small>Support reference: {this.state.reference}</small>
        <button type="button" onClick={() => window.location.reload()}>Reload DripCut</button>
      </main>
    );
  }
}

function createReference(): string {
  return `UI-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 7).toUpperCase()}`;
}
