"use client";

import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useRef } from "react";

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

  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    const focusFrame = window.requestAnimationFrame(() => sheetRef.current?.focus({ preventScroll: true }));
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
      returnFocusRef.current?.focus();
    };
  }, [open]);

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

  return <div className="bottom-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={sheetRef} tabIndex={-1} onKeyDown={keepFocusInSheet} className={`bottom-sheet ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={labelledBy} aria-describedby={describedBy}>
      <div className="bottom-sheet-handle" aria-hidden="true" />
      <header className="bottom-sheet-header">
        <div>{header}</div>
        <button type="button" className="bottom-sheet-close" onClick={onClose} aria-label={closeLabel} title={closeLabel}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </header>
      <div className="bottom-sheet-content">{children}</div>
    </section>
  </div>;
}
