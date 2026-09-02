import {
  type CSSProperties,
  createContext,
  type DragEvent,
  type FormEvent,
  type PropsWithChildren,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
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


export function ChronosMark({ compact = false }: { compact?: boolean }) {
  return (
    <img
      className={`chronos-mark ${compact ? "is-compact" : ""}`}
      src="/chronos-mark.png"
      alt="Chronos mark"
    />
  );
}


interface UniversalCardProps extends PropsWithChildren {
  ordinal: number;
  title?: string;
  span?: "1x" | "2x" | "4x";
  className?: string;
  reorderLabel?: string;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  onDragOver?: (event: DragEvent<HTMLElement>) => void;
  onDrop?: (event: DragEvent<HTMLElement>) => void;
  onMove?: (direction: -1 | 1) => void;
  style?: CSSProperties;
}


export function UniversalCard({
  ordinal,
  title,
  span = "4x",
  className = "",
  reorderLabel,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  onMove,
  style,
  children,
}: UniversalCardProps) {
  const handle = reorderLabel ? (
    <button
      type="button"
      className="drag-handle"
      draggable
      aria-label={`Reorder ${reorderLabel}. Use Alt+Arrow keys to move.`}
      title={`Reorder ${reorderLabel}`}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onKeyDown={(event) => {
        if (!event.altKey || !onMove) return;
        if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
          event.preventDefault();
          onMove(-1);
        } else if (event.key === "ArrowDown" || event.key === "ArrowRight") {
          event.preventDefault();
          onMove(1);
        }
      }}
    >
      <span /><span /><span /><span />
    </button>
  ) : null;
  return (
    <article
      className={`universal-card card-${span} ${title ? "has-title" : ""} ${className}`}
      onDragOver={onDragOver}
      onDrop={onDrop}
      style={style}
      aria-label={title || reorderLabel}
      data-smart-hover={reorderLabel ? "" : undefined}
    >
      {title ? (
        <header className="universal-card-header">
          <span className="card-ordinal">{String(ordinal).padStart(2, "0")}</span>
          <h2>{title}</h2>
          {handle}
        </header>
      ) : (
        <>
          <span className="card-ordinal card-ordinal-floating">{String(ordinal).padStart(2, "0")}</span>
          {handle}
        </>
      )}
      <div className="universal-card-body">{children}</div>
    </article>
  );
}


export function CardPlaceholder({ span = "4x" }: { span?: "1x" | "2x" | "4x" }) {
  return <div className={`card-placeholder card-${span}`} aria-hidden="true" />;
}


export function CollectionCommandBar({ children, label }: PropsWithChildren<{ label: string }>) {
  return <div className="collection-command-bar" role="toolbar" aria-label={label}>{children}</div>;
}


export function StatusSquare({ state }: { state: "success" | "danger" | "neutral" }) {
  return <span className={`status-square status-square-${state}`} aria-hidden="true" />;
}


interface OverlayProps {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
  dismissible?: boolean;
}


export function Overlay({ title, children, onClose, className = "", dismissible = true }: OverlayProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const invoker = useRef<HTMLElement | null>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);

  useEffect(() => {
    invoker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && dismissible) onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
      )];
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", keyboard);
    const first = dialogRef.current?.querySelector<HTMLElement>("input, select, textarea, button");
    (first ?? dialogRef.current)?.focus();
    return () => {
      window.removeEventListener("keydown", keyboard);
      invoker.current?.focus();
    };
  }, [dismissible, onClose]);

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
    <div className="overlay-backdrop" onPointerDown={(event) => event.target === event.currentTarget && dismissible && onClose()}>
      <div
        ref={dialogRef}
        className={`overlay-dialog ${className}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
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
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            disabled={!dismissible}
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
    <Overlay title={title} onClose={onClose} className="confirm-dialog" dismissible={!pending}>
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
