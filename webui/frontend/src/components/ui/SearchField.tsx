import { useRef, type InputHTMLAttributes, type KeyboardEvent } from "react";

// A search box with its own clear button (ui-design.md "Shared controls"): the × appears
// once there is text, clears it and returns focus to the box, and Esc does the same
// before it reaches anything around the box. The browser's own clear button is hidden,
// since only some browsers draw one. *From:* Carbon's search input.
export function SearchField({ value, onValueChange, className = "", clearLabel = "Clear search", disabled, ...input }:
  Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
    value: string;
    onValueChange: (value: string) => void;
    clearLabel?: string;
  }) {
  const box = useRef<HTMLInputElement>(null);
  const clear = () => { onValueChange(""); box.current?.focus(); };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    input.onKeyDown?.(e);
    if (e.key === "Escape" && value && !e.defaultPrevented) {
      e.preventDefault();
      e.stopPropagation();
      clear();
    }
  };
  return (
    <span className={`search-field ${className}`.trim()}>
      <input {...input} ref={box} type="search" value={value} disabled={disabled}
             onChange={(e) => onValueChange(e.target.value)} onKeyDown={onKeyDown} />
      {value && !disabled && (
        <button type="button" className="search-clear" aria-label={clearLabel} title={`${clearLabel} (Esc)`}
                onClick={clear}><span aria-hidden="true">×</span></button>
      )}
    </span>
  );
}
