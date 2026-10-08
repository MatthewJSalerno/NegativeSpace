import { useId, type InputHTMLAttributes } from "react";

export function Field({ label, hint, error, id: givenId, fullWidth = false, ...input }: InputHTMLAttributes<HTMLInputElement> & {
  label: string; hint?: string; error?: string; fullWidth?: boolean;
}) {
  const generated = useId();
  const id = givenId ?? generated;
  return <div className="form-field" data-width={fullWidth ? "full" : undefined}>
    <label htmlFor={id}>{label}</label>
    {hint && <p id={`${id}-hint`} className="muted">{hint}</p>}
    <input {...input} id={id} aria-invalid={!!error || undefined}
      aria-describedby={[hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined} />
    {error && <p id={`${id}-error`} className="error field-error">{error}</p>}
  </div>;
}
