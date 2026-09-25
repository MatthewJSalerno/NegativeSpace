import type { ReactNode } from "react";

// A hover and keyboard-focus explanation for a control. On a wrapper rather than the
// control itself, so it still shows while the control is disabled.
export function Tip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="tip" data-tip={text}>
      {children}
    </span>
  );
}
