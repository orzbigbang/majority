"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { BottomSheet } from "../../BottomSheet";
import { apiMessage } from "../../ja";
import { PlayerName } from "../../PlayerName";
import { useRoomExitRedirect } from "../../useRoomExit";
import { ReactionAvatarButton, RoomReactionSurface, useRoomReactions } from "../../RoomReactions";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const wsBase = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const configuredGameUrl = process.env.NEXT_PUBLIC_GAME_URL?.trim().replace(/\/$/, "");
const identityKey = "party-quiz-player";
const avatarStyleVersion = process.env.NEXT_PUBLIC_AVATAR_STYLE_VERSION || "cute-animal-v1";

type Identity = { player_id: string; username: string; session_id?: string };
type BoardEntry = { rank: number; id: string; username: string; score: number };
type QuestionSummary = { id: string; title: string; option_a: string; option_b: string };
type AnswerReview = { player_id: string; username: string; choice: "A" | "B" | null };
type Result = { question_id: string; question: QuestionSummary; counts: { A: number; B: number }; answers: AnswerReview[]; scores: Record<string, number>; leaderboard: BoardEntry[] };
type Review = { question: QuestionSummary; counts: { A: number; B: number }; answers: AnswerReview[] };
type PreviousGame = { leaderboard: BoardEntry[]; review: Review[] };
type RoomSettingsDraft = { max_players: string; question_count: string; question_duration: string; between_question_duration: string };
type RoomClock = { revision: number; phase: State["status"]; server_time: string; running: boolean; started_at: string | null; ends_at: string | null; duration_ms: number | null; remaining_ms: number };
type State = {
  status: "WAITING" | "COUNTDOWN" | "QUESTION" | "PAUSED" | "LOCK" | "SHOW_RESULT" | "FINISHED";
  owner_id: string | null;
  players: { id: string; username: string; score: number; ready: boolean; connected: boolean }[];
  current_question_index: number;
  question_count: number;
  answered: number;
  settings: { game_name: string; max_players: number; question_duration: number; result_duration: number };
  phase_started_at?: string;
  phase_duration?: number;
  clock: RoomClock;
  paused_status?: string;
  result?: Result | null;
  review?: Review[];
  previous_game?: PreviousGame | null;
  question?: { id: string; title: string; option_a: string; option_b: string };
};

function clockSecondsRemaining(clock: RoomClock | undefined, currentTime: number): number {
  if (!clock) return 0;
  if (!clock.running || !clock.ends_at) return Math.max(0, Math.ceil(clock.remaining_ms / 1000));
  return Math.max(0, Math.ceil((new Date(clock.ends_at).getTime() - currentTime) / 1000));
}

function avatarUrl(playerId: string): string {
  return `${api}/api/players/${playerId}/avatar?v=${encodeURIComponent(avatarStyleVersion)}`;
}

export default function RoomPage({ params }: { params: Promise<{ roomId: string }> }) {
  const router = useRouter();
  const { exitRoom, exitForJoinError } = useRoomExitRedirect();
  const [roomId, setRoomId] = useState("");
  const [state, setState] = useState<State | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [selectedChoice, setSelectedChoice] = useState<"A" | "B" | null>(null);
  const [confirmedChoice, setConfirmedChoice] = useState<"A" | "B" | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [pendingOwnerId, setPendingOwnerId] = useState<string | null>(null);
  const [roomShareOpen, setRoomShareOpen] = useState(false);
  const [roomUrl, setRoomUrl] = useState("");
  const [shareMessage, setShareMessage] = useState("");
  const [roomSettingsOpen, setRoomSettingsOpen] = useState(false);
  const [savingRoomSettings, setSavingRoomSettings] = useState(false);
  const [availableQuestionCount, setAvailableQuestionCount] = useState(30);
  const [roomSettingsDraft, setRoomSettingsDraft] = useState<RoomSettingsDraft>({ max_players: "12", question_count: "3", question_duration: "20", between_question_duration: "5" });
  const [showPreviousGame, setShowPreviousGame] = useState(false);
  const [currentTime, setCurrentTime] = useState(Date.now());
  const [serverClockOffsetMs, setServerClockOffsetMs] = useState(0);
  const selectionQuestionId = useRef<string | null>(null);
  const clockSynchronized = useRef(false);
  const clockSyncSamples = useRef<{ rtt: number; offset: number }[]>([]);
  const latestClockRevision = useRef(-1);
  const reactions = useRoomReactions({
    ws,
    identity,
    status: state?.status,
    scopeId: state?.status === "WAITING" ? "waiting" : result?.question_id,
    onError: setMessage,
  });

  useEffect(() => { params.then(value => setRoomId(value.roomId.toUpperCase())); }, [params]);
  useEffect(() => {
    if (!roomId) return;
    try {
      const gameUrl = new URL(configuredGameUrl || "/", window.location.origin).toString().replace(/\/$/, "");
      setRoomUrl(`${gameUrl}/room/${encodeURIComponent(roomId)}`);
    } catch {
      setRoomUrl(`${window.location.origin}/room/${encodeURIComponent(roomId)}`);
    }
  }, [roomId]);
  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!roomId) return;
    try {
      const saved = JSON.parse(localStorage.getItem(identityKey) || "null");
      if (saved?.player_id) setIdentity(saved);
      else router.replace(`/?room=${roomId}`);
    } catch { router.replace(`/?room=${roomId}`); }
  }, [roomId, router]);
  useEffect(() => {
    const questionId = state?.question?.id || null;
    if (selectionQuestionId.current === questionId) return;
    selectionQuestionId.current = questionId;
    setSelectedChoice(null); setConfirmedChoice(null); setIsConfirming(false);
  }, [state?.question?.id]);
  useEffect(() => {
    if (!roomId || !identity) return;
    const player = identity;
    let active = true;
    let socket: WebSocket | null = null;
    let sessionId = player.session_id;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let connecting = false;
    let clockSyncTimer: number | null = null;

    function syncClock(target: WebSocket) {
      if (target.readyState === WebSocket.OPEN) target.send(JSON.stringify({ type: "time_sync", payload: { client_sent_at: Date.now(), client_monotonic: performance.now() } }));
    }

    function useSnapshotClock(serverTime?: string) {
      if (!serverTime || clockSynchronized.current) return;
      const parsed = new Date(serverTime).getTime();
      if (Number.isFinite(parsed)) setServerClockOffsetMs(parsed - Date.now());
    }

    function scheduleReconnect() {
      if (!active || reconnectTimer !== null) return;
      setWs(null);
      setMessage("接続が一時的に切れました。再接続しています…");
      const delay = Math.min(30_000, 1_000 * (2 ** Math.min(reconnectAttempt, 5)));
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    }

    async function connect() {
      if (!active || connecting) return;
      connecting = true;
      try {
      const response = await fetch(`${api}/api/rooms/${roomId}/join`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: player.username, player_id: player.player_id, session_id: sessionId || undefined }),
      });
      const data = await response.json();
      if (!response.ok) {
        if (exitForJoinError(data.detail, response.status, roomId)) {
          active = false;
          return;
        }
        throw new Error(apiMessage(data.detail, "ルームに参加できませんでした。"));
      }
      if (!active) return;
      sessionId = data.session_id;
      try {
        const stored = JSON.parse(localStorage.getItem(identityKey) || "{}");
        localStorage.setItem(identityKey, JSON.stringify({ ...stored, player_id: data.player_id, session_id: data.session_id }));
      } catch { /* The player ID still provides a safe recovery path. */ }
      selectionQuestionId.current = data.room.question?.id || null;
      setSelectedChoice(data.draft_choice || null);
      setConfirmedChoice(data.confirmed_choice || null);
      useSnapshotClock(data.room.clock?.server_time);
      latestClockRevision.current = data.room.clock?.revision ?? -1;
      setState(data.room);
      setResult(data.room.result || null);
      setShowPreviousGame(data.room.status === "FINISHED");
      const query = new URLSearchParams({ player_id: data.player_id, session_id: data.session_id });
      socket = new WebSocket(`${wsBase}/ws/rooms/${roomId}?${query.toString()}`);
      socket.onopen = () => {
        reconnectAttempt = 0;
        clockSynchronized.current = false;
        clockSyncSamples.current = [];
        setWs(socket);
        setMessage("");
        syncClock(socket!);
        clockSyncTimer = window.setInterval(() => syncClock(socket!), 10_000);
      };
      socket.onmessage = event => {
        const item = JSON.parse(event.data);
        if (item.type === "game_state") {
          useSnapshotClock(item.payload.clock?.server_time);
          const incomingRevision = Number(item.payload.clock?.revision ?? -1);
          if (incomingRevision < latestClockRevision.current) return;
          latestClockRevision.current = incomingRevision;
          setState(item.payload);
          setResult(item.payload.result || null);
          if (item.payload.status !== "WAITING" || item.payload.owner_id !== player.player_id) setRoomSettingsOpen(false);
          if (item.payload.status === "FINISHED") setShowPreviousGame(true);
        }
        if (item.type === "time_sync") {
          const sentAt = Number(item.payload?.client_sent_at);
          const sentMonotonic = Number(item.payload?.client_monotonic);
          const serverTime = new Date(item.payload?.server_time).getTime();
          const roundTripTime = performance.now() - sentMonotonic;
          if (Number.isFinite(serverTime) && Number.isFinite(roundTripTime) && roundTripTime >= 0) {
            const sample = { rtt: roundTripTime, offset: serverTime - (sentAt + roundTripTime / 2) };
            clockSyncSamples.current = [...clockSyncSamples.current.slice(-5), sample];
            const bestRecentSample = clockSyncSamples.current.reduce((best, current) => current.rtt < best.rtt ? current : best);
            clockSynchronized.current = true;
            setServerClockOffsetMs(bestRecentSample.offset);
          }
        }
        if (item.type === "room_deleted") { active = false; exitRoom("deleted", roomId); }
        if (item.type === "answer_count") setState(current => current ? { ...current, answered: item.payload.answered } : current);
        if (item.type === "answer_saved") { setConfirmedChoice(item.payload.choice); setIsConfirming(false); }
        if (item.type === "room_settings_saved") { setSavingRoomSettings(false); setRoomSettingsOpen(false); }
        if (item.type === "result") setResult(item.payload);
        if (item.type === "emoji_reaction") reactions.receive(item.payload);
        if (item.type === "error") { setIsConfirming(false); setSavingRoomSettings(false); setMessage(apiMessage(item.payload.message, "操作を完了できませんでした。")); }
      };
      socket.onclose = event => {
        if (!active) return;
        if (clockSyncTimer !== null) window.clearInterval(clockSyncTimer);
        clockSyncTimer = null;
        if (event.code === 1008) {
          active = false;
          exitRoom("access-lost", roomId);
          return;
        }
        scheduleReconnect();
      };
      } catch {
        scheduleReconnect();
      } finally {
        connecting = false;
      }
    }
    function reconnectWhenOnline() {
      if (!active || socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
      void connect();
    }
    function syncWhenVisible() {
      if (document.visibilityState === "visible" && socket?.readyState === WebSocket.OPEN) syncClock(socket);
    }
    window.addEventListener("online", reconnectWhenOnline);
    document.addEventListener("visibilitychange", syncWhenVisible);
    void connect();
    return () => {
      active = false;
      window.removeEventListener("online", reconnectWhenOnline);
      document.removeEventListener("visibilitychange", syncWhenVisible);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (clockSyncTimer !== null) window.clearInterval(clockSyncTimer);
      socket?.close();
    };
  }, [roomId, identity, exitForJoinError, exitRoom, reactions.receive]);

  function confirmAnswer() {
    if (!state?.question || !ws || ws.readyState !== WebSocket.OPEN || !identity || !selectedChoice || selectedChoice === confirmedChoice) {
      if (!ws || ws.readyState !== WebSocket.OPEN) setMessage("再接続中です。少し待ってから回答を確定してください。");
      return;
    }
    ws.send(JSON.stringify({ type: "answer", player_id: identity.player_id, payload: { question_id: state.question.id, choice: selectedChoice } }));
    setIsConfirming(true);
  }

  function selectAnswer(choice: "A" | "B") {
    if (!state?.question || !ws || ws.readyState !== WebSocket.OPEN || !identity) {
      setMessage("再接続中のため、まだ回答を選べません。");
      return;
    }
    setSelectedChoice(choice);
    ws.send(JSON.stringify({ type: "select_answer", player_id: identity.player_id, payload: { question_id: state.question.id, choice } }));
  }

  function markReady() {
    if (!ws || ws.readyState !== WebSocket.OPEN || !identity) {
      setMessage("再接続中のため、準備状態を変更できません。");
      return;
    }
    ws.send(JSON.stringify({ type: "ready", player_id: identity.player_id, payload: { ready: !isReady } }));
  }

  function startGame() {
    if (!ws || !identity) return;
    ws.send(JSON.stringify({ type: "start" }));
  }

  function returnToRoom() {
    if (!ws || !identity) return;
    setShowPreviousGame(false);
    if (state?.status === "FINISHED") ws.send(JSON.stringify({ type: "return_to_room" }));
  }

  function confirmOwnerTransfer() {
    if (!pendingOwnerId) return;
    if (!ws || !identity) return;
    ws.send(JSON.stringify({ type: "transfer_owner", payload: { player_id: pendingOwnerId } }));
    setPendingOwnerId(null);
  }

  async function copyRoomUrl() {
    try {
      await navigator.clipboard.writeText(roomUrl);
      setShareMessage("ルームのURLをコピーしました。");
    } catch {
      setShareMessage("URLをコピーできませんでした。リンクを長押ししてコピーしてください。");
    }
  }

  async function shareRoomUrl() {
    if (!navigator.share) {
      await copyRoomUrl();
      return;
    }
    try {
      await navigator.share({ title: `マジョリティ · ルーム ${roomId}`, text: `ルーム ${roomId} に参加してください。`, url: roomUrl });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setShareMessage("共有できませんでした。URLをコピーして送ってください。");
    }
  }

  async function openRoomSettings() {
    if (!state) return;
    setPendingOwnerId(null);
    setRoomSettingsDraft({
      max_players: String(state.settings.max_players),
      question_count: String(state.question_count),
      question_duration: String(state.settings.question_duration),
      between_question_duration: String(state.settings.result_duration),
    });
    setRoomSettingsOpen(true);
    try {
      const response = await fetch(`${api}/api/room-options`);
      if (response.ok) setAvailableQuestionCount((await response.json()).available_question_count);
    } catch { /* The server validates the question count when saving. */ }
  }

  function updateRoomSettingsDraft(field: keyof RoomSettingsDraft, value: string) {
    setRoomSettingsDraft(current => ({ ...current, [field]: value.replace(/^0+(?=\d)/, "") }));
  }

  function saveRoomSettings(event: FormEvent) {
    event.preventDefault();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setMessage("再接続中です。少し待ってから設定を保存してください。");
      return;
    }
    setMessage("");
    setSavingRoomSettings(true);
    ws.send(JSON.stringify({ type: "update_room_settings", payload: {
      max_players: Number(roomSettingsDraft.max_players),
      question_count: Number(roomSettingsDraft.question_count),
      question_duration: Number(roomSettingsDraft.question_duration),
      between_question_duration: Number(roomSettingsDraft.between_question_duration),
    } }));
  }

  const board = useMemo(() => result?.leaderboard ?? [...(state?.players || [])]
    .sort((a, b) => b.score - a.score || a.username.localeCompare(b.username))
    .map((player, index) => ({ rank: index + 1, ...player })), [result, state]);
  const clockRemaining = clockSecondsRemaining(state?.clock, currentTime + serverClockOffsetMs);
  const remaining = state?.status === "COUNTDOWN" ? Math.max(0, clockRemaining - 1) : clockRemaining;
  const phaseProgress = state?.phase_duration ? Math.max(0, Math.min(100, (remaining / state.phase_duration) * 100)) : 0;
  const canConfirm = Boolean(selectedChoice && selectedChoice !== confirmedChoice && !isConfirming);
  const ownScore = identity && result ? result.scores[identity.player_id] ?? 0 : 0;
  const participants = state?.players.filter(player => player.id !== state.owner_id) || [];
  const readyCount = participants.filter(player => player.ready).length;
  const everyoneReady = participants.length > 0 && participants.every(player => player.ready);
  const isOwner = Boolean(identity && state?.owner_id === identity.player_id);
  const isReady = Boolean(identity && state?.players.find(player => player.id === identity.player_id)?.ready);
  const pendingOwner = state?.players.find(player => player.id === pendingOwnerId);
  const isLastQuestion = Boolean(state && state.current_question_index + 1 >= state.question_count);
  const viewingResults = state?.status === "FINISHED" || Boolean(showPreviousGame && state?.previous_game);
  const displayedBoard = state?.status === "FINISHED" ? board : state?.previous_game?.leaderboard || [];
  const displayedReview = state?.status === "FINISHED" ? state.review || [] : state?.previous_game?.review || [];

  if (!state) return <main id="main-content" className="loading-stage"><span className="loading-orbit" aria-hidden="true" /><h1>入室しています…</h1><p role="status">ルーム {roomId || "…"} に参加しています</p>{message && <p className="error" role="alert">{message}</p>}</main>;

  return <main id="main-content" className="game-page">
    <header className="game-header"><div><span className="eyebrow">ルーム {roomId}</span><h1>{state.settings.game_name}</h1></div><div className="game-header-actions">{state.status === "WAITING" && !viewingResults && <button type="button" className="secondary room-share-button" onClick={() => { setShareMessage(""); setRoomShareOpen(true); }} aria-haspopup="dialog"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.6 10.5 6.8-4M8.6 13.5l6.8 4" /></svg><span>ルームを共有</span></button>}{viewingResults && <div className="player-score"><small>最終スコア</small><strong>{identity ? displayedBoard.find(player => player.id === identity.player_id)?.score ?? 0 : 0}</strong></div>}</div></header>
    <div className="visually-hidden" aria-live="polite" aria-atomic="true">ゲーム状況：{viewingResults ? "ゲーム結果を表示中" : state.status === "WAITING" ? "プレイヤーの準備待ち" : state.status === "COUNTDOWN" ? (remaining === 0 ? "スタート" : "まもなく開始") : state.status === "QUESTION" ? `第${state.current_question_index + 1}問` : state.status === "PAUSED" ? "一時停止中" : state.status === "SHOW_RESULT" ? (isLastQuestion ? "最終結果を計算中" : "この問題の結果を表示中") : "集計中"}</div>

    {state.status === "WAITING" && !viewingResults && <section className="card waiting-card"><div className="section-heading"><div><span className="step-label">プレイヤー待機中</span><h2>みんなの準備を待っています</h2><p className="muted">参加者全員が準備できたら開始できます。ほかの人のアバターを押すと、リアクションを送れます。</p></div><div className="ready-meter" aria-label={`${participants.length}人中${readyCount}人が準備完了`}><strong>{readyCount}</strong><span>/ {participants.length}</span></div></div><div className="ready-list">{state.players.map(player => { const isCurrentPlayer = player.id === identity?.player_id; return <article key={player.id} className={`${player.id === state.owner_id ? "room-owner" : player.ready ? "ready" : "not-ready"}${isCurrentPlayer ? " is-you" : ""}`} aria-label={isCurrentPlayer ? `${player.username}、自分のプレイヤーカード` : undefined}><ReactionAvatarButton target={{ id: player.id, username: player.username }} surfaceId="waiting" disabled={isCurrentPlayer || !player.connected} onSelect={reactions.openPicker}><img width="38" height="38" src={avatarUrl(player.id)} alt="" /></ReactionAvatarButton><span>{player.id === state.owner_id ? "★ ルームオーナー" : player.ready ? "✓ 準備完了" : "○ 準備中"}</span><strong><PlayerName name={player.username} />{isCurrentPlayer && <i className="self-marker" aria-hidden="true" />}</strong>{isOwner && player.id !== state.owner_id && <button type="button" className="secondary transfer-owner" onClick={() => setPendingOwnerId(player.id)}>オーナーにする</button>}</article>; })}</div><div className="waiting-actions">{isOwner ? <button type="button" className="waiting-primary-action" onClick={startGame} disabled={!everyoneReady}>{participants.length === 0 ? "参加者を待っています" : everyoneReady ? "ゲームを開始！" : `準備待ち（${readyCount}/${participants.length}）`}</button> : <button type="button" className="ready-toggle waiting-primary-action" aria-pressed={isReady} onClick={markReady}>{isReady ? "✓ 準備完了" : "準備"}</button>}<div className="waiting-secondary-actions">{isOwner && <button type="button" className="secondary" onClick={() => void openRoomSettings()}>ルーム設定</button>}<a className="secondary admin-button" href="/">ロビーに戻る</a></div></div>{state.previous_game && <button type="button" className="secondary previous-game-button" onClick={() => setShowPreviousGame(true)}>前回のゲーム結果を見る</button>}</section>}

    {state.status === "COUNTDOWN" && <section className="card phase-card countdown-card"><p className="eyebrow">第1問まであと少し</p><strong className={`phase-number${remaining === 0 ? " phase-start" : ""}`} role="timer" aria-label={remaining === 0 ? "スタート" : `残り${remaining}秒`}>{remaining === 0 ? "スタート！" : remaining}</strong><p>スマホを手に、直感で選びましょう。</p></section>}

    {state.status === "PAUSED" && <section className="card phase-card paused-card"><p className="eyebrow">管理者が一時停止しました</p><strong className="phase-number" aria-hidden="true">Ⅱ</strong><p>そのままお待ちください。まもなく再開します。</p></section>}

    {state.status === "QUESTION" && state.question && <section className="card question-card" aria-labelledby="question-title">
      <div className="question-meta"><span>第 {state.current_question_index + 1} / {state.question_count} 問</span><strong className="timer" role="timer">{remaining}<small>秒</small></strong></div>
      <div className="time-track" aria-hidden="true"><i style={{ width: `${phaseProgress}%` }} /></div>
      <h2 id="question-title">{state.question.title}</h2>
      <p className="answer-count" aria-live="polite">{state.answered} / {state.players.length} 人が回答を確定</p>
      <div className="choices" role="group" aria-label="回答を選択"><button type="button" aria-pressed={selectedChoice === "A"} className={`choice a ${selectedChoice === "A" ? "selected-choice" : ""}`} onClick={() => selectAnswer("A")}><span className="choice-letter">A</span><span className="choice-copy">{state.question.option_a}</span><span className="choice-check" aria-hidden="true">✓</span></button><button type="button" aria-pressed={selectedChoice === "B"} className={`choice b ${selectedChoice === "B" ? "selected-choice" : ""}`} onClick={() => selectAnswer("B")}><span className="choice-letter">B</span><span className="choice-copy">{state.question.option_b}</span><span className="choice-check" aria-hidden="true">✓</span></button></div>
      <button type="button" className="wide confirm-answer" disabled={!canConfirm} onClick={confirmAnswer}>{isConfirming ? "回答を確定しています…" : confirmedChoice ? "選び直した回答を確定" : selectedChoice ? `${selectedChoice}で確定` : "先にAかBを選んでください"}</button>
      {confirmedChoice && <p className="notice answer-notice" role="status">{confirmedChoice}で確定しました。変更する場合は、もう一方を選んで再度確定してください。</p>}
    </section>}

    {state.status === "SHOW_RESULT" && <section className="card result-card stage-card">
      <div className="row"><div><span className="step-label">{isLastQuestion ? "最終問題" : `第 ${state.current_question_index + 1} 問`}</span><h2>{isLastQuestion ? "最終結果を計算しています" : "この問題の結果"}</h2></div><strong className="timer" role="timer">{isLastQuestion ? `集計完了まであと ${remaining} 秒` : `次の問題まであと ${remaining} 秒`}</strong></div>
      {result ? <><div className="result-reaction-heading"><h3 className="result-answer-heading">みんなの選択</h3><span>アバターを押してリアクション</span></div><div className="result-choice-groups">{(["A", "B"] as const).map(choice => { const answers = result.answers.filter(answer => answer.choice === choice); const option = choice === "A" ? result.question.option_a : result.question.option_b; return <section key={choice} className={`result-choice-group choice-group-${choice}`} aria-labelledby={`choice-${choice}-heading`}><div className="result-choice-group-heading"><span className="choice-letter" aria-hidden="true">{choice}</span><div><h4 id={`choice-${choice}-heading`}>{option}</h4><p>{answers.length}人が選択</p></div></div><div className="result-choice-players">{answers.length > 0 ? answers.map(answer => { const player = state.players.find(item => item.id === answer.player_id); const isCurrentPlayer = answer.player_id === identity?.player_id; return <article key={answer.player_id}><ReactionAvatarButton compact target={{ id: answer.player_id, username: answer.username }} surfaceId={result.question_id} disabled={isCurrentPlayer || !player?.connected} onSelect={reactions.openPicker}><img width="30" height="30" src={avatarUrl(answer.player_id)} alt="" /></ReactionAvatarButton><strong><PlayerName name={answer.username} /></strong></article>; }) : <p className="muted">選んだ人はいません</p>}</div></section>; })}</div>{result.answers.some(answer => answer.choice === null) && <div className="result-unanswered"><strong>未回答</strong><span>{result.answers.filter(answer => answer.choice === null).map(answer => answer.username).join("、")}</span></div>}<p className="score-change">この問題で <strong>{ownScore >= 0 ? `+${ownScore}` : ownScore}</strong> ポイント</p></> : <p className="muted">結果を集計しています…</p>}
    </section>}

    {viewingResults && <><section className="card final-summary-card"><span className="step-label">最終結果</span><h2>今夜の最終ランキング 🏆</h2><div className="podium">{displayedBoard.slice(0, 3).map((player, index) => <article key={player.id} className={`podium-place place-${index + 1}`}><span aria-hidden="true">{["🥇", "🥈", "🥉"][index]}</span><strong><PlayerName name={player.username} /></strong><small>{player.score} ポイント</small></article>)}</div><div className="final-room-actions"><p className="muted">結果を確認したら、待機画面に戻れます。</p><button type="button" className="wide" onClick={returnToRoom}>ルームに戻る</button></div></section><details className="card leaderboard-card"><summary><span><span className="step-label">ランキング</span><strong>全員の順位を見る</strong></span><span className="leaderboard-summary-count">{displayedBoard.length}人</span></summary><ol className="leaderboard">{displayedBoard.map(player => { const isCurrentPlayer = player.id === identity?.player_id; return <li key={player.id} className={isCurrentPlayer ? "is-you" : ""} aria-label={isCurrentPlayer ? `${player.rank}位、${player.username}、自分、${player.score}ポイント` : undefined}><span><b>{player.rank}</b><PlayerName name={player.username} />{isCurrentPlayer && <i className="self-marker" aria-hidden="true" />}</span><strong>{player.score}<small> ポイント</small></strong></li>; })}</ol></details><section className="card review-card"><h2>回答を振り返る</h2><p className="muted">各問題で全員が最後に選んだ回答を確認できます。</p>{displayedReview.map((review, index) => <details key={review.question.id} open={index === 0}><summary>第 {index + 1} 問：{review.question.title}<span>A {review.counts.A} · B {review.counts.B}</span></summary><div className="review-options"><span>A · {review.question.option_a}</span><span>B · {review.question.option_b}</span></div><div className="review-answers">{review.answers.map(answer => <article key={answer.player_id}><img width="30" height="30" loading="lazy" src={avatarUrl(answer.player_id)} alt="" /><strong><PlayerName name={answer.username} /></strong><span className={`review-choice choice-${answer.choice || "none"}`}>{answer.choice ? `${answer.choice} · ${answer.choice === "A" ? review.question.option_a : review.question.option_b}` : "未回答"}</span></article>)}</div></details>)}</section></>}
    <RoomReactionSurface reactions={reactions} />
    {message && <p className="error floating-message" role="alert">{message}</p>}
    {roomShareOpen && <BottomSheet open onClose={() => setRoomShareOpen(false)} labelledBy="room-share-title" describedBy="room-share-summary" header={<><span className="step-label">ルーム {roomId}</span><h2 id="room-share-title">このルームに招待</h2><p id="room-share-summary" className="muted">QRコードを読み取るか、URLを送って参加してもらいましょう。</p></>}>
      <div className="room-share-content">
        {roomUrl && <div className="room-share-qr" aria-label={`ルーム ${roomId} のQRコード`}><QRCodeSVG value={roomUrl} size={208} level="M" marginSize={2} title={`ルーム ${roomId} に参加するQRコード`} /></div>}
        <a className="room-share-url" href={roomUrl}>{roomUrl}</a>
        <div className="button-row room-share-actions"><button type="button" onClick={() => void shareRoomUrl()}>共有する</button><button type="button" className="secondary" onClick={() => void copyRoomUrl()}>URLをコピー</button></div>
        {shareMessage && <p className="notice room-share-message" role="status" aria-live="polite">{shareMessage}</p>}
      </div>
    </BottomSheet>}
    {pendingOwner && <BottomSheet open onClose={() => setPendingOwnerId(null)} labelledBy="owner-transfer-title" describedBy="owner-transfer-summary" closeLabel="キャンセル" header={<><span className="step-label">オーナー権限の引き継ぎ</span><h2 id="owner-transfer-title">ルームオーナーを変更しますか？</h2></>}>
      <p id="owner-transfer-summary"><PlayerName name={pendingOwner.username} />を新しいルームオーナーにします。</p>
      <p className="muted">変更すると、あなたは通常の参加者に戻り、ゲーム開始前に準備が必要になります。</p>
      <div className="button-row owner-transfer-actions"><button type="button" onClick={confirmOwnerTransfer}>オーナーを変更する</button></div>
    </BottomSheet>}
    {roomSettingsOpen && <BottomSheet open onClose={() => { if (!savingRoomSettings) setRoomSettingsOpen(false); }} labelledBy="room-settings-title" describedBy="room-settings-summary" closeLabel="キャンセル" header={<><span className="step-label">待機中のみ変更できます</span><h2 id="room-settings-title">ルーム設定</h2><p id="room-settings-summary" className="muted">次のゲームで使う人数とテンポを調整します。</p></>}>
      <form onSubmit={saveRoomSettings}><div className="room-setup-grid">
        <div className="room-setup-field"><label htmlFor="room-max-players">ルームの定員</label><input id="room-max-players" type="number" inputMode="numeric" min={Math.max(2, state.players.length)} max="100" step="1" value={roomSettingsDraft.max_players} onChange={event => updateRoomSettingsDraft("max_players", event.target.value)} required /><small>現在の参加人数以上、最大100人</small></div>
        <div className="room-setup-field"><label htmlFor="room-question-count">出題数</label><input id="room-question-count" type="number" inputMode="numeric" min="1" max={availableQuestionCount} step="1" value={roomSettingsDraft.question_count} onChange={event => updateRoomSettingsDraft("question_count", event.target.value)} required /><small>1〜{availableQuestionCount}問</small></div>
        <div className="room-setup-field"><label htmlFor="room-question-duration">回答時間</label><input id="room-question-duration" type="number" inputMode="numeric" min="10" max="60" step="10" value={roomSettingsDraft.question_duration} onChange={event => updateRoomSettingsDraft("question_duration", event.target.value)} required /><small>10〜60秒（10秒刻み）</small></div>
        <div className="room-setup-field"><label htmlFor="room-result-duration">問題間の待ち時間</label><input id="room-result-duration" type="number" inputMode="numeric" min="5" max="30" step="5" value={roomSettingsDraft.between_question_duration} onChange={event => updateRoomSettingsDraft("between_question_duration", event.target.value)} required /><small>5〜30秒（5秒刻み）</small></div>
      </div><div className="button-row room-setup-actions"><button type="submit" disabled={savingRoomSettings}>{savingRoomSettings ? "保存しています…" : "設定を保存"}</button></div></form>
    </BottomSheet>}
  </main>;
}
