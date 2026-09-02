"use client";

import { FormEvent, useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { BottomSheet } from "./BottomSheet";
import { apiMessage } from "./ja";
import { PlayerName } from "./PlayerName";
import { useRoomExitNotice } from "./useRoomExit";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const identityKey = "party-quiz-player";
const avatarStyleVersion = process.env.NEXT_PUBLIC_AVATAR_STYLE_VERSION || "cute-animal-v1";
type Identity = { player_id: string; username: string; avatar_url?: string; session_id?: string };
type LobbyRoom = { room_id: string; title: string | null; status: string; player_count: number; max_players: number; game_name: string };
type RoomSetup = { max_players: number; round_count: number; selection_duration: number; question_duration: number; between_question_duration: number };
type RoomSetupDraft = { [Key in keyof RoomSetup]: string };
type IdentityEntryStep = "idle" | "creating-avatar" | "entering";
const defaultRoomSetup: RoomSetup = { max_players: 12, round_count: 1, selection_duration: 15, question_duration: 20, between_question_duration: 5 };

function setupDraft(values: RoomSetup): RoomSetupDraft {
  return {
    max_players: String(values.max_players),
    round_count: String(values.round_count),
    selection_duration: String(values.selection_duration),
    question_duration: String(values.question_duration),
    between_question_duration: String(values.between_question_duration),
  };
}

function normalizedNumber(value: string, minimum: number, maximum: number, step: number, fallback: number): string {
  const parsed = value === "" ? fallback : Number(value);
  const finite = Number.isFinite(parsed) ? parsed : fallback;
  const snapped = minimum + Math.round((finite - minimum) / step) * step;
  return String(Math.min(maximum, Math.max(minimum, snapped)));
}

function SetupNumberInput({ label, hint, value, minimum, maximum, step, onChange, onBlur }: {
  label: string;
  hint: string;
  value: string;
  minimum: number;
  maximum: number;
  step: number;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const inputId = useId();
  const numericValue = Number(value);
  const hasValue = value !== "" && Number.isFinite(numericValue);
  function stepValue(direction: -1 | 1) {
    const startingValue = hasValue ? numericValue : direction === 1 ? minimum - step : minimum;
    onChange(String(Math.min(maximum, Math.max(minimum, startingValue + direction * step))));
  }
  return <div className="room-setup-field"><label htmlFor={inputId}>{label}</label><div className="number-stepper"><input id={inputId} type="number" inputMode="numeric" min={minimum} max={maximum} step={step} value={value} onChange={event => onChange(event.target.value)} onBlur={onBlur} required /><div className="number-stepper-controls"><button type="button" aria-label={`${label}を増やす`} disabled={hasValue && numericValue >= maximum} onMouseDown={event => event.preventDefault()} onClick={() => stepValue(1)}>▲</button><button type="button" aria-label={`${label}を減らす`} disabled={hasValue && numericValue <= minimum} onMouseDown={event => event.preventDefault()} onClick={() => stepValue(-1)}>▼</button></div></div><small>{hint}</small></div>;
}

function savedIdentity(): Identity | null {
  try { return JSON.parse(localStorage.getItem(identityKey) || "null"); } catch { return null; }
}

function currentAvatarUrl(avatarUrl?: string): string | undefined {
  if (!avatarUrl) return undefined;
  return `${avatarUrl.split("?")[0]}?v=${encodeURIComponent(avatarStyleVersion)}`;
}

function preloadImage(src?: string): Promise<void> {
  if (!src) return Promise.resolve();
  return new Promise(resolve => {
    const image = new Image();
    const timeout = window.setTimeout(resolve, 3000);
    const finish = () => { window.clearTimeout(timeout); resolve(); };
    image.onload = finish;
    image.onerror = finish;
    image.src = src;
    if (image.complete) finish();
  });
}

export default function Home() {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [identityResolved, setIdentityResolved] = useState(false);
  const [nickname, setNickname] = useState("");
  const [rooms, setRooms] = useState<LobbyRoom[]>([]);
  const [message, setMessage] = useState("");
  const [roomsRefreshing, setRoomsRefreshing] = useState(false);
  const [roomsLoaded, setRoomsLoaded] = useState(false);
  const [destination, setDestination] = useState<string>();
  const [roomSetupOpen, setRoomSetupOpen] = useState(false);
  const [roomSetup, setRoomSetup] = useState<RoomSetupDraft>(() => setupDraft(defaultRoomSetup));
  const [availableQuestionCount, setAvailableQuestionCount] = useState(3);
  const [identityEntryStep, setIdentityEntryStep] = useState<IdentityEntryStep>("idle");
  const [roomEntryStep, setRoomEntryStep] = useState<"idle" | "creating" | "entering">("idle");
  const creatingIdentity = identityEntryStep !== "idle";
  const creatingRoom = roomEntryStep !== "idle";
  const { notice: roomExitNotice, clearNotice: clearRoomExitNotice } = useRoomExitNotice();

  function editSetup(field: keyof RoomSetupDraft, value: string) {
    const withoutLeadingZeroes = value === "" ? "" : value.replace(/^0+(?=\d)/, "");
    setRoomSetup(current => ({ ...current, [field]: withoutLeadingZeroes }));
  }

  function normalizeSetup(field: keyof RoomSetupDraft, minimum: number, maximum: number, step: number, fallback: number) {
    setRoomSetup(current => ({ ...current, [field]: normalizedNumber(current[field], minimum, maximum, step, fallback) }));
  }

  async function loadRooms() {
    try {
      const response = await fetch(`${api}/api/rooms`);
      if (!response.ok) throw new Error();
      setRooms(await response.json());
      setRoomsLoaded(true);
    } catch { setMessage("ゲームサーバーに接続できません。しばらくしてからもう一度お試しください。"); }
  }

  async function refreshRooms() {
    clearRoomExitNotice();
    setMessage("");
    setRoomsRefreshing(true);
    try { await loadRooms(); } finally { setRoomsRefreshing(false); }
  }

  async function loadRoomOptions() {
    try {
      const response = await fetch(`${api}/api/room-options`);
      if (!response.ok) return;
      const data = await response.json();
      setAvailableQuestionCount(data.available_question_count);
      setRoomSetup(setupDraft({
        max_players: Math.min(100, Math.max(2, data.defaults.max_players)),
        round_count: Math.max(1, Math.min(10, data.defaults.round_count)),
        selection_duration: Number(normalizedNumber(String(data.defaults.selection_duration), 5, 60, 5, 15)),
        question_duration: Number(normalizedNumber(String(data.defaults.question_duration), 10, 60, 10, 20)),
        between_question_duration: Number(normalizedNumber(String(data.defaults.between_question_duration), 5, 30, 5, 5)),
      }));
    } catch { /* Defaults remain available when options cannot be loaded. */ }
  }

  useEffect(() => {
    const existing = savedIdentity();
    if (existing?.player_id && existing.username) {
      const restored = { ...existing, avatar_url: currentAvatarUrl(existing.avatar_url) };
      if (restored.avatar_url !== existing.avatar_url) localStorage.setItem(identityKey, JSON.stringify(restored));
      setIdentity(restored);
      fetch(`${api}/api/players/identity`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(existing),
      }).then(response => response.ok ? response.json() : null).then(data => {
        if (data) {
          const synced = { ...existing, ...data };
          localStorage.setItem(identityKey, JSON.stringify(synced));
          setIdentity(synced);
        }
      }).catch(() => undefined);
    }
    setIdentityResolved(true);
    const searchParams = new URLSearchParams(window.location.search);
    setDestination(searchParams.get("room")?.toUpperCase());
    loadRooms();
    void loadRoomOptions();
    const interval = window.setInterval(loadRooms, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (identity && destination) router.replace(`/room/${destination}`);
  }, [identity, destination, router]);

  useEffect(() => {
    if (!identityResolved) return;
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [identityResolved, identity?.player_id]);

  async function saveIdentity(event: FormEvent) {
    event.preventDefault();
    if (creatingIdentity) return;
    setIdentityEntryStep("creating-avatar");
    setMessage("");
    try {
      const response = await fetch(`${api}/api/players/identity`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: nickname }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(apiMessage(data.detail, "ニックネームを保存できませんでした。"));
      localStorage.setItem(identityKey, JSON.stringify(data));
      setIdentityEntryStep("entering");
      await preloadImage(data.avatar_url ? `${api}${data.avatar_url}` : undefined);
      await new Promise<void>(resolve => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve())));
      setIdentity(data);
      setIdentityEntryStep("idle");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ニックネームを保存できませんでした。");
      setIdentityEntryStep("idle");
    }
  }

  function enterRoom(roomId: string) { router.push(`/room/${roomId}`); }

  async function createRoom(event: FormEvent) {
    event.preventDefault();
    if (!identity || creatingRoom) return;
    setRoomSetupOpen(false);
    setRoomEntryStep("creating");
    setMessage("");
    try {
      const response = await fetch(`${api}/api/rooms`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: identity.username,
          player_id: identity.player_id,
          session_id: identity.session_id,
          max_players: Number(roomSetup.max_players),
          round_count: Number(roomSetup.round_count),
          selection_duration: Number(roomSetup.selection_duration),
          question_duration: Number(roomSetup.question_duration),
          between_question_duration: Number(roomSetup.between_question_duration),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(apiMessage(data.detail, "ルームを作成できませんでした。"));
      const updatedIdentity = { ...identity, player_id: data.player_id, session_id: data.session_id };
      localStorage.setItem(identityKey, JSON.stringify(updatedIdentity));
      setIdentity(updatedIdentity);
      setRoomEntryStep("entering");
      await new Promise<void>(resolve => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve())));
      router.replace(`/room/${data.room.room_id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ルームを作成できませんでした。");
      setRoomEntryStep("idle");
    }
  }

  if (!identityResolved) return <main id="main-content" className="loading-stage"><span className="loading-orbit" aria-hidden="true" /><p role="status">ロビーを準備しています…</p></main>;

  if (!identity) return <><main id="main-content" className="lobby lobby-intro" inert={creatingIdentity || undefined} aria-busy={creatingIdentity}>
    <header className="page-heading intro-heading">
      <a className="brand-lockup" href="/" aria-label="マジョリティ ホーム">マジョリティ</a>
    </header>
    <section className="hero hero-stage" aria-labelledby="welcome-title">
      <span className="live-kicker"><i aria-hidden="true" /> みんなそろったら、すぐスタート</span>
      <h1 id="welcome-title">今夜は、<br /><em>どっち？</em></h1>
      <p>正解はありません。あるのは思いがけない仲間だけ。まずはニックネームを決めて、今夜の二択に参加しましょう。</p>
    </section>
    <section className="card identity-card">
      <span className="step-label">参加パス · 01</span>
      <h2>なんて呼べばいい？</h2>
      <form onSubmit={saveIdentity} aria-describedby={message ? "identity-message" : undefined}>
        <label htmlFor="nickname">ニックネーム</label>
        <input id="nickname" name="nickname" autoComplete="nickname" spellCheck={false} value={nickname} onChange={event => setNickname(event.target.value)} maxLength={30} placeholder="例：ユウ…" required />
        <button className="wide" disabled={creatingIdentity}>{creatingIdentity ? "準備しています…" : <>ロビーへ進む <span aria-hidden="true">→</span></>}</button>
      </form>
      {message && <p id="identity-message" className="error" role="alert">{message}</p>}
    </section>
    <footer className="lobby-footer"><a href="/admin">管理者入口</a></footer>
  </main>
    {creatingIdentity && <div className="room-entry-overlay" role="dialog" aria-modal="true" aria-labelledby="identity-entry-title"><section className="card room-entry-progress"><span className="loading-orbit" aria-hidden="true" /><span className="step-label">初回参加を準備中</span><h2 id="identity-entry-title" aria-live="polite">{identityEntryStep === "creating-avatar" ? "プロフィール画像を作成しています" : "ロビーを準備しています"}</h2><ol><li className="done">ニックネームを確認</li><li className={identityEntryStep === "creating-avatar" ? "active" : "done"}>プロフィール画像を作成</li><li className={identityEntryStep === "entering" ? "active" : ""}>ロビーへ入場</li></ol><p>このままお待ちください。操作は必要ありません。</p></section></div>}
  </>;

  return <><main id="main-content" className="lobby" inert={creatingRoom || roomSetupOpen || undefined} aria-busy={creatingRoom}>
    <header className="page-heading lobby-heading">
      <div className="identity-summary">
        <a className="profile-avatar-link" href="/profile" aria-label="自分のプロフィールを開く">
          {identity.avatar_url && <img className="avatar" width="56" height="56" src={`${api}${identity.avatar_url}`} alt="" />}
          <span>プロフィール</span>
        </a>
        <h1><PlayerName name={identity.username} /></h1>
      </div>
    </header>
    {roomExitNotice && <p className="notice room-not-found-notice" role="alert"><strong>{roomExitNotice.title}</strong><span>{roomExitNotice.detail}</span></p>}
    {destination && <p className="notice" role="status">ルーム番号 {destination} を確認しました。下の一覧から参加してください。</p>}
    <section className="card lobby-board" aria-labelledby="lobby-title">
      <div className="section-heading">
        <div><span className="step-label">参加受付中</span><h2 id="lobby-title">参加するルームを選ぶ</h2><p className="muted room-refresh-status" aria-live="polite">{roomsRefreshing ? "ルームを更新しています…" : roomsLoaded ? "最新のルームを表示中 · 5秒ごとに自動更新" : "参加できるルームを確認しています…"}</p></div>
        <div className="button-row lobby-actions"><button type="button" className="create-room-button" disabled={creatingRoom || availableQuestionCount < 1} onClick={() => setRoomSetupOpen(true)}><span aria-hidden="true">＋</span>{creatingRoom ? "作成中…" : "ルームを作成"}</button><button type="button" className={`refresh-room-button secondary${roomsRefreshing ? " is-refreshing" : ""}`} disabled={creatingRoom || roomsRefreshing} onClick={() => void refreshRooms()}><span aria-hidden="true">↻</span> {roomsRefreshing ? "更新中" : "更新"}</button></div>
      </div>
      {rooms.length === 0 ? <div className="empty"><span className="empty-mark" aria-hidden="true">＋</span><div><h3>参加できるルームはまだありません</h3><p className="muted">新しいルームを作って、みんなを招待しましょう。</p></div></div> : <div className="room-list">{rooms.map(room => {
        const joinable = room.status === "WAITING" && room.player_count < room.max_players;
        return <article className="room-card" key={room.room_id}>
          <div className="room-code" aria-label={`ルーム番号 ${room.room_id}`}><small>ルーム</small><strong>{room.room_id}</strong></div>
          <div className="room-detail"><span className={`status status-${room.status.toLowerCase()}`}>{room.status === "WAITING" ? "● 参加受付中" : "ゲーム進行中"}</span><h3>{room.title || room.game_name}</h3><p className="muted">{room.player_count} / {room.max_players} 人</p></div>
          <button type="button" disabled={!joinable} onClick={() => enterRoom(room.room_id)}>{joinable ? <>参加する <span aria-hidden="true">→</span></> : room.player_count >= room.max_players ? "満員" : "開始済み"}</button>
        </article>;
      })}</div>}
    </section>
    {message && <p className="error" role="alert">{message}</p>}
    <footer className="lobby-footer"><a href="/admin">管理者入口</a></footer>
  </main>
    <BottomSheet open={roomSetupOpen} onClose={() => setRoomSetupOpen(false)} labelledBy="room-setup-title" describedBy="room-setup-summary" closeLabel="キャンセル" className="room-setup-sheet" header={<><span className="step-label">新しいルーム</span><h2 id="room-setup-title">ルーム設定を選ぶ</h2><p id="room-setup-summary" className="muted">遊ぶ人数とゲームのテンポを決めてください。</p></>}>
      <form className="room-setup-form" onSubmit={createRoom}>
        <div className="room-setup-grid">
          <SetupNumberInput label="ルームの定員" hint="範囲：2〜100人（オーナーを含む）" value={roomSetup.max_players} minimum={2} maximum={100} step={1} onChange={value => editSetup("max_players", value)} onBlur={() => normalizeSetup("max_players", 2, 100, 1, defaultRoomSetup.max_players)} />
          <SetupNumberInput label="ラウンド数" hint="1ラウンドで全員が1回ずつ親になります（1〜10ラウンド）" value={roomSetup.round_count} minimum={1} maximum={10} step={1} onChange={value => editSetup("round_count", value)} onBlur={() => normalizeSetup("round_count", 1, 10, 1, defaultRoomSetup.round_count)} />
          <SetupNumberInput label="問題を選ぶ時間" hint="範囲：5〜60秒（5秒刻み、時間切れで自動選択）" value={roomSetup.selection_duration} minimum={5} maximum={60} step={5} onChange={value => editSetup("selection_duration", value)} onBlur={() => normalizeSetup("selection_duration", 5, 60, 5, defaultRoomSetup.selection_duration)} />
          <SetupNumberInput label="回答時間" hint="範囲：10〜60秒（10秒刻み）" value={roomSetup.question_duration} minimum={10} maximum={60} step={10} onChange={value => editSetup("question_duration", value)} onBlur={() => normalizeSetup("question_duration", 10, 60, 10, defaultRoomSetup.question_duration)} />
          <SetupNumberInput label="問題間の待ち時間" hint="範囲：5〜30秒（5秒刻み）" value={roomSetup.between_question_duration} minimum={5} maximum={30} step={5} onChange={value => editSetup("between_question_duration", value)} onBlur={() => normalizeSetup("between_question_duration", 5, 30, 5, defaultRoomSetup.between_question_duration)} />
        </div>
        <div className="button-row room-setup-actions"><button type="submit">この設定で作成</button></div>
      </form>
    </BottomSheet>
    {creatingRoom && <div className="room-entry-overlay" role="dialog" aria-modal="true" aria-labelledby="room-entry-title"><section className="card room-entry-progress"><span className="loading-orbit" aria-hidden="true" /><span className="step-label">ルームへご案内中</span><h2 id="room-entry-title" aria-live="polite">{roomEntryStep === "creating" ? "専用ルームを作成しています" : "オーナーとして入室しています"}</h2><ol><li className="done">本人情報を確認</li><li className={roomEntryStep === "creating" ? "active" : "done"}>ルームを作成</li><li className={roomEntryStep === "entering" ? "active" : ""}>オーナーとして入室</li></ol><p>このままお待ちください。操作は必要ありません。</p></section></div>}
  </>;
}
