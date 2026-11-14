"use client";

import { Component, type ReactNode } from "react";

/** If rendering an answer ever fails, show it as plain text instead of a blank page (issue 3.4). */
export class RenderGuard extends Component<{ text: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: { text: string }) {
    if (this.state.failed && previous.text !== this.props.text) this.setState({ failed: false });
  }

  render() {
    return this.state.failed ? <div className="text-sm whitespace-pre-wrap">{this.props.text}</div> : this.props.children;
  }
}
