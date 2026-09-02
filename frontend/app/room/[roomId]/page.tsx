"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { BottomSheet } from "../../BottomSheet";
import { apiMessage, gameRulesCopy, GameRuleSpec } from "../../ja";
import { PlayerName } from "../../PlayerName";
import { QuestionText } from "../../QuestionText";
import { GameRules } from "../../GameRules";
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
type Result = { question_id: string; question: QuestionSummary; counts: { A: number; B: number }; answers: AnswerReview[]; scores: Record<string, number>; parent_id?: string | null; majority_choice?: "A" | "B" | null; leaderboard: BoardEntry[] };
type Review = { question: QuestionSummary; counts: { A: number; B: number }; answers: AnswerReview[]; parent_id?: string | null; majority_choice?: "A" | "B" | null };
type PreviousGame = { leaderboard: BoardEntry[]; review: Review[] };
const choiceLabels = { A: "押す", B: "押さない" } as const;
type RoomSettingsDraft = { title: string; max_players: string; round_count: string; selection_duration: string; question_duration: string; between_question_duration: string };
type RoomClock = { revision: number; phase: State["status"]; server_time: string; running: boolean; started_at: string | null; ends_at: string | null; duration_ms: number | null; remaining_ms: number };
type State = {
  title: string | null;
  status: "WAITING" | "COUNTDOWN" | "SELECTING" | "PARENT_ANSWERING" | "QUESTION" | "PAUSED" | "LOCK" | "SHOW_RESULT" | "FINISHED";
  owner_id: string | null;
  players: { id: string; username: string; score: number; ready: boolean; connected: boolean }[];
  current_question_index: number;
  question_count: number;
  round_count: number;
  current_round: number;
  current_parent_id: string | null;
  answered: number;
  settings: { game_name: string; max_players: number; selection_duration: number; question_duration: number; result_duration: number };
  rules?: GameRuleSpec;
  phase_started_at?: string;
  phase_duration?: number;
  clock: RoomClock;
  paused_status?: string;
  result?: Result | null;
  review?: Review[];
  previous_game?: PreviousGame | null;
  question?: { id: string; title: string; option_a: string; option_b: string };
  question_options?: { id: string; title: string }[];
};

function clockSecondsRemaining(clock: RoomClock | undefined, currentTime: number): number {
  if (!clock) return 0;
  if (!clock.running || !clock.ends_at) return Math.max(0, Math.ceil(clock.remaining_ms / 1000));
  return Math.max(0, Math.ceil((new Date(clock.ends_at).getTime() - currentTime) / 1000));
}

function avatarUrl(playerId: string): string {
  return `${api}/api/players/${playerId}/avatar?v=${encodeURIComponent(avatarStyleVersion)}`;
}

function RoundFlow({ phase }: { phase: "selecting" | "answering" | "everyone" }) {
  const currentStep = phase === "selecting" ? 0 : phase === "answering" ? 1 : 2;
  const steps = [
    { mark: "問", label: "質問選択" },
    { mark: "親", label: "親の回答" },
    { mark: "全", label: "みんなの回答" },
  ];
  return <ol className={`game-flow phase-${phase}`} aria-label="回答までの流れ">
    {steps.map((step, index) => <li key={step.label} className={index < currentStep ? "is-done" : index === currentStep ? "is-current" : ""} aria-current={index === currentStep ? "step" : undefined}>
      <span aria-hidden="true">{index < currentStep ? "✓" : step.mark}</span><b>{step.label}</b>
    </li>)}
  </ol>;
}

function ParentGameWait({ phase, parentName }: { phase: "selecting" | "answering"; parentName: string }) {
  const answering = phase === "answering";
  return <div className={`parent-game-wait wait-${phase}`} role="status">
    <div className="wait-game-board" aria-hidden="true">
      <div className="wait-card-stack"><i /><i /><i><span>?</span></i></div>
      <div className="wait-choice-duel"><b>押</b><em>VS</em><b>待</b></div>
      <span className="wait-turn-token">親</span>
    </div>
    <div className="wait-game-copy">
      {answering && <span className="wait-selected-badge"><i aria-hidden="true">✓</i> 問題が決まりました</span>}
      <strong>{answering ? "次は、親が先に回答します" : "親が問題を選び中です"}</strong>
      <p>{answering ? `${parentName}さんの回答が終わると、みんなの回答画面が始まります。` : `${parentName}さんが今回の問題を選んでいます…`}</p>
    </div>
  </div>;
}

function ScoreChangeBurst({ score, resultKey }: { score: number; resultKey: string }) {
  const tone = score > 0 ? "gain" : score < 0 ? "loss" : "even";
  const amount = score > 0 ? `+${score}` : score < 0 ? `−${Math.abs(score)}` : "±0";
  const message = score > 0
    ? `${score}ポイント増えました！`
    : score < 0
      ? `${Math.abs(score)}ポイント減りました`
      : "今回はポイントの変動なし";

  return <div key={resultKey} className={`score-change score-change-${tone}`} role="status" aria-live="polite" aria-atomic="true">
    <span className="visually-hidden">この問題のポイント変動：{message}</span>
    <div className="score-change-burst" aria-hidden="true">
      <span className="score-change-rays" />
      <i className="score-spark score-spark-one" />
      <i className="score-spark score-spark-two" />
      <i className="score-spark score-spark-three" />
      <div className="score-ticket">
        <small>{score > 0 ? "POINT GET!" : score < 0 ? "SCORE CHANGE" : "STAY"}</small>
        <strong>{amount}</strong>
        <span>ポイント</span>
      </div>
    </div>
    <p>{message}</p>
  </div>;
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
  const [rulesOpen, setRulesOpen] = useState(false);
  const [roomUrl, setRoomUrl] = useState("");
  const [shareMessage, setShareMessage] = useState("");
  const [roomSettingsOpen, setRoomSettingsOpen] = useState(false);
  const [savingRoomSettings, setSavingRoomSettings] = useState(false);
  const [roomSettingsDraft, setRoomSettingsDraft] = useState<RoomSettingsDraft>({ title: "", max_players: "12", round_count: "1", selection_duration: "15", question_duration: "20", between_question_duration: "5" });
  const [showPreviousGame, setShowPreviousGame] = useState(false);
  const [currentTime, setCurrentTime] = useState(Date.now());
  const [serverClockOffsetMs, setServerClockOffsetMs] = useState(0);
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0);
  const [showAnswerHandoff, setShowAnswerHandoff] = useState(false);
  const questionDeckRef = useRef<HTMLDivElement | null>(null);
  const selectionQuestionId = useRef<string | null>(null);
  const clockSynchronized = useRef(false);
  const clockSyncSamples = useRef<{ rtt: number; offset: number }[]>([]);
  const latestClockRevision = useRef(-1);
  const latestStatus = useRef<State["status"] | null>(null);
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
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [roomId]);
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
    const isReactionCooldown = message === "リアクションは少し間をあけて送ってください。"
      || message === "リアクションが混み合っています。少し待ってから送ってください。";
    if (!isReactionCooldown) return;
    const timer = window.setTimeout(() => setMessage(current => current === message ? "" : current), 3_000);
    return () => window.clearTimeout(timer);
  }, [message]);
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
    if (state?.status !== "SELECTING") return;
    setActiveQuestionIndex(0);
    questionDeckRef.current?.scrollTo({ left: 0, behavior: "auto" });
  }, [state?.current_question_index, state?.status]);
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
    let answerHandoffTimer: number | null = null;

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
      latestStatus.current = data.room.status;
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
          const previousStatus = latestStatus.current;
          latestStatus.current = item.payload.status;
          if (previousStatus === "PARENT_ANSWERING" && item.payload.status === "QUESTION" && item.payload.current_parent_id !== player.player_id) {
            if (answerHandoffTimer !== null) window.clearTimeout(answerHandoffTimer);
            setShowAnswerHandoff(true);
            answerHandoffTimer = window.setTimeout(() => {
              setShowAnswerHandoff(false);
              answerHandoffTimer = null;
            }, 1_800);
          } else if (item.payload.status !== "QUESTION") {
            setShowAnswerHandoff(false);
          }
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
      if (answerHandoffTimer !== null) window.clearTimeout(answerHandoffTimer);
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

  function chooseQuestion(questionId: string) {
    if (!ws || ws.readyState !== WebSocket.OPEN || !identity || state?.current_parent_id !== identity.player_id) {
      setMessage("親だけが今回の問題を選べます。");
      return;
    }
    setMessage("");
    ws.send(JSON.stringify({ type: "select_question", payload: { question_id: questionId } }));
  }

  function moveQuestionDeck(nextIndex: number) {
    const deck = questionDeckRef.current;
    const cards = deck ? Array.from(deck.querySelectorAll<HTMLElement>("[data-question-card]")) : [];
    const index = Math.max(0, Math.min(cards.length - 1, nextIndex));
    cards[index]?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    setActiveQuestionIndex(index);
  }

  function trackQuestionDeck() {
    const deck = questionDeckRef.current;
    if (!deck) return;
    const center = deck.getBoundingClientRect().left + deck.clientWidth / 2;
    const cards = Array.from(deck.querySelectorAll<HTMLElement>("[data-question-card]"));
    let closest = 0;
    cards.forEach((card, index) => {
      if (Math.abs(card.getBoundingClientRect().left + card.clientWidth / 2 - center) < Math.abs(cards[closest].getBoundingClientRect().left + cards[closest].clientWidth / 2 - center)) closest = index;
    });
    setActiveQuestionIndex(closest);
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
      await navigator.share({ title: `${state?.title || "マジョリティ"} · ルーム ${roomId}`, text: `${state?.title ? `${state.title}（` : ""}ルーム ${roomId}${state?.title ? "）" : ""} に参加してください。`, url: roomUrl });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setShareMessage("共有できませんでした。URLをコピーして送ってください。");
    }
  }

  async function openRoomSettings() {
    if (!state) return;
    setPendingOwnerId(null);
    setRoomSettingsDraft({
      title: state.title || "",
      max_players: String(state.settings.max_players),
      round_count: String(state.round_count),
      selection_duration: String(state.settings.selection_duration),
      question_duration: String(state.settings.question_duration),
      between_question_duration: String(state.settings.result_duration),
    });
    setRoomSettingsOpen(true);
  }

  function updateRoomSettingsDraft(field: keyof RoomSettingsDraft, value: string) {
    setRoomSettingsDraft(current => ({ ...current, [field]: field === "title" ? value : value.replace(/^0+(?=\d)/, "") }));
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
      title: roomSettingsDraft.title.trim() || null,
      max_players: Number(roomSettingsDraft.max_players),
      round_count: Number(roomSettingsDraft.round_count),
      selection_duration: Number(roomSettingsDraft.selection_duration),
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
  const currentParent = state?.players.find(player => player.id === state.current_parent_id);
  const isCurrentParent = Boolean(identity && state?.current_parent_id === identity.player_id);
  const parentAnswerLocked = Boolean(state?.status === "QUESTION" && isCurrentParent && confirmedChoice);
  const canConfirm = Boolean(selectedChoice && selectedChoice !== confirmedChoice && !isConfirming && !parentAnswerLocked);
  const ownScore = identity && result ? result.scores[identity.player_id] ?? 0 : 0;
  const currentOwnScore = identity ? state?.players.find(player => player.id === identity.player_id)?.score ?? 0 : 0;
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
  const roundFlowPhase = state?.status === "SELECTING" ? "selecting" : state?.status === "PARENT_ANSWERING" ? "answering" : state?.status === "QUESTION" ? "everyone" : null;
  const isParentWaitPage = !isCurrentParent && (state?.status === "SELECTING" || state?.status === "PARENT_ANSWERING");

  if (!state) return <main id="main-content" className="loading-stage"><span className="loading-orbit" aria-hidden="true" /><h1>入室しています…</h1><p role="status">ルーム {roomId || "…"} に参加しています</p>{message && <p className="error" role="alert">{message}</p>}</main>;

  return <main id="main-content" className={`game-page${isParentWaitPage ? " parent-wait-page" : ""}`}>
    <header className="game-header"><div><span className="eyebrow">ルーム {roomId}</span><h1>{state.title || state.settings.game_name}</h1></div><div className="game-header-actions"><button type="button" className="secondary room-header-button room-rules-button" onClick={() => setRulesOpen(true)} aria-haspopup="dialog"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4.5h10a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3V4.5Z" /><path d="M8 4.5V17a3 3 0 0 0 3 3M11 9h4M11 13h4" /></svg><span>ルール</span></button>{state.status === "WAITING" && !viewingResults && <button type="button" className="secondary room-header-button room-share-button" onClick={() => { setShareMessage(""); setRoomShareOpen(true); }} aria-haspopup="dialog"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.6 10.5 6.8-4M8.6 13.5l6.8 4" /></svg><span>共有</span></button>}{(state.status !== "WAITING" || viewingResults) && <div className="player-score"><small>{viewingResults ? "最終スコア" : "現在のスコア"}</small><strong>{viewingResults ? (identity ? displayedBoard.find(player => player.id === identity.player_id)?.score ?? 0 : 0) : currentOwnScore}</strong></div>}</div></header>
    <div className="visually-hidden" aria-live="polite" aria-atomic="true">ゲーム状況：{viewingResults ? "ゲーム結果を表示中" : state.status === "WAITING" ? "プレイヤーの準備待ち" : state.status === "COUNTDOWN" ? (remaining === 0 ? "スタート" : "まもなく開始") : state.status === "SELECTING" ? `${currentParent?.username || "親"}が問題を選択中` : state.status === "PARENT_ANSWERING" ? `${currentParent?.username || "親"}が先に回答中` : state.status === "QUESTION" ? `第${state.current_question_index + 1}問` : state.status === "PAUSED" ? "一時停止中" : state.status === "SHOW_RESULT" ? (isLastQuestion ? "最終結果を計算中" : "この問題の結果を表示中") : "集計中"}</div>

    {state.status === "WAITING" && !viewingResults && <section className="card waiting-card"><div className="section-heading"><div><span className="step-label">プレイヤー待機中</span><h2>みんなの準備を待っています</h2><p className="muted">参加者全員が準備できたら開始できます。ほかの人のアバターを押すと、リアクションを送れます。</p></div><div className="ready-meter" aria-label={`${participants.length}人中${readyCount}人が準備完了`}><strong>{readyCount}</strong><span>/ {participants.length}</span></div></div><div className="ready-list">{state.players.map(player => { const isCurrentPlayer = player.id === identity?.player_id; return <article key={player.id} className={`${player.id === state.owner_id ? "room-owner" : player.ready ? "ready" : "not-ready"}${isCurrentPlayer ? " is-you" : ""}`} aria-label={isCurrentPlayer ? `${player.username}、自分のプレイヤーカード` : undefined}><ReactionAvatarButton target={{ id: player.id, username: player.username }} surfaceId="waiting" disabled={isCurrentPlayer || !player.connected} onSelect={reactions.openPicker}><img width="38" height="38" src={avatarUrl(player.id)} alt="" /></ReactionAvatarButton><span>{player.id === state.owner_id ? "★ ルームオーナー" : player.ready ? "✓ 準備完了" : "○ 準備中"}</span><strong><PlayerName name={player.username} />{isCurrentPlayer && <i className="self-marker" aria-hidden="true" />}</strong>{isOwner && player.id !== state.owner_id && <button type="button" className="secondary transfer-owner" onClick={() => setPendingOwnerId(player.id)}>オーナーにする</button>}</article>; })}</div><div className="waiting-actions">{isOwner ? <button type="button" className="waiting-primary-action" onClick={startGame} disabled={!everyoneReady}>{participants.length === 0 ? "参加者を待っています" : everyoneReady ? "ゲームを開始！" : `準備待ち（${readyCount}/${participants.length}）`}</button> : <button type="button" className="ready-toggle waiting-primary-action" aria-pressed={isReady} onClick={markReady}>{isReady ? "✓ 準備完了" : "準備"}</button>}<div className="waiting-secondary-actions">{isOwner && <button type="button" className="secondary" onClick={() => void openRoomSettings()}>ルーム設定</button>}<a className="secondary admin-button" href="/">ロビーに戻る</a></div></div>{state.previous_game && <button type="button" className="secondary previous-game-button" onClick={() => setShowPreviousGame(true)}>前回のゲーム結果を見る</button>}</section>}

    {state.status === "COUNTDOWN" && <section className="card phase-card countdown-card"><p className="eyebrow">最初の親まであと少し</p><strong className={`phase-number${remaining === 0 ? " phase-start" : ""}`} role="timer" aria-label={remaining === 0 ? "スタート" : `残り${remaining}秒`}>{remaining === 0 ? "スタート！" : remaining}</strong><p>親が問題を選んだら、みんなで「押す・押さない」を考えます。</p></section>}

    {roundFlowPhase && <nav className="game-flow-shell" aria-label="現在のゲーム進行"><RoundFlow phase={roundFlowPhase} /></nav>}

    {state.status === "SELECTING" && <section className={`card parent-selection-card${!isCurrentParent ? " parent-spectator-card" : ""}`} aria-labelledby="parent-selection-title">
      <div className="question-meta"><span>ラウンド {state.current_round} / {state.round_count} · 第 {state.current_question_index + 1} ターン</span><strong className="timer" role="timer">{remaining}<small>秒</small></strong></div>
      <div className="time-track" aria-hidden="true"><i style={{ width: `${phaseProgress}%` }} /></div>
      <div className="parent-selection-heading">{state.current_parent_id && <img width="64" height="64" src={avatarUrl(state.current_parent_id)} alt="" />}<div><p>{isCurrentParent ? "あなたが今回の親です" : "今回の親"}</p><h2 id="parent-selection-title">{currentParent ? <PlayerName name={currentParent.username} /> : "親を確認しています"}</h2></div></div>
      {isCurrentParent ? <div className="question-deck-shell"><div className="question-deck-intro"><p>カードを左右にめくって、意見が割れそうな一枚を選んでください。</p><strong>{activeQuestionIndex + 1}<small> / {(state.question_options || []).length}</small></strong></div><div className="question-deck" ref={questionDeckRef} onScroll={trackQuestionDeck} aria-label="問題カード"><span className="question-deck-spacer" aria-hidden="true" />{(state.question_options || []).map((question, index) => <article data-question-card key={question.id} className={`question-deck-card${index === activeQuestionIndex ? " is-active" : ""}`}><span className="deck-card-number">CARD {String(index + 1).padStart(2, "0")}</span><strong><QuestionText title={question.title} /></strong><button type="button" onClick={() => chooseQuestion(question.id)}>この問題を選ぶ</button></article>)}<span className="question-deck-spacer" aria-hidden="true" /></div><div className="question-deck-controls"><button type="button" className="deck-arrow" aria-label="前の問題" disabled={activeQuestionIndex === 0} onClick={() => moveQuestionDeck(activeQuestionIndex - 1)}>←</button><div className="deck-dots" aria-hidden="true">{(state.question_options || []).map((question, index) => <i key={question.id} className={index === activeQuestionIndex ? "active" : ""} />)}</div><button type="button" className="deck-arrow" aria-label="次の問題" disabled={activeQuestionIndex >= (state.question_options || []).length - 1} onClick={() => moveQuestionDeck(activeQuestionIndex + 1)}>→</button></div></div> : <ParentGameWait phase="selecting" parentName={currentParent?.username || "親"} />}
    </section>}

    {state.status === "PARENT_ANSWERING" && !isCurrentParent && <section className="card parent-selection-card parent-spectator-card parent-answer-wait" aria-labelledby="parent-answer-wait-title"><div className="question-meta"><span className="step-label">親の回答待ち</span><strong className="timer" role="timer" aria-label={`親の回答まで残り${remaining}秒`}>{remaining}<small>秒</small></strong></div><div className="time-track" aria-hidden="true"><i style={{ width: `${phaseProgress}%` }} /></div><h2 id="parent-answer-wait-title" className="visually-hidden">問題決定後、親の回答を待っています</h2><ParentGameWait phase="answering" parentName={currentParent?.username || "親"} /></section>}

    {state.status === "PAUSED" && <section className="card phase-card paused-card"><p className="eyebrow">管理者が一時停止しました</p><strong className="phase-number" aria-hidden="true">Ⅱ</strong><p>そのままお待ちください。まもなく再開します。</p></section>}

    {((state.status === "QUESTION" && !showAnswerHandoff) || (state.status === "PARENT_ANSWERING" && isCurrentParent)) && state.question && <section className={`card question-card${state.status === "PARENT_ANSWERING" ? " parent-first-answer" : ""}`} aria-labelledby="question-title">
      <div className="question-meta"><span>ラウンド {state.current_round} / {state.round_count} · {state.status === "PARENT_ANSWERING" ? "親の先行回答" : `親：${currentParent?.username || "—"}`}</span><strong className="timer" role="timer" aria-label={`残り${remaining}秒`}>{remaining}<small>秒</small></strong></div>
      <div className="time-track" aria-hidden="true"><i style={{ width: `${phaseProgress}%` }} /></div>
      <div className="question-prompt"><div><span className="button-question-label">このボタン、押す？</span><h2 id="question-title"><QuestionText title={state.question.title} /></h2></div><img className="question-button-image" src="/images/ultimate-button.webp" width="220" height="220" alt="赤い究極の選択ボタン" /></div>
      <p className="answer-count" aria-live="polite">{state.status === "PARENT_ANSWERING" ? "親の回答は、結果発表までみんなには見えません。" : `${state.answered} / ${state.players.length} 人が回答を確定`}</p>
      <div className="choices" role="group" aria-label="ボタンを押すか選択"><button type="button" disabled={parentAnswerLocked} aria-pressed={selectedChoice === "A"} className={`choice a ${selectedChoice === "A" ? "selected-choice" : ""}`} onClick={() => selectAnswer("A")}><span className="choice-symbol" aria-hidden="true">●</span><span className="choice-copy">押す</span><span className="choice-check" aria-hidden="true">✓</span></button><button type="button" disabled={parentAnswerLocked} aria-pressed={selectedChoice === "B"} className={`choice b ${selectedChoice === "B" ? "selected-choice" : ""}`} onClick={() => selectAnswer("B")}><span className="choice-symbol" aria-hidden="true">—</span><span className="choice-copy">押さない</span><span className="choice-check" aria-hidden="true">✓</span></button></div>
      <button type="button" className="wide confirm-answer" disabled={!canConfirm} onClick={confirmAnswer}>{isConfirming ? "回答を確定しています…" : parentAnswerLocked ? "親の回答は確定済みです" : state.status === "PARENT_ANSWERING" && selectedChoice ? `誰にも見せず「${choiceLabels[selectedChoice]}」で確定` : confirmedChoice ? "選び直した回答を確定" : selectedChoice ? `「${choiceLabels[selectedChoice]}」で確定` : "押すか、押さないかを選んでください"}</button>
      {confirmedChoice && <p className="notice answer-notice" role="status">「{choiceLabels[confirmedChoice]}」で確定しました。{parentAnswerLocked ? "ほかのプレイヤーの回答を待っています。" : "変更する場合は、もう一方を選んで再度確定してください。"}</p>}
    </section>}

    {showAnswerHandoff && <div className="answer-handoff" role="region" aria-label="回答開始のお知らせ" aria-live="assertive" aria-atomic="true">
      <div className="answer-handoff-card">
        <span className="answer-handoff-kicker">YOUR TURN</span>
        <div className="answer-handoff-token" aria-hidden="true"><i>親</i><b>→</b><i>あなた</i></div>
        <h2>あなたの番です！</h2>
        <p>親の回答が決まりました。<br />今度はあなたが「押す・押さない」を選んでください。</p>
        <span className="answer-handoff-progress" aria-hidden="true" />
      </div>
    </div>}

    {state.status === "SHOW_RESULT" && <section className="card result-card stage-card">
      <div className="row"><div><span className="step-label">{isLastQuestion ? "最終問題" : `第 ${state.current_question_index + 1} 問`}</span><h2>{isLastQuestion ? "最終結果を計算しています" : "この問題の結果"}</h2></div><strong className="timer" role="timer">{isLastQuestion ? `集計完了まであと ${remaining} 秒` : `次の問題まであと ${remaining} 秒`}</strong></div>
      {result ? <><p className="parent-result-note"><strong>親：{currentParent?.username || "—"}</strong><span>多数派：{result.majority_choice ? choiceLabels[result.majority_choice] : "なし"}</span></p><ScoreChangeBurst score={ownScore} resultKey={result.question_id} /><div className="result-reaction-heading"><h3 className="result-answer-heading">みんなの選択</h3><span>アバターを押してリアクション</span></div><div className="result-choice-groups">{(["A", "B"] as const).map(choice => { const answers = result.answers.filter(answer => answer.choice === choice); return <section key={choice} className={`result-choice-group choice-group-${choice}`} aria-labelledby={`choice-${choice}-heading`}><div className="result-choice-group-heading"><span className="choice-letter" aria-hidden="true">{choice === "A" ? "●" : "—"}</span><div><h4 id={`choice-${choice}-heading`}>{choiceLabels[choice]}</h4><p>{answers.length}人が選択</p></div></div><div className="result-choice-players">{answers.length > 0 ? answers.map(answer => { const player = state.players.find(item => item.id === answer.player_id); const isCurrentPlayer = answer.player_id === identity?.player_id; const isParent = answer.player_id === result.parent_id; return <article key={answer.player_id} aria-label={isCurrentPlayer ? `${answer.username}、自分` : undefined}><ReactionAvatarButton compact target={{ id: answer.player_id, username: answer.username }} surfaceId={result.question_id} disabled={isCurrentPlayer || !player?.connected} onSelect={reactions.openPicker}><img width="30" height="30" src={avatarUrl(answer.player_id)} alt="" />{isParent && <span className="result-parent-badge" aria-label="この問題の親">親</span>}{isCurrentPlayer && <span className="result-self-badge" aria-hidden="true">自分</span>}</ReactionAvatarButton><strong><PlayerName name={answer.username} /></strong></article>; }) : <p className="muted">選んだ人はいません</p>}</div></section>; })}</div>{result.answers.some(answer => answer.choice === null) && <div className="result-unanswered"><strong>未回答</strong><span>{result.answers.filter(answer => answer.choice === null).map(answer => answer.username).join("、")}</span></div>}</> : <p className="muted">結果を集計しています…</p>}
    </section>}

    {viewingResults && <><section className="card final-summary-card"><span className="step-label">最終結果</span><h2>今夜の最終ランキング 🏆</h2><div className="podium">{displayedBoard.slice(0, 3).map((player, index) => <article key={player.id} className={`podium-place place-${index + 1}`}><span aria-hidden="true">{["🥇", "🥈", "🥉"][index]}</span><strong><PlayerName name={player.username} /></strong><small>{player.score} ポイント</small></article>)}</div><div className="final-room-actions"><p className="muted">結果を確認したら、待機画面に戻れます。</p><button type="button" className="wide" onClick={returnToRoom}>ルームに戻る</button></div></section><details className="card leaderboard-card"><summary><span><span className="step-label">ランキング</span><strong>全員の順位を見る</strong></span><span className="leaderboard-summary-count">{displayedBoard.length}人</span></summary><ol className="leaderboard">{displayedBoard.map(player => { const isCurrentPlayer = player.id === identity?.player_id; return <li key={player.id} className={isCurrentPlayer ? "is-you" : ""} aria-label={isCurrentPlayer ? `${player.rank}位、${player.username}、自分、${player.score}ポイント` : undefined}><span><b>{player.rank}</b><PlayerName name={player.username} />{isCurrentPlayer && <i className="self-marker" aria-hidden="true" />}</span><strong>{player.score}<small> ポイント</small></strong></li>; })}</ol></details><section className="card review-card"><h2>回答を振り返る</h2><p className="muted">各問題で、当時の親とあなたの回答を確認できます。</p>{displayedReview.map((review, index) => { const reviewParentName = review.answers.find(answer => answer.player_id === review.parent_id)?.username || "—"; return <details key={review.question.id} open={index === 0}><summary><strong className="review-question-title">第 {index + 1} 問：<QuestionText title={review.question.title} /></strong><span>押す {review.counts.A} · 押さない {review.counts.B}</span></summary><div className="review-parent"><span>親</span><strong><PlayerName name={reviewParentName} /></strong></div><div className="review-options"><span>● 押す</span><span>— 押さない</span></div><div className="review-answers">{review.answers.map(answer => { const isParent = answer.player_id === review.parent_id; const isCurrentPlayer = answer.player_id === identity?.player_id; const roles = [isParent ? "この問題の親" : "", isCurrentPlayer ? "あなた" : ""].filter(Boolean).join("、"); return <article key={answer.player_id} className={isCurrentPlayer ? "is-you" : ""} aria-label={roles ? `${answer.username}、${roles}` : undefined}><img width="30" height="30" loading="lazy" src={avatarUrl(answer.player_id)} alt="" /><div className="review-player-name"><strong><PlayerName name={answer.username} /></strong>{(isParent || isCurrentPlayer) && <span className="review-role-badges" aria-hidden="true">{isParent && <i className="is-parent">親</i>}{isCurrentPlayer && <i className="is-self">あなた</i>}</span>}</div><span className={`review-choice choice-${answer.choice || "none"}`}>{answer.choice ? choiceLabels[answer.choice] : "未回答"}</span></article>; })}</div></details>; })}</section></>}
    <RoomReactionSurface reactions={reactions} />
    {message && <div className="error floating-message" role="alert"><span>{message}</span><button type="button" onClick={() => setMessage("")} aria-label="メッセージを閉じる">×</button></div>}
    {rulesOpen && <BottomSheet open onClose={() => setRulesOpen(false)} labelledBy="rules-title" describedBy="rules-summary" closeLabel={gameRulesCopy.closeLabel} className="rules-sheet" header={<><span className="step-label">{gameRulesCopy.eyebrow}</span><h2 id="rules-title">{gameRulesCopy.title}</h2><p id="rules-summary" className="muted">{gameRulesCopy.summary}</p></>}><GameRules rules={state.rules} /></BottomSheet>}
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
        <div className="room-setup-field room-title-field"><label htmlFor="room-title">ルームタイトル <span className="optional-label">任意</span></label><input id="room-title" type="text" value={roomSettingsDraft.title} onChange={event => updateRoomSettingsDraft("title", event.target.value)} maxLength={40} placeholder="例：金曜夜の二択会" /><small>空欄にすると標準タイトルに戻ります（最大40文字）</small></div>
        <div className="room-setup-field"><label htmlFor="room-max-players">ルームの定員</label><input id="room-max-players" type="number" inputMode="numeric" min={Math.max(2, state.players.length)} max="100" step="1" value={roomSettingsDraft.max_players} onChange={event => updateRoomSettingsDraft("max_players", event.target.value)} required /><small>現在の参加人数以上、最大100人</small></div>
        <div className="room-setup-field"><label htmlFor="room-round-count">ラウンド数</label><input id="room-round-count" type="number" inputMode="numeric" min="1" max="10" step="1" value={roomSettingsDraft.round_count} onChange={event => updateRoomSettingsDraft("round_count", event.target.value)} required /><small>1ラウンドで全員が1回ずつ親になります（1〜10ラウンド）</small></div>
        <div className="room-setup-field"><label htmlFor="room-selection-duration">問題を選ぶ時間</label><input id="room-selection-duration" type="number" inputMode="numeric" min="5" max="60" step="5" value={roomSettingsDraft.selection_duration} onChange={event => updateRoomSettingsDraft("selection_duration", event.target.value)} required /><small>5〜60秒（時間切れで自動選択）</small></div>
        <div className="room-setup-field"><label htmlFor="room-question-duration">回答時間</label><input id="room-question-duration" type="number" inputMode="numeric" min="10" max="60" step="10" value={roomSettingsDraft.question_duration} onChange={event => updateRoomSettingsDraft("question_duration", event.target.value)} required /><small>10〜60秒（10秒刻み）</small></div>
        <div className="room-setup-field"><label htmlFor="room-result-duration">問題間の待ち時間</label><input id="room-result-duration" type="number" inputMode="numeric" min="5" max="30" step="5" value={roomSettingsDraft.between_question_duration} onChange={event => updateRoomSettingsDraft("between_question_duration", event.target.value)} required /><small>5〜30秒（5秒刻み）</small></div>
      </div><div className="button-row room-setup-actions"><button type="submit" disabled={savingRoomSettings}>{savingRoomSettings ? "保存しています…" : "設定を保存"}</button></div></form>
    </BottomSheet>}
  </main>;
}
