import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";
import { Icon } from "./Icon";
import { Modal } from "./ui";
import { UnconfirmedError } from "../lib/api";

type Tone = "up" | "down" | "info";
interface Toast { id: number; tone: Tone; title: string; body?: string }
interface ConfirmOpts { title: string; body: ReactNode; confirmLabel?: string; danger?: boolean }

interface Feedback {
  toast: (tone: Tone, title: string, body?: string) => void;
  confirm: (o: ConfirmOpts) => Promise<boolean>;
  /** Run an API action with a confirmation (optional) and success/error toasts. */
  run: <T>(fn: () => Promise<T>, o: { success: string; confirm?: ConfirmOpts }) => Promise<T | undefined>;
}

const Ctx = createContext<Feedback | null>(null);
export const useFeedback = () => useContext(Ctx)!;

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pending, setPending] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null);
  const seq = useRef(0);

  const toast = useCallback((tone: Tone, title: string, body?: string) => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-3), { id, tone, title, body }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "down" ? 8000 : 4500);
  }, []);

  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => setPending({ ...o, resolve })), []);

  const run = useCallback(
    async <T,>(fn: () => Promise<T>, o: { success: string; confirm?: ConfirmOpts }) => {
      if (o.confirm && !(await confirm(o.confirm))) return undefined;
      try {
        const res = await fn();
        const msg = res && typeof res === "object" ? (res as any).message : undefined;
        toast("up", o.success, typeof msg === "string" ? msg : undefined);
        return res;
      } catch (e: any) {
        if (e instanceof UnconfirmedError)
          toast("info", "Not confirmed — check Portfolio before retrying", `${e.message}. The order may have been placed.`);
        else toast("down", "Action failed", e?.message || String(e));
        return undefined;
      }
    },
    [confirm, toast],
  );

  const close = (v: boolean) => {
    pending?.resolve(v);
    setPending(null);
  };

  return (
    <Ctx.Provider value={{ toast, confirm, run }}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <Icon name={t.tone === "up" ? "check" : t.tone === "down" ? "alert" : "info"} />
            <div className="grow">
              <b>{t.title}</b>
              {t.body && <div className="muted" style={{ fontSize: 12.5 }}>{t.body}</div>}
            </div>
          </div>
        ))}
      </div>
      {pending && (
        <Modal title={pending.title} onClose={() => close(false)}
          footer={
            <>
              <button className="btn ghost" onClick={() => close(false)}>Cancel</button>
              <button className={`btn ${pending.danger ? "sell" : "primary"}`} autoFocus onClick={() => close(true)}>
                {pending.confirmLabel || "Confirm"}
              </button>
            </>
          }>
          <div className="muted">{pending.body}</div>
        </Modal>
      )}
    </Ctx.Provider>
  );
}
