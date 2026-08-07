import {
  createContext,
  type FormEvent,
  type PropsWithChildren,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";


export type NoticeKind = "success" | "error" | "info";

interface Notice {
  id: number;
  kind: NoticeKind;
  message: string;
}

interface NoticeContextValue {
  notify: (kind: NoticeKind, message: string) => void;
}

const NoticeContext = createContext<NoticeContextValue>({ notify: () => undefined });


export function NoticeProvider({ children }: PropsWithChildren) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);

  const notify = useCallback(
    (kind: NoticeKind, message: string) => {
      const id = nextId.current++;
      setNotices((current) => [...current.slice(-4), { id, kind, message }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 8000 : 4500);
    },
    [dismiss],
  );

  return (
    <NoticeContext.Provider value={{ notify }}>
      {children}
      <div className="notice-stack" aria-live="polite" aria-atomic="false">
        {notices.map((notice) => (
          <div className={`notice notice-${notice.kind}`} key={notice.id} role="status">
            <span>{notice.message}</span>
            <button
              type="button"
              className="icon-button"
              aria-label="Dismiss notification"
              title="Dismiss notification"
              onClick={() => dismiss(notice.id)}
              data-smart-hover
            >
              X
            </button>
          </div>
        ))}
      </div>
    </NoticeContext.Provider>
  );
}


export function useNotices(): NoticeContextValue {
  return useContext(NoticeContext);
}


export function useSmartHover(): void {
  useEffect(() => {
    const update = (target: HTMLElement) => {
      const rect = target.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const grow = Math.min(rect.width, rect.height) * 0.05;
      target.style.setProperty("--hover-scale-x", String((rect.width + grow) / rect.width));
      target.style.setProperty("--hover-scale-y", String((rect.height + grow) / rect.height));
    };
    const pointer = (event: Event) => {
      const target = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-smart-hover]");
      if (target) update(target);
    };
    document.addEventListener("pointerover", pointer);
    document.addEventListener("focusin", pointer);
    return () => {
      document.removeEventListener("pointerover", pointer);
      document.removeEventListener("focusin", pointer);
    };
  }, []);
}


interface OverlayProps {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
}


export function Overlay({ title, children, onClose, className = "" }: OverlayProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    dialogRef.current?.focus();
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current || !dialogRef.current) return;
    const rect = dialogRef.current.getBoundingClientRect();
    const wantedX = drag.current.x + event.clientX - drag.current.startX;
    const wantedY = drag.current.y + event.clientY - drag.current.startY;
    const centeredLeft = (window.innerWidth - rect.width) / 2;
    const centeredTop = (window.innerHeight - rect.height) / 2;
    const x = Math.min(
      window.innerWidth - rect.width - 8 - centeredLeft,
      Math.max(8 - centeredLeft, wantedX),
    );
    const y = Math.min(
      window.innerHeight - rect.height - 8 - centeredTop,
      Math.max(8 - centeredTop, wantedY),
    );
    setOffset({ x, y });
  };

  return (
    <div className="overlay-backdrop" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        className={`overlay-dialog ${className}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="overlay-title"
        tabIndex={-1}
        style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}
      >
        <div
          className="overlay-header"
          onPointerDown={(event) => {
            if ((event.target as HTMLElement).closest("button")) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            drag.current = { x: offset.x, y: offset.y, startX: event.clientX, startY: event.clientY };
          }}
          onPointerMove={move}
          onPointerUp={(event) => {
            drag.current = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
          }}
        >
          <h2 id="overlay-title">{title}</h2>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Close dialog"
            title="Close dialog"
            data-smart-hover
          >
            X
          </button>
        </div>
        <div className="overlay-content">{children}</div>
      </div>
    </div>
  );
}


interface ConfirmProps {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  pendingLabel?: string;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}


export function ConfirmOverlay({
  title,
  description,
  confirmLabel,
  pendingLabel = "Working...",
  onConfirm,
  onClose,
}: ConfirmProps) {
  const [pending, setPending] = useState(false);
  return (
    <Overlay title={title} onClose={pending ? () => undefined : onClose} className="confirm-dialog">
      <div className="confirm-copy">{description}</div>
      <div className="form-actions">
        <button type="button" onClick={onClose} disabled={pending} data-smart-hover>
          Cancel
        </button>
        <button
          type="button"
          className="danger-button"
          disabled={pending}
          onClick={async () => {
            setPending(true);
            try {
              await onConfirm();
            } finally {
              setPending(false);
            }
          }}
          data-smart-hover
        >
          {pending ? pendingLabel : confirmLabel}
        </button>
      </div>
    </Overlay>
  );
}


export function SearchField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="search-field">
      <span>SEARCH</span>
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
      />
    </label>
  );
}


export function EmptyState({ children }: PropsWithChildren) {
  return <div className="empty-state">{children}</div>;
}


export function LoadingBlock({ label = "Loading Chronos state..." }: { label?: string }) {
  return (
    <div className="loading-block" role="status">
      <span className="status-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}


export function SubmitButton({
  pending,
  label,
  pendingLabel,
}: {
  pending: boolean;
  label: string;
  pendingLabel: string;
}) {
  return (
    <button type="submit" disabled={pending} data-smart-hover>
      {pending ? pendingLabel : label}
    </button>
  );
}


export function useSubmit(
  action: () => Promise<void>,
): { pending: boolean; submit: (event: FormEvent) => Promise<void> } {
  const [pending, setPending] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    try {
      await action();
    } finally {
      setPending(false);
    }
  };
  return { pending, submit };
}

