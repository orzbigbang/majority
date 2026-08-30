"use client";

import { CSSProperties, ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";

export const REACTIONS = [
  { id: "clap", label: "拍手" },
  { id: "laugh", label: "大笑い" },
  { id: "wow", label: "びっくり" },
  { id: "like", label: "いいね" },
  { id: "shy", label: "照れ笑い" },
] as const;

export type ReactionId = (typeof REACTIONS)[number]["id"];
export type ReactionTarget = { id: string; username: string };
export type ReactionEvent = {
  event_id: string;
  reaction_id: ReactionId;
  sender_id: string;
  sender_username: string;
  target_player_id: string;
  target_username: string;
  scope_id: string;
};

type Point = { x: number; y: number };

export function ReactionAvatarButton({ target, disabled = false, compact = false, onSelect, children }: {
  target: ReactionTarget;
  disabled?: boolean;
  compact?: boolean;
  onSelect: (target: ReactionTarget, anchor: HTMLElement) => void;
  children: ReactNode;
}) {
  if (disabled) return <span className={`reaction-avatar-static${compact ? " compact" : ""}`}>{children}</span>;
  return <button
    type="button"
    className={`reaction-avatar-trigger${compact ? " compact" : ""}`}
    data-reaction-player-id={target.id}
    aria-label={`${target.username}さんにリアクションを送る`}
    onClick={event => onSelect(target, event.currentTarget)}
  >{children}<span className="reaction-avatar-hint" aria-hidden="true">＋</span></button>;
}

export function AnimatedReactionSticker({ reaction, preview = false }: { reaction: ReactionId; preview?: boolean }) {
  const common = { viewBox: "0 0 72 72", role: "img", "aria-hidden": true } as const;
  return <span className={`reaction-sticker reaction-${reaction}${preview ? " is-preview" : " is-burst"}`}>
    {reaction === "clap" && <svg {...common}>
      <path className="sticker-spark spark-one" d="M13 17l-5-5m11 1-1-8M55 16l6-6m-1 13 8-1" />
      <path className="sticker-hand clap-back" d="M38 51c-4-4-9-12-10-17l-2-10c-.4-3 4-4 5-1l3 9-1-17c-.2-3 4-4 5-1l2 16 1-18c.2-3 5-3 5 1l1 17 3-14c.7-3 5-2 5 2l-2 18c-.6 7-4 14-9 18z" />
      <path className="sticker-hand clap-front" d="M30 58c-6-3-13-10-15-15l-4-9c-1-3 3-5 5-2l5 8-5-16c-1-3 3-5 5-2l6 15-4-17c-.7-3 4-4 5-1l6 16-1-14c0-3 4-4 5-1l3 18c1 7-1 14-5 19z" />
    </svg>}
    {reaction === "laugh" && <svg {...common}>
      <circle className="sticker-face" cx="36" cy="35" r="25" />
      <path className="sticker-line" d="M20 30c4-5 8-5 12 0m8 0c4-5 8-5 12 0" />
      <path className="sticker-mouth" d="M23 39h26c-2 13-22 15-26 0z" />
      <path className="sticker-tear tear-left" d="M16 31c-7 9-5 14 0 14 6 0 7-6 0-14z" />
      <path className="sticker-tear tear-right" d="M56 31c-7 9-5 14 0 14 6 0 7-6 0-14z" />
    </svg>}
    {reaction === "wow" && <svg {...common}>
      <circle className="sticker-ring" cx="36" cy="36" r="31" />
      <circle className="sticker-face" cx="36" cy="36" r="25" />
      <circle className="sticker-eye" cx="27" cy="30" r="3" /><circle className="sticker-eye" cx="45" cy="30" r="3" />
      <ellipse className="sticker-mouth-dark" cx="36" cy="45" rx="7" ry="10" />
    </svg>}
    {reaction === "like" && <svg {...common}>
      <path className="sticker-spark like-spark" d="M54 12v9m-5-4h10M20 11l2 6m-7-2 6 3" />
      <path className="sticker-cuff" d="M12 39h14v24H12z" />
      <path className="sticker-hand like-hand" d="M25 60V39c8-5 10-12 12-23 .7-4 7-5 9-1 2 5 0 11-2 16h12c5 0 7 4 6 8l-5 17c-1 4-4 6-8 6z" />
    </svg>}
    {reaction === "shy" && <svg {...common}>
      <circle className="sticker-face shy-face" cx="36" cy="35" r="25" />
      <path className="sticker-line" d="M20 30c4-5 8-5 12 0m8 0c4-5 8-5 12 0" />
      <circle className="sticker-blush blush-left" cx="20" cy="39" r="4" /><circle className="sticker-blush blush-right" cx="52" cy="39" r="4" />
      <path className="sticker-hand shy-hand" d="M25 54c-4-6-2-14 3-17l5 7-1-15c0-3 4-4 5-1l3 14 1-13c0-3 4-3 5 0l1 14 3-10c1-3 5-2 5 1l-2 14c-1 7-7 13-14 14z" />
    </svg>}
  </span>;
}

export function ReactionPicker({ target, anchor, onClose, onSend }: {
  target: ReactionTarget | null;
  anchor: HTMLElement | null;
  onClose: () => void;
  onSend: (reaction: ReactionId) => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<Point>({ x: 0, y: 0 });

  useLayoutEffect(() => {
    if (!target || !anchor) return;
    const update = () => {
      const rect = anchor.getBoundingClientRect();
      const panelHalfWidth = Math.min(392, window.innerWidth - 24) / 2;
      const x = Math.min(window.innerWidth - panelHalfWidth - 12, Math.max(panelHalfWidth + 12, rect.left + rect.width / 2));
      setPosition({ x, y: rect.bottom + 12 });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [target, anchor]);

  useEffect(() => {
    if (!target) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    const onPointerDown = (event: PointerEvent) => {
      if (!panelRef.current?.contains(event.target as Node) && !anchor?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    requestAnimationFrame(() => panelRef.current?.querySelector<HTMLButtonElement>("button")?.focus());
    return () => { document.removeEventListener("keydown", onKeyDown); document.removeEventListener("pointerdown", onPointerDown); };
  }, [target, anchor, onClose]);

  if (!target) return null;
  return <div ref={panelRef} className="reaction-picker" role="dialog" aria-label={`${target.username}さんへのリアクション`} style={{ "--picker-x": `${position.x}px`, "--picker-y": `${position.y}px` } as CSSProperties}>
    <div className="reaction-picker-copy"><strong>{target.username}</strong><span>さんへ</span></div>
    <div className="reaction-options">{REACTIONS.map(item => <button key={item.id} type="button" className="reaction-option" aria-label={item.label} onClick={() => onSend(item.id)}>
      <AnimatedReactionSticker reaction={item.id} preview /><small>{item.label}</small>
    </button>)}</div>
  </div>;
}

function ReactionBurst({ event, index }: { event: ReactionEvent; index: number }) {
  const [target, setTarget] = useState<Point | null>(null);
  const [source, setSource] = useState<Point | null>(null);
  useLayoutEffect(() => {
    const buttons = [...document.querySelectorAll<HTMLElement>("[data-reaction-player-id]")];
    const targetElement = buttons.find(item => item.dataset.reactionPlayerId === event.target_player_id);
    const sourceElement = buttons.find(item => item.dataset.reactionPlayerId === event.sender_id);
    if (!targetElement) return;
    const targetRect = targetElement.getBoundingClientRect();
    const sourceRect = sourceElement?.getBoundingClientRect();
    setTarget({ x: targetRect.left + targetRect.width / 2, y: targetRect.top + targetRect.height / 2 });
    setSource(sourceRect ? { x: sourceRect.left + sourceRect.width / 2, y: sourceRect.top + sourceRect.height / 2 } : { x: targetRect.left - 36, y: targetRect.bottom + 36 });
    targetElement.classList.remove("reaction-hit");
    requestAnimationFrame(() => targetElement.classList.add("reaction-hit"));
    const hitTimer = window.setTimeout(() => targetElement.classList.remove("reaction-hit"), 950);
    return () => { window.clearTimeout(hitTimer); targetElement.classList.remove("reaction-hit"); };
  }, [event]);
  if (!target || !source) return null;
  const offset = (index % 3 - 1) * 14;
  return <div className="reaction-burst" style={{
    "--burst-x": `${target.x + offset}px`, "--burst-y": `${target.y}px`,
    "--from-x": `${source.x - target.x}px`, "--from-y": `${source.y - target.y}px`,
  } as CSSProperties} aria-hidden="true">
    <span className="reaction-flight"><AnimatedReactionSticker reaction={event.reaction_id} /><i className="reaction-confetti confetti-one" /><i className="reaction-confetti confetti-two" /><i className="reaction-confetti confetti-three" /></span>
  </div>;
}

export function ReactionAnimationLayer({ events }: { events: ReactionEvent[] }) {
  return <div className="reaction-animation-layer" aria-hidden="true">{events.map((event, index) => <ReactionBurst key={event.event_id} event={event} index={index} />)}</div>;
}
