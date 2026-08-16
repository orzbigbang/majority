"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const wsBase = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const identityKey = "party-quiz-player";
const avatarStyleVersion = process.env.NEXT_PUBLIC_AVATAR_STYLE_VERSION || "party-token-v1";

type Identity = { player_id: string; username: string; session_id?: string };
type BoardEntry = { rank: number; id: string; username: string; score: number };
type Result = { question_id: string; counts: { A: number; B: number }; scores: Record<string, number>; leaderboard: BoardEntry[] };
type Review = { question: { id: string; title: string; option_a: string; option_b: string }; counts: { A: number; B: number }; answers: { player_id: string; username: string; choice: "A" | "B" | null }[] };
type State = {
  status: "WAITING" | "COUNTDOWN" | "QUESTION" | "PAUSED" | "LOCK" | "SHOW_RESULT" | "FINISHED";
  players: { id: string; username: string; score: number; ready: boolean; connected: boolean }[];
  current_question_index: number;
  question_count: number;
  answered: number;
  settings: { game_name: string };
  phase_started_at?: string;
  phase_duration?: number;
  paused_status?: string;
  result?: Result | null;
  review?: Review[];
  question?: { id: string; title: string; option_a: string; option_b: string };
};

function secondsRemaining(startedAt?: string, duration?: number, currentTime = Date.now()): number {
  if (!startedAt || duration === undefined) return 0;
  return Math.max(0, Math.ceil((new Date(startedAt).getTime() + duration * 1000 - currentTime) / 1000));
}

function avatarUrl(playerId: string): string {
  return `${api}/api/players/${playerId}/avatar?v=${encodeURIComponent(avatarStyleVersion)}`;
}

export default function RoomPage({ params }: { params: Promise<{ roomId: string }> }) {
  const router = useRouter();
  const [roomId, setRoomId] = useState("");
  const [state, setState] = useState<State | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [selectedChoice, setSelectedChoice] = useState<"A" | "B" | null>(null);
  const [confirmedChoice, setConfirmedChoice] = useState<"A" | "B" | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [currentTime, setCurrentTime] = useState(Date.now());
  const selectionQuestionId = useRef<string | null>(null);

  useEffect(() => { params.then(value => setRoomId(value.roomId.toUpperCase())); }, [params]);
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
    async function connect() {
      try {
      const response = await fetch(`${api}/api/rooms/${roomId}/join`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: player.username, player_id: player.player_id, session_id: player.session_id || undefined }),
      });
      const data = await response.json();
      if (!response.ok) { if (active) setMessage(data.detail || "无法加入房间"); return; }
      if (!active) return;
      try {
        const stored = JSON.parse(localStorage.getItem(identityKey) || "{}");
        localStorage.setItem(identityKey, JSON.stringify({ ...stored, session_id: data.session_id }));
      } catch { /* The player ID still provides a safe recovery path. */ }
      selectionQuestionId.current = data.room.question?.id || null;
      setSelectedChoice(data.draft_choice || null);
      setConfirmedChoice(data.confirmed_choice || null);
      setState(data.room);
      setResult(data.room.result || null);
      socket = new WebSocket(`${wsBase}/ws/rooms/${roomId}?player_id=${encodeURIComponent(player.player_id)}`);
      socket.onmessage = event => {
        const item = JSON.parse(event.data);
        if (item.type === "game_state") {
          setState(item.payload);
          setResult(item.payload.result || null);
        }
        if (item.type === "room_deleted") { active = false; router.replace("/"); }
        if (item.type === "answer_count") setState(current => current ? { ...current, answered: item.payload.answered } : current);
        if (item.type === "answer_saved") { setConfirmedChoice(item.payload.choice); setIsConfirming(false); }
        if (item.type === "result") setResult(item.payload);
        if (item.type === "error") { setIsConfirming(false); setMessage(item.payload.message); }
      };
      socket.onclose = () => {
        if (!active) return;
        setWs(null);
        setMessage("连接暂时中断，正在重新连接…");
        window.setTimeout(() => { if (active) void connect(); }, 1500);
      };
      setWs(socket);
      } catch {
        if (!active) return;
        setMessage("连接暂时中断，正在重新连接…");
        window.setTimeout(() => { if (active) void connect(); }, 1500);
      }
    }
    void connect();
    return () => { active = false; socket?.close(); };
    // Identity changes only when navigating back from the lobby.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, identity]);

  function confirmAnswer() {
    if (!state?.question || !ws || ws.readyState !== WebSocket.OPEN || !identity || !selectedChoice || selectedChoice === confirmedChoice) {
      if (!ws || ws.readyState !== WebSocket.OPEN) setMessage("连接恢复中，请稍后确认答案。");
      return;
    }
    ws.send(JSON.stringify({ type: "answer", player_id: identity.player_id, payload: { question_id: state.question.id, choice: selectedChoice } }));
    setIsConfirming(true);
  }

  function selectAnswer(choice: "A" | "B") {
    if (!state?.question || !ws || ws.readyState !== WebSocket.OPEN || !identity) {
      setMessage("连接恢复中，暂时无法选择答案。");
      return;
    }
    setSelectedChoice(choice);
    ws.send(JSON.stringify({ type: "select_answer", player_id: identity.player_id, payload: { question_id: state.question.id, choice } }));
  }

  function markReady() {
    if (!ws || !identity) return;
    ws.send(JSON.stringify({ type: "ready", player_id: identity.player_id }));
  }

  const board = useMemo(() => result?.leaderboard ?? [...(state?.players || [])]
    .sort((a, b) => b.score - a.score || a.username.localeCompare(b.username))
    .map((player, index) => ({ rank: index + 1, ...player })), [result, state]);
  const remaining = secondsRemaining(state?.phase_started_at, state?.phase_duration, currentTime);
  const canConfirm = Boolean(selectedChoice && selectedChoice !== confirmedChoice && !isConfirming);
  const ownScore = identity && result ? result.scores[identity.player_id] ?? 0 : 0;
  const readyCount = state?.players.filter(player => player.ready).length || 0;
  const isReady = Boolean(identity && state?.players.find(player => player.id === identity.player_id)?.ready);

  if (!state) return <main><p>正在加入房间…</p><p className="error">{message}</p></main>;

  return <main>
    <div className="row"><h1>{state.settings.game_name}</h1><span className="muted">房间 {roomId}</span></div>

    {state.status === "WAITING" && <div className="card"><h2>已进入房间</h2><p>请在所有人准备好后，由主持人开始游戏。</p><div className="ready-summary"><strong>{readyCount} / {state.players.length}</strong><span className="muted">位玩家已准备</span></div><div className="ready-list">{state.players.map(player => <article key={player.id} className={`${player.ready ? "ready" : "not-ready"} ${player.connected ? "" : "offline"}`}><img src={avatarUrl(player.id)} alt="" /><span>{player.connected ? (player.ready ? "✓ 已准备" : "○ 未准备") : "离线"}</span><strong>{player.username}{player.id === identity?.player_id ? "（你）" : ""}</strong></article>)}</div><div className="button-row"><button onClick={markReady} disabled={isReady}>{isReady ? "已准备" : "我准备好了"}</button><button className="secondary" onClick={() => router.push("/")}>返回大厅</button></div></div>}

    {state.status === "COUNTDOWN" && <div className="card phase-card countdown-card"><p className="eyebrow">即将开始</p><strong className="phase-number">{remaining}</strong><p className="muted">请准备好选择你的答案</p></div>}

    {state.status === "PAUSED" && <div className="card phase-card paused-card"><p className="eyebrow">游戏已暂停</p><strong className="phase-number">Ⅱ</strong><p className="muted">主持人将在准备好后继续游戏。</p></div>}

    {state.status === "QUESTION" && state.question && <div className="card question-card">
      <div className="row"><p className="muted">第 {state.current_question_index + 1} / {state.question_count} 题 · 已回答 {state.answered}/{state.players.length}</p><strong className="timer">剩余 {remaining} 秒</strong></div>
      <h2>{state.question.title}</h2>
      <div className="choices"><button className={`choice a ${selectedChoice === "A" ? "selected-choice" : ""}`} onClick={() => selectAnswer("A")}>A<br />{state.question.option_a}</button><button className={`choice b ${selectedChoice === "B" ? "selected-choice" : ""}`} onClick={() => selectAnswer("B")}>B<br />{state.question.option_b}</button></div>
      <button className="wide confirm-answer" disabled={!canConfirm} onClick={confirmAnswer}>{isConfirming ? "正在确认…" : confirmedChoice ? "确认切换答案" : "确认答案"}</button>
      {confirmedChoice && <p className="notice">当前已确认 {confirmedChoice}；可改选另一个选项后再次确认。</p>}
    </div>}

    {state.status === "SHOW_RESULT" && <div className="card result-card stage-card">
      <div className="row"><h2>本题结果</h2><strong className="timer">{remaining} 秒后进入下一题</strong></div>
      {result ? <><div className="result-counts"><span>A <strong>{result.counts.A}</strong></span><span>B <strong>{result.counts.B}</strong></span></div><p className="score-change">你本题获得 <strong>{ownScore >= 0 ? `+${ownScore}` : ownScore}</strong> 分</p></> : <p className="muted">正在汇总结果…</p>}
    </div>}

    {state.status === "FINISHED" && <><section className="card"><h2>最终结果 🏆</h2><div className="podium">{board.slice(0, 3).map((player, index) => <article key={player.id} className={`podium-place place-${index + 1}`}><span>{["🥇", "🥈", "🥉"][index]}</span><strong>{player.username}</strong><small>{player.score} 分</small></article>)}</div></section><section className="card review-card"><h2>答题回顾</h2><p className="muted">查看每道题所有玩家的最终选择。</p>{(state.review || []).map((review, index) => <details key={review.question.id} open={index === 0}><summary>第 {index + 1} 题：{review.question.title}<span>A {review.counts.A} · B {review.counts.B}</span></summary><div className="review-options"><span>A · {review.question.option_a}</span><span>B · {review.question.option_b}</span></div><div className="review-answers">{review.answers.map(answer => <article key={answer.player_id}><img src={avatarUrl(answer.player_id)} alt="" /><strong>{answer.username}</strong><span className={`review-choice choice-${answer.choice || "none"}`}>{answer.choice ? `${answer.choice} · ${answer.choice === "A" ? review.question.option_a : review.question.option_b}` : "未作答"}</span></article>)}</div></details>)}</section></>}

    <div className="card"><h2>{state.status === "FINISHED" ? "完整排名" : "当前排名"}</h2><ol className="leaderboard">{board.map(player => <li key={player.id}><span>{player.rank}. {player.username}</span><strong>{player.score}</strong></li>)}</ol></div>
    <p className="error">{message}</p>
  </main>;
}
