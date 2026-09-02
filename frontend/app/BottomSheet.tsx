"use client";

import {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  ReactNode,
  TouchEvent as ReactTouchEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

type BottomSheetProps = {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  describedBy?: string;
  header: ReactNode;
  children: ReactNode;
  closeLabel?: string;
  className?: string;
};

export function BottomSheet({ open, onClose, labelledBy, describedBy, header, children, closeLabel = "完了", className = "" }: BottomSheetProps) {
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const sheetRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const closeTimerRef = useRef<number | null>(null);
  const closingRef = useRef(false);
  const dragRef = useRef({ identifier: -1, startY: 0, startedAt: 0, offset: 0 });
  const [isClosing, setIsClosing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);

  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  const requestClose = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    setIsDragging(false);
    setIsClosing(true);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    closeTimerRef.current = window.setTimeout(() => {
      onCloseRef.current();
      // A guarded onClose may intentionally leave the sheet open (for example,
      // while saving). Restore it instead of leaving an invisible modal mounted.
      closingRef.current = false;
      setIsClosing(false);
      setDragOffset(0);
    }, reducedMotion ? 0 : 280);
  }, []);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    const focusFrame = window.requestAnimationFrame(() => sheetRef.current?.focus({ preventScroll: true }));
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
      returnFocusRef.current?.focus();
    };
  }, [open, requestClose]);

  if (!open) return null;

  function keepFocusInSheet(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "Tab" || !sheetRef.current) return;
    const focusable = Array.from(sheetRef.current.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])"))
      .filter(element => element.offsetParent !== null);
    if (focusable.length === 0) { event.preventDefault(); return; }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === sheetRef.current)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === sheetRef.current)) {
      event.preventDefault(); first.focus();
    }
  }

  function startDrag(event: ReactTouchEvent<HTMLElement>) {
    if (event.touches.length !== 1 || isClosing) return;
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, select, textarea") || !target.closest(".bottom-sheet-handle, .bottom-sheet-header")) return;
    const touch = event.touches[0];
    dragRef.current = { identifier: touch.identifier, startY: touch.clientY, startedAt: performance.now(), offset: 0 };
    setIsDragging(true);
  }

  function moveDrag(event: ReactTouchEvent<HTMLElement>) {
    const touch = Array.from(event.touches).find(item => item.identifier === dragRef.current.identifier);
    if (!touch) return;
    const offset = Math.max(0, touch.clientY - dragRef.current.startY);
    dragRef.current.offset = offset;
    setDragOffset(offset);
  }

  function endDrag() {
    if (dragRef.current.identifier < 0) return;
    const elapsed = Math.max(performance.now() - dragRef.current.startedAt, 1);
    const offset = dragRef.current.offset;
    const shouldClose = offset >= 96 || (offset >= 24 && offset / elapsed >= 0.55);
    dragRef.current.identifier = -1;
    if (shouldClose) requestClose();
    else {
      setIsDragging(false);
      setDragOffset(0);
    }
  }

  function cancelDrag() {
    dragRef.current.identifier = -1;
    setIsDragging(false);
    setDragOffset(0);
  }

  const sheetStyle = { "--sheet-drag-y": `${dragOffset}px` } as CSSProperties;
  return <div className={`bottom-sheet-backdrop${isClosing ? " is-closing" : ""}`} onMouseDown={event => { if (event.target === event.currentTarget) requestClose(); }}>
    <section
      ref={sheetRef}
      tabIndex={-1}
      onKeyDown={keepFocusInSheet}
      onTouchStart={startDrag}
      onTouchMove={moveDrag}
      onTouchEnd={endDrag}
      onTouchCancel={cancelDrag}
      className={`bottom-sheet${isClosing ? " is-closing" : ""}${isDragging ? " is-dragging" : ""} ${className}`.trim()}
      style={sheetStyle}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
    >
      <div className="bottom-sheet-handle" aria-hidden="true" />
      <header className="bottom-sheet-header">
        <div>{header}</div>
        <button type="button" className="bottom-sheet-close" onClick={requestClose} aria-label={closeLabel} title={closeLabel}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </header>
      <div className="bottom-sheet-content">{children}</div>
    </section>
  </div>;
}
