import React from 'react';

interface Props {
  fallback: React.ReactNode;
  children: React.ReactNode;
}

interface State {
  failed: boolean;
}

/** Contains GL/render failures so decorative layers can never take down a screen. */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(): void {
    /* decorative layer failed — fallback rendered; nothing to report */
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
