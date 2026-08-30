"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { QRCodeSVG } from "qrcode.react";
import { BottomSheet } from "../BottomSheet";
import { apiMessage, statusLabel } from "../ja";
import { PlayerName } from "../PlayerName";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const configuredGameUrl = process.env.NEXT_PUBLIC_GAME_URL?.trim().replace(/\/$/, "");
const adminTokenKey = "party-quiz-admin-token";
type Section = "overview" | "rooms" | "questions" | "settings" | "users";
type Strategy = "majority" | "minority" | "fixed";
type Settings = { game_name: string; question_duration: number; result_duration: number; countdown_duration: number; max_players: number };
type SettingsDraft = Omit<Settings, "question_duration" | "result_duration" | "countdown_duration" | "max_players"> & {
  question_duration: number | "";
  result_duration: number | "";
  countdown_duration: number | "";
  max_players: number | "";
};
type Question = { id: string; title: string; option_a: string; option_b: string; score_strategy: Strategy; score_config: Record<string, number | string>; order: number };
type Player = { id: string; username: string; ready: boolean; connected: boolean; score: number };
type Room = { room_id: string; status: string; owner_id: string | null; players: Player[]; settings: Settings; current_question_index: number; question_count: number; answered: number; phase_started_at?: string; phase_duration?: number; paused_status?: string; question?: { title: string; option_a: string; option_b: string }; result?: { counts: { A: number; B: number } } };
type RecentGame = { id: string; room_id: string; game_name: string; finished_at: string; player_count: number; rank: number; score: number };
type User = { id: string; username: string; avatar_url: string; created_at: string | null; last_active_at: string | null; stats: { games: number; wins: number; best_rank: number | null; average_rank: number | null }; recent_games: RecentGame[] };
const nav: { section: Section; href: string; label: string }[] = [
  { section: "overview", href: "/admin", label: "概要" }, { section: "rooms", href: "/admin/rooms", label: "ルーム管理" }, { section: "users", href: "/admin/users", label: "プレイヤー名簿" }, { section: "questions", href: "/admin/questions", label: "質問管理" }, { section: "settings", href: "/admin/settings", label: "ゲーム設定" },
];
const blankQuestion = (): Omit<Question, "id" | "order"> => ({ title: "", option_a: "", option_b: "", score_strategy: "majority", score_config: { winner_score: 1, loser_score: 0 } });

function secondsRemaining(startedAt?: string, duration?: number): number {
  if (!startedAt || duration === undefined) return 0;
  return Math.max(0, Math.ceil((new Date(startedAt).getTime() + duration * 1000 - Date.now()) / 1000));
}

function isLocalUrl(value: string): boolean {
  try { return ["localhost", "127.0.0.1", "::1"].includes(new URL(value).hostname); }
  catch { return false; }
}

function activityLabel(value: string | null): string {
  if (!value) return "まだプレイしていません";
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "たった今";
  if (minutes < 60) return `${minutes}分前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}時間前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}日前`;
  return new Intl.DateTimeFormat("ja-JP", { month: "short", day: "numeric" }).format(new Date(value));
}

function gameDate(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function AdminDashboard({ section }: { section: Section }) {
  const [token, setToken] = useState<string | null>(null); const [password, setPassword] = useState(""); const [message, setMessage] = useState(""); const [saving, setSaving] = useState(false);
  const [rooms, setRooms] = useState<Room[]>([]); const [selectedRoom, setSelectedRoom] = useState<Room | null>(null); const [roomDraft, setRoomDraft] = useState({ game_name: "", max_players: 12 });
  const [users, setUsers] = useState<User[]>([]); const [editingUser, setEditingUser] = useState<User | null>(null); const [userName, setUserName] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]); const [draft, setDraft] = useState<Omit<Question, "id" | "order">>(blankQuestion()); const [editingQuestion, setEditingQuestion] = useState<Question | null>(null); const [questionEditorOpen, setQuestionEditorOpen] = useState(false);
  const [settings, setSettings] = useState<SettingsDraft | null>(null); const [clock, setClock] = useState(0); const [gameUrl, setGameUrl] = useState("");

  async function request(path: string, init: RequestInit = {}) {
    const response = await fetch(`${api}${path}`, { ...init, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(init.headers || {}) } });
    const data = await response.json().catch(() => null);
    if (response.status === 401) { sessionStorage.removeItem(adminTokenKey); setToken(""); throw new Error("管理者セッションの有効期限が切れました。もう一度ログインしてください。"); }
    if (!response.ok) throw new Error(apiMessage(data?.detail, "操作に失敗しました。"));
    return data;
  }
  async function loadRooms() {
    const loaded: Room[] = await request("/api/admin/rooms");
    setRooms(loaded); setSelectedRoom(current => current ? loaded.find(room => room.room_id === current.room_id) || null : null);
  }
  async function load() {
    try {
      if (section === "rooms") await loadRooms();
      if (section === "users") setUsers(await request("/api/admin/users"));
      if (section === "questions") setQuestions(await request("/api/admin/questions"));
      if (section === "settings") setSettings(await request("/api/admin/game"));
      if (section === "overview") { const [loadedRooms, loadedUsers, loadedQuestions] = await Promise.all([request("/api/admin/rooms"), request("/api/admin/users"), request("/api/admin/questions")]); setRooms(loadedRooms); setUsers(loadedUsers); setQuestions(loadedQuestions); }
    } catch (error) { setMessage(error instanceof Error ? error.message : "読み込みに失敗しました。"); }
  }
  useEffect(() => {
    const currentUrl = new URL(window.location.href);
    if (currentUrl.searchParams.has("password")) {
      currentUrl.searchParams.delete("password");
      window.history.replaceState(window.history.state, "", `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`);
    }
    setToken(sessionStorage.getItem(adminTokenKey) || "");
    try { setGameUrl(new URL(configuredGameUrl || "/", window.location.origin).toString().replace(/\/$/, "")); }
    catch { setGameUrl(window.location.origin); }
  }, []);
  useEffect(() => { if (token) void load(); }, [token, section]);
  useEffect(() => { if (!token || section !== "rooms") return; const timer = window.setInterval(() => void loadRooms().catch(() => undefined), 1500); return () => window.clearInterval(timer); }, [token, section]);
  useEffect(() => { if (section !== "rooms") return; const timer = window.setInterval(() => setClock(value => value + 1), 500); return () => window.clearInterval(timer); }, [section]);

  async function login(event: FormEvent) { event.preventDefault(); try { const response = await fetch(`${api}/api/admin/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) }); const data = await response.json(); if (!response.ok) throw new Error("ログインできませんでした。"); sessionStorage.setItem(adminTokenKey, data.token); setPassword(""); setToken(data.token); setMessage(""); } catch (error) { setMessage(error instanceof Error ? error.message : "ログインできませんでした。"); } }
  function logout() { sessionStorage.removeItem(adminTokenKey); setToken(""); setMessage(""); }
  function chooseRoom(room: Room) { setSelectedRoom(room); setRoomDraft({ game_name: room.settings.game_name, max_players: room.settings.max_players }); }
  async function createRoom() { try { const room: Room = await request("/api/admin/rooms", { method: "POST" }); setRooms(current => [...current, room]); chooseRoom(room); setMessage("ルームを作成しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "作成に失敗しました。"); } }
  async function saveRoom(event: FormEvent) { event.preventDefault(); if (!selectedRoom) return; setSaving(true); try { const updated: Room = await request(`/api/admin/rooms/${selectedRoom.room_id}`, { method: "PUT", body: JSON.stringify(roomDraft) }); chooseRoom(updated); await loadRooms(); setMessage("ルーム設定を保存しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "保存に失敗しました。"); } finally { setSaving(false); } }
  async function deleteRoom() { if (!selectedRoom || !window.confirm(`ルーム ${selectedRoom.room_id} を削除しますか？`)) return; try { await request(`/api/admin/rooms/${selectedRoom.room_id}`, { method: "DELETE" }); setSelectedRoom(null); await loadRooms(); setMessage("ルームを削除しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "削除に失敗しました。"); } }

  const readyPlayers = selectedRoom?.players.filter(player => player.id !== selectedRoom.owner_id) || [];
  const readyCount = readyPlayers.filter(player => player.ready).length;
  const everyoneReady = Boolean(readyPlayers.length && readyCount === readyPlayers.length);
  async function action(action: "start" | "lock" | "next" | "pause" | "resume" | "reset" | "end") {
    if (!selectedRoom) return;
    if (action === "start" && !everyoneReady) { setMessage("全員が準備完了になるまで開始できません。"); return; }
    if (["reset", "end"].includes(action) && !window.confirm(action === "reset" ? "リセットすると、スコア・回答履歴・準備状況が消去されます。続けますか？" : "ゲームを途中で終了しますか？")) return;
    try { await request(`/api/admin/rooms/${selectedRoom.room_id}/${action}`, { method: "POST" }); await loadRooms(); setMessage(action === "pause" ? "ゲームを一時停止しました。" : action === "resume" ? "ゲームを再開しました。" : "操作が完了しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "操作に失敗しました。"); }
  }
  async function saveUser(event: FormEvent) { event.preventDefault(); if (!editingUser) return; setSaving(true); try { const updated: User = await request(`/api/admin/users/${editingUser.id}`, { method: "PUT", body: JSON.stringify({ username: userName }) }); setUsers(current => current.map(user => user.id === updated.id ? updated : user)); setEditingUser(null); setMessage("ニックネームを更新しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "保存に失敗しました。"); } finally { setSaving(false); } }
  async function deleteUser(user: User) { if (!window.confirm(`ユーザー「${user.username}様」を削除しますか？`)) return; try { await request(`/api/admin/users/${user.id}`, { method: "DELETE" }); setUsers(current => current.filter(item => item.id !== user.id)); setMessage("ユーザーとアバターを削除しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "削除に失敗しました。"); } }
  function openQuestionCreator() { setMessage(""); setEditingQuestion(null); setDraft(blankQuestion()); setQuestionEditorOpen(true); }
  function openQuestionEditor(question: Question) { setMessage(""); setEditingQuestion(question); setDraft({ title: question.title, option_a: question.option_a, option_b: question.option_b, score_strategy: question.score_strategy, score_config: { ...question.score_config } }); setQuestionEditorOpen(true); }
  function closeQuestionEditor() { if (saving) return; setQuestionEditorOpen(false); setEditingQuestion(null); setDraft(blankQuestion()); }
  async function saveQuestion(event: FormEvent) { event.preventDefault(); setSaving(true); try { if (editingQuestion) await request(`/api/admin/questions/${editingQuestion.id}`, { method: "PUT", body: JSON.stringify({ ...draft, id: editingQuestion.id, order: editingQuestion.order }) }); else await request("/api/admin/questions", { method: "POST", body: JSON.stringify(draft) }); const savedAsEdit = Boolean(editingQuestion); setQuestionEditorOpen(false); setDraft(blankQuestion()); setEditingQuestion(null); await load(); setMessage(savedAsEdit ? "質問を更新しました。" : "質問を追加しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "保存に失敗しました。"); } finally { setSaving(false); } }
  async function removeQuestion(question: Question) { if (!window.confirm(`質問「${question.title}」を削除しますか？`)) return; try { await request(`/api/admin/questions/${question.id}`, { method: "DELETE" }); await load(); setMessage("質問を削除しました。"); } catch (error) { setMessage(error instanceof Error ? error.message : "削除に失敗しました。"); } }
  async function saveSettings(event: FormEvent) { event.preventDefault(); if (!settings) return; setSaving(true); try { setSettings(await request("/api/admin/game", { method: "PUT", body: JSON.stringify(settings) })); setMessage("デフォルト設定を保存しました。新しく作成するルームにのみ適用されます。"); } catch (error) { setMessage(error instanceof Error ? error.message : "保存に失敗しました。"); } finally { setSaving(false); } }

  async function copyGameUrl() {
    try { await navigator.clipboard.writeText(gameUrl); setMessage("ゲームトップのURLをコピーしました。"); }
    catch { setMessage("URLをコピーできませんでした。リンクを長押ししてコピーしてください。"); }
  }
  async function shareGameUrl() {
    if (!navigator.share) { await copyGameUrl(); return; }
    try { await navigator.share({ title: "マジョリティ", text: "ゲームはこちらから参加できます。", url: gameUrl }); }
    catch (error) { if (error instanceof DOMException && error.name === "AbortError") return; setMessage("共有できませんでした。URLをコピーして送ってください。"); }
  }

  const roomUrl = selectedRoom ? `${typeof window !== "undefined" ? window.location.origin : ""}/room/${selectedRoom.room_id}` : "";
  const gameUrlIsLocal = isLocalUrl(gameUrl);
  const editable = selectedRoom?.status === "WAITING";
  const remaining = useMemo(() => selectedRoom?.status === "PAUSED" ? Math.ceil(selectedRoom.phase_duration || 0) : secondsRemaining(selectedRoom?.phase_started_at, selectedRoom?.phase_duration), [selectedRoom, clock]);
  if (token === null) return <main id="main-content" className="admin-page" aria-busy="true" aria-label="管理画面を読み込んでいます。" />;
  if (!token) return <main id="main-content" className="admin-login">
    <header className="page-heading"><div><span className="eyebrow">ゲーム管理</span><h1>管理コンソール</h1></div><a className="secondary admin-button" href="/">ロビーに戻る</a></header>
    <section className="card identity-card"><span className="step-label">管理者専用</span><h2>管理者パスワードを確認</h2><form method="post" onSubmit={login}><label htmlFor="admin-password">管理者パスワード</label><input id="admin-password" name="password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /><button type="submit" className="wide">管理画面へ進む <span aria-hidden="true">→</span></button></form>{message && <p className="error" role="alert">{message}</p>}</section>
  </main>;

  return <main id="main-content" className="admin-page"><header className="admin-header"><div><span className="eyebrow">ゲーム管理</span><h1>管理コンソール</h1><p className="muted">ルーム、質問、ゲーム進行を管理します。</p></div><div className="button-row"><button type="button" className="secondary" onClick={logout}>ログアウト</button><a className="secondary admin-button" href="/">ロビーに戻る</a></div></header><nav className="admin-nav" aria-label="管理画面ナビゲーション">{nav.map(item => <Link key={item.section} href={item.href} className={section === item.section ? "active" : ""} aria-current={section === item.section ? "page" : undefined}>{item.label}</Link>)}</nav>{message && !(section === "questions" && questionEditorOpen) && <p className="notice" role="status" aria-live="polite">{message}</p>}
    {section === "overview" && <><section className="card share-game-card"><div className="share-game-copy"><span className="step-label">iPhoneカメラ対応</span><h2>ゲームトップをシェア</h2><p className="muted">このQRコードをカメラで読み取ると、ゲームのトップページが開きます。表示中のドメインから自動生成しています。</p>{gameUrl && <><a className="share-game-url" href={gameUrl}>{gameUrl}</a><div className="button-row"><button type="button" onClick={() => void shareGameUrl()}>共有する</button><button type="button" className="secondary" onClick={() => void copyGameUrl()}>URLをコピー</button></div></>}{gameUrlIsLocal && <p className="local-url-warning" role="alert"><strong>このURLはスマートフォンから開けません。</strong> 公開URLで管理画面を開くか、<code>NEXT_PUBLIC_GAME_URL</code> にスマートフォンから届くURLを設定してください。</p>}</div>{gameUrl && <div className="homepage-qr" aria-label="ゲームトップのQRコード"><QRCodeSVG value={gameUrl} size={208} level="M" marginSize={2} title="ゲームトップを開くQRコード" /></div>}</section><section className="card"><h2>現在のデータ</h2><div className="stats"><span><strong>{rooms.length}</strong> ルーム</span><span><strong>{users.length}</strong> ユーザー</span><span><strong>{questions.length}</strong> 問</span></div></section><section className="card overview-grid">{nav.filter(item => item.section !== "overview").map(item => <Link className="overview-link" key={item.section} href={item.href}>{item.label}</Link>)}</section></>}
    {section === "rooms" && <>
      <section className="card">
        <div className="row"><div><h2>ルーム一覧</h2><p className="muted">1.5秒ごとに自動更新</p></div><div className="button-row"><button className="secondary" onClick={() => void loadRooms()}>更新</button><button onClick={createRoom}>ルームを作る</button></div></div>
        <div className="room-list">{rooms.map(room => <article className={`room-card admin-room ${selectedRoom?.room_id === room.room_id ? "selected" : ""}`} key={room.room_id}><div><span className={`status status-${room.status.toLowerCase()}`}>{statusLabel(room.status)}</span><h3>{room.settings.game_name}</h3><p className="muted">{room.room_id} · {room.players.length}/{room.settings.max_players} 人 · 準備完了 {room.players.filter(player => player.ready).length} 人</p></div><button className="secondary" onClick={() => chooseRoom(room)}>管理</button></article>)}</div>
      </section>
      {selectedRoom && <BottomSheet open onClose={() => setSelectedRoom(null)} labelledBy="room-sheet-title" describedBy="room-sheet-summary" className="admin-room-sheet" header={<><span className={`status status-${selectedRoom.status.toLowerCase()}`}>{statusLabel(selectedRoom.status)}</span><h2 id="room-sheet-title">ルーム {selectedRoom.room_id}</h2><p id="room-sheet-summary" className="muted">第 {Math.min(selectedRoom.current_question_index + 1, selectedRoom.question_count)} / {selectedRoom.question_count} 問</p></>}>
            <div className="control-stats"><span><strong>{readyCount}/{selectedRoom.players.length}</strong> 準備完了</span><span><strong>{selectedRoom.answered}/{selectedRoom.players.length}</strong> 回答済み</span><span><strong>{remaining || "—"}</strong> 秒</span></div>
            {selectedRoom.question && <div className="inset-form"><strong>{selectedRoom.question.title}</strong><p className="muted">A：{selectedRoom.question.option_a}　B：{selectedRoom.question.option_b}</p>{selectedRoom.result && <p>A {selectedRoom.result.counts.A} · B {selectedRoom.result.counts.B}</p>}</div>}
            {roomUrl && <div className="qr"><QRCodeSVG value={roomUrl} size={160} /><a href={roomUrl}>{roomUrl}</a></div>}
            {editable && <form className="editor-form" onSubmit={saveRoom}><div className="form-grid"><label>ルーム名<input value={roomDraft.game_name} onChange={event => setRoomDraft({ ...roomDraft, game_name: event.target.value })} required /></label><label>定員<input type="number" min={selectedRoom.players.length} max="100" value={roomDraft.max_players} onChange={event => setRoomDraft({ ...roomDraft, max_players: Number(event.target.value) })} required /></label></div><button disabled={saving}>ルーム設定を保存</button></form>}
            <div className="button-row control-actions"><button onClick={() => void action("start")} disabled={!editable || !everyoneReady}>ゲーム開始 {!everyoneReady && editable ? `(${readyCount}/${selectedRoom.players.length})` : ""}</button><button onClick={() => void action("pause")} disabled={!(["COUNTDOWN", "QUESTION", "SHOW_RESULT"].includes(selectedRoom.status))}>一時停止</button><button onClick={() => void action("resume")} disabled={selectedRoom.status !== "PAUSED"}>再開</button><button onClick={() => void action("lock")} disabled={selectedRoom.status !== "QUESTION"}>締め切って採点</button><button onClick={() => void action("next")} disabled={selectedRoom.status !== "SHOW_RESULT"}>次の問題</button><button className="secondary" onClick={() => void action("reset")} disabled={selectedRoom.status === "WAITING"}>ゲームをリセット</button><button className="danger" onClick={() => void action("end")} disabled={["WAITING", "FINISHED"].includes(selectedRoom.status)}>途中で終了</button></div>
            <div className="control-players">{selectedRoom.players.map(player => <span key={player.id} className={!player.connected ? "offline" : player.ready ? "ready" : "not-ready"}>{player.connected ? "●" : "○"} <PlayerName name={player.username} /> · {player.score} ポイント</span>)}</div>
            {editable && <div className="room-sheet-danger"><button className="danger" onClick={deleteRoom}>ルームを削除</button></div>}
      </BottomSheet>}
    </>}
    {section === "users" && <section className="card player-directory"><div className="section-heading player-directory-heading"><div><span className="step-label">プレイヤー名簿</span><h2>参加したみんな</h2><p className="muted">最後のアクセスが新しい順に、プロフィールと戦績を表示します。</p></div><button type="button" className="secondary" onClick={() => void load()}>更新</button></div>{editingUser && <form className="editor-form inset-form" onSubmit={saveUser}><label htmlFor="edit-username">ニックネーム</label><input id="edit-username" name="username" autoComplete="off" spellCheck={false} value={userName} onChange={event => setUserName(event.target.value)} required maxLength={30} /><div className="button-row"><button disabled={saving}>{saving ? "保存中…" : "ニックネームを保存"}</button><button type="button" className="secondary" onClick={() => setEditingUser(null)}>キャンセル</button></div></form>}{users.length === 0 ? <div className="empty"><span className="empty-mark" aria-hidden="true">人</span><div><h3>プレイヤーはまだいません</h3><p className="muted">誰かがゲームに参加すると、ここにプロフィールが追加されます。</p></div></div> : <div className="player-record-list">{users.map(user => <article className="player-record" key={user.id}><div className="player-record-main"><img className="player-record-avatar" width="58" height="58" loading="lazy" src={`${api}${user.avatar_url}`} alt="" /><div className="player-record-identity"><h3><PlayerName name={user.username} /></h3><span className="player-activity"><i aria-hidden="true" />最終アクセス {activityLabel(user.last_active_at)}</span><code title={user.id}>ID {user.id.slice(0, 8)}</code></div><div className="player-record-stats" aria-label={`${user.username}の戦績`}><span><strong>{user.stats.games}</strong>局</span><span><strong>{user.stats.wins}</strong>勝</span><span><strong>{user.stats.best_rank ? `${user.stats.best_rank}位` : "—"}</strong>最高</span><span><strong>{user.stats.average_rank ?? "—"}</strong>平均順位</span></div><div className="button-row player-record-actions"><button type="button" className="secondary" onClick={() => { setEditingUser(user); setUserName(user.username); }}>編集</button><button type="button" className="danger" onClick={() => void deleteUser(user)}>削除</button></div></div>{user.recent_games.length > 0 && <details className="player-recent-games"><summary>最近の戦績 <span>{user.recent_games.length}件</span></summary><div>{user.recent_games.map(game => <article key={game.id}><span className={`player-game-rank ${game.rank === 1 ? "is-win" : ""}`}><strong>{game.rank}</strong>位</span><div><strong>{game.game_name}</strong><small>{gameDate(game.finished_at)} · {game.player_count}人</small></div><span className="player-game-score">{game.score}<small> pt</small></span></article>)}</div></details>}</article>)}</div>}</section>}
    {section === "questions" && <>
      <section className="card question-library">
        <div className="section-heading question-library-heading">
          <div><span className="step-label">質問ライブラリ</span><h2>登録済みの質問</h2><p className="muted">{questions.length}問の質問をゲームで使用できます。</p></div>
          <button type="button" className="question-create-button" onClick={openQuestionCreator}><span aria-hidden="true">＋</span> 新しい質問</button>
        </div>
        {questions.length === 0 ? <div className="empty"><span className="empty-mark" aria-hidden="true">？</span><div><h3>質問はまだありません</h3><p className="muted">最初の質問を追加してゲームを始めましょう。</p></div></div> : <div className="question-list">{questions.map(question => <article className="question-row" key={question.id}>
          <span className="question-order" aria-label={`${question.order}問目`}>{String(question.order).padStart(2, "0")}</span>
          <div className="question-row-copy"><h3>{question.title}</h3><div className="question-options"><span><b>A</b>{question.option_a}</span><span><b>B</b>{question.option_b}</span></div></div>
          <div className="question-row-actions"><button type="button" className="secondary question-edit-button" aria-label={`質問「${question.title}」を編集`} title="編集" onClick={() => openQuestionEditor(question)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11-4-4L4 16v4Zm10-13 4 4M13 6l4 4" /></svg></button><button type="button" className="danger question-delete-button" onClick={() => void removeQuestion(question)}>削除</button></div>
        </article>)}</div>}
      </section>
      <BottomSheet open={questionEditorOpen} onClose={closeQuestionEditor} labelledBy="question-editor-title" describedBy="question-editor-summary" closeLabel="キャンセル" className="question-editor-sheet" header={<><span className="step-label">{editingQuestion ? `質問 ${String(editingQuestion.order).padStart(2, "0")}` : "新しい質問"}</span><h2 id="question-editor-title">{editingQuestion ? "質問を編集" : "質問を作成"}</h2><p id="question-editor-summary" className="muted">質問文、二つの選択肢、採点ルールを設定します。</p></>}>
        <form className="editor-form question-editor-form" onSubmit={saveQuestion}>
          <label htmlFor="question-title">質問文<input id="question-title" value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} required /></label>
          <div className="form-grid"><label htmlFor="question-option-a">選択肢 A<input id="question-option-a" value={draft.option_a} onChange={event => setDraft({ ...draft, option_a: event.target.value })} required /></label><label htmlFor="question-option-b">選択肢 B<input id="question-option-b" value={draft.option_b} onChange={event => setDraft({ ...draft, option_b: event.target.value })} required /></label></div>
          <label htmlFor="question-strategy">採点ルール<select id="question-strategy" value={draft.score_strategy} onChange={event => { const score_strategy = event.target.value as Strategy; setDraft({ ...draft, score_strategy, score_config: score_strategy === "fixed" ? { correct_answer: "A", correct_score: 1, wrong_score: 0 } : { winner_score: 1, loser_score: 0 } }); }}><option value="majority">多数派に得点</option><option value="minority">少数派に得点</option><option value="fixed">正解を固定</option></select></label>
          {draft.score_strategy === "fixed" ? <div className="form-grid"><label>正解<select value={String(draft.score_config.correct_answer)} onChange={event => setDraft({ ...draft, score_config: { ...draft.score_config, correct_answer: event.target.value } })}><option value="A">A</option><option value="B">B</option></select></label><label>正解時の得点<input type="number" value={Number(draft.score_config.correct_score)} onChange={event => setDraft({ ...draft, score_config: { ...draft.score_config, correct_score: Number(event.target.value) } })} /></label><label>不正解時の得点<input type="number" value={Number(draft.score_config.wrong_score)} onChange={event => setDraft({ ...draft, score_config: { ...draft.score_config, wrong_score: Number(event.target.value) } })} /></label></div> : <div className="form-grid"><label>勝った側の得点<input type="number" value={Number(draft.score_config.winner_score)} onChange={event => setDraft({ ...draft, score_config: { ...draft.score_config, winner_score: Number(event.target.value) } })} /></label><label>それ以外の得点<input type="number" value={Number(draft.score_config.loser_score)} onChange={event => setDraft({ ...draft, score_config: { ...draft.score_config, loser_score: Number(event.target.value) } })} /></label></div>}
          <button className="wide" disabled={saving}>{saving ? "保存しています…" : editingQuestion ? "変更を保存" : "質問を作成"}</button>
          {message && <p className="error" role="alert">{message}</p>}
        </form>
      </BottomSheet>
    </>}
    {section === "settings" && settings && <section className="card"><h2>デフォルトのゲーム設定</h2><p className="muted">これから新しく作成するルームにのみ適用されます。</p><form className="editor-form" onSubmit={saveSettings}><label>ゲーム名<input value={settings.game_name} onChange={event => setSettings({ ...settings, game_name: event.target.value })} required /></label><div className="form-grid"><label>最大参加人数<input type="number" min="2" max="100" value={settings.max_players} onChange={event => setSettings({ ...settings, max_players: event.target.value === "" ? "" : Number(event.target.value) })} required /></label><label>1問の制限時間（秒）<input type="number" min="5" max="120" value={settings.question_duration} onChange={event => setSettings({ ...settings, question_duration: event.target.value === "" ? "" : Number(event.target.value) })} required /></label><label>結果の表示時間（秒）<input type="number" min="1" max="60" value={settings.result_duration} onChange={event => setSettings({ ...settings, result_duration: event.target.value === "" ? "" : Number(event.target.value) })} required /></label><label>開始前カウントダウン（秒）<input type="number" min="0" max="10" value={settings.countdown_duration} onChange={event => setSettings({ ...settings, countdown_duration: event.target.value === "" ? "" : Number(event.target.value) })} required /></label></div><button disabled={saving}>デフォルト設定を保存</button></form></section>}
  </main>;
}
