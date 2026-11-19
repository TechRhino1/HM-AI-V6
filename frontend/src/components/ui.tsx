import { createContext, ReactNode, useContext, useEffect } from "react";
import { Icon, IconName } from "./Icon";

/** Extra header control injected by a container (the Overview widget menu) into every Card inside it. */
export const CardMenuCtx = createContext<ReactNode>(null);

export function Card({ title, sub, actions, children, flush, className = "" }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string;
}) {
  const menu = useContext(CardMenuCtx);
  if (menu) actions = <>{actions}{menu}</>;
  return (
    <CardMenuCtx.Provider value={null}>
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div className="grow">
            {title && <h2>{title}</h2>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {actions && <div className="actions">{actions}</div>}
        </header>
      )}
      <div className={`card-body ${flush ? "flush" : ""}`}>{children}</div>
    </section>
    </CardMenuCtx.Provider>
  );
}

export function Stat({ label, value, hint, tone, icon, children, onClick, title }: {
  label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: string; icon?: IconName; children?: ReactNode; onClick?: () => void; title?: string;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className={`card stat ${onClick ? "clickable" : ""}`} onClick={onClick} title={title} {...(onClick ? { type: "button" as const } : {})}>
      <div className="label">{icon && <Icon name={icon} size={14} />}{label}</div>
      <div className={`value ${tone || ""}`}>{value}</div>
      {hint && <div className="hint">{hint}</div>}
      {children}
    </Tag>
  );
}

export function Meter({ value, max = 100, tone }: { value: number; max?: number; tone?: "good" | "warn" | "danger" }) {
  const w = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className={`meter ${tone || ""}`} role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <i style={{ width: `${w}%` }} />
    </div>
  );
}

export function Badge({ tone, children, dot }: { tone?: "up" | "down" | "warn" | "accent" | "flat"; children: ReactNode; dot?: boolean }) {
  return <span className={`badge ${tone || ""}`}>{dot && <span className={`dot ${tone || ""}`} />}{children}</span>;
}

export const sideTone = (side: unknown) => {
  const s = String(side || "").toUpperCase();
  return s.includes("BUY") || s === "LONG" || s.includes("BULL") ? "up" : s.includes("SELL") || s === "SHORT" || s.includes("BEAR") ? "down" : "flat";
};

export function Seg<T extends string>({ value, options, onChange, full, disabled }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; full?: boolean; disabled?: boolean;
}) {
  return (
    <div className={`seg ${full ? "full" : ""}`} role="radiogroup">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value}
          className={o.value === value ? "on" : ""} disabled={disabled} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className="switch" title={label}>
      <input type="checkbox" checked={checked} disabled={disabled} aria-label={label} onChange={(e) => onChange(e.target.checked)} />
      <i />
    </label>
  );
}

export function Empty({ title, children, icon = "info" }: { title: ReactNode; children?: ReactNode; icon?: IconName }) {
  return (
    <div className="empty">
      <Icon name={icon} size={22} />
      <b>{title}</b>
      {children && <div>{children}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert down with-icon" role="alert">
      <Icon name="alert" />
      <div className="grow">{error}</div>
      {onRetry && <button className="btn sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" style={{ padding: 16 }} aria-busy="true">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, wide, drawer }: {
  title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean; drawer?: boolean;
}) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  const body = (
    <>
      <div className="modal-head">
        <h3 className="grow">{title}</h3>
        <button className="btn ghost icon-btn sm" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
      </div>
      <div className="modal-body">{children}</div>
      {footer && <div className="modal-foot">{footer}</div>}
    </>
  );
  if (drawer)
    return (
      <>
        <div className="overlay" onClick={onClose} />
        <aside className="drawer" role="dialog" aria-modal="true">{body}</aside>
      </>
    );
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">{body}</div>
    </div>
  );
}

export function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>
      ))}
    </dl>
  );
}
