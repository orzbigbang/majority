"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PlayerName } from "../PlayerName";
import { QuestionText } from "../QuestionText";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const identityKey = "party-quiz-player";

type Identity = { player_id: string; username: string; avatar_url?: string; session_id?: string };
type HistoryAnswer = { question_id: string; question: string; option_a: string; option_b: string; choice: "A" | "B" | null; a_count: number; b_count: number; score: number };
type HistoryRecord = { id: string; room_id: string; game_name: string; finished_at: string; player_count: number; rank: number; score: number; answers: HistoryAnswer[] };
type Profile = {
  id: string;
  username: string;
  avatar_url: string;
  bio: string;
  favorite_choice: "A" | "B" | null;
  stats: { games: number; wins: number; average_rank: number | null; answer_rate: number | null };
  history: HistoryRecord[];
};

function readIdentity(): Identity | null {
  try { return JSON.parse(localStorage.getItem(identityKey) || "null"); } catch { return null; }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function ProfilePage() {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [username, setUsername] = useState("");
  const [bio, setBio] = useState("");
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);

  useEffect(() => {
    const saved = readIdentity();
    if (!saved?.player_id) { router.replace("/"); return; }
    setIdentity(saved);
    fetch(`${api}/api/players/${saved.player_id}`).then(async response => {
      if (!response.ok) throw new Error();
      return response.json();
    }).then((data: Profile) => {
      setProfile(data); setUsername(data.username); setBio(data.bio || "");
    }).catch(() => setMessage("プロフィールを読み込めませんでした。時間をおいてもう一度お試しください。"))
      .finally(() => setLoading(false));
  }, [router]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!identity || savingProfile) return;
    setMessage("");
    setSavingProfile(true);
    try {
      const response = await fetch(`${api}/api/players/${identity.player_id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, bio, favorite_choice: profile?.favorite_choice ?? null }),
      });
      const data = await response.json();
      if (!response.ok) { setMessage("変更を保存できませんでした。入力内容を確認してください。"); return; }
      const updatedIdentity = { ...identity, username: data.username, avatar_url: data.avatar_url };
      localStorage.setItem(identityKey, JSON.stringify(updatedIdentity));
      setIdentity(updatedIdentity);
      setProfile(current => current ? { ...current, username: data.username, bio: data.bio, favorite_choice: data.favorite_choice } : current);
      setEditing(false);
      setMessage("プロフィールを更新しました。");
    } catch {
      setMessage("プロフィールを保存できませんでした。通信状態を確認して、もう一度お試しください。");
    } finally {
      setSavingProfile(false);
    }
  }

  if (loading) return <main id="main-content" className="loading-stage"><span className="loading-orbit" aria-hidden="true" /><p role="status">プロフィールを準備しています…</p></main>;

  return <main id="main-content" className="profile-page">
    <nav className="profile-nav" aria-label="プロフィールのナビゲーション">
      <Link className="text-link" href="/"><span aria-hidden="true">←</span> ロビーへ戻る</Link>
      <span className="brand-lockup"><span className="brand-dice" aria-hidden="true">二択</span><span>マジョリティ</span></span>
    </nav>

    {profile && <>
      <header className="profile-hero">
        <div className="profile-avatar-wrap">
          <img src={`${api}${profile.avatar_url}`} width="112" height="112" alt="" />
          <span aria-hidden="true">YOU</span>
        </div>
        <div className="profile-intro">
          <span className="step-label">あなたのプレイヤーカード</span>
          <h1><PlayerName name={profile.username} /></h1>
          <p>{profile.bio || "ひとことを設定すると、あなたらしいプレイヤーカードになります。"}</p>
        </div>
        <button type="button" className="secondary profile-edit-button" onClick={() => { setEditing(value => !value); setMessage(""); }}>{editing ? "閉じる" : "プロフィールを編集"}</button>
      </header>

      {editing && <section className="card profile-settings" aria-labelledby="profile-settings-title">
        <span className="step-label">設定</span><h2 id="profile-settings-title">プレイヤー情報</h2>
        <form onSubmit={saveProfile}>
          <label htmlFor="profile-name">ニックネーム</label>
          <input id="profile-name" name="nickname" autoComplete="nickname" spellCheck={false} value={username} onChange={event => setUsername(event.target.value)} maxLength={30} required />
          <label htmlFor="profile-bio">ひとこと</label>
          <textarea id="profile-bio" name="bio" autoComplete="off" value={bio} onChange={event => setBio(event.target.value)} maxLength={120} placeholder="例：迷ったら直感で選びます…" />
          <button className="wide" disabled={savingProfile}>{savingProfile ? "保存しています…" : "変更を保存"}</button>
        </form>
      </section>}
      {message && <p className={message.includes("更新") ? "notice profile-message" : "error"} role="status">{message}</p>}

      <section className="profile-stats" aria-label="これまでの戦績">
        <article><small>プレイ</small><strong>{profile.stats.games}</strong><span>ゲーム</span></article>
        <article><small>1位</small><strong>{profile.stats.wins}</strong><span>回</span></article>
        <article><small>平均順位</small><strong>{profile.stats.average_rank ?? "—"}</strong><span>{profile.stats.average_rank ? "位" : ""}</span></article>
        <article><small>回答率</small><strong>{profile.stats.answer_rate ?? "—"}</strong><span>{profile.stats.answer_rate !== null ? "%" : ""}</span></article>
      </section>

      <section className="card history-board" aria-labelledby="history-title">
        <div className="section-heading"><div><span className="step-label">プレイログ</span><h2 id="history-title">これまでの戦績と選択</h2><p className="muted">ゲームごとに、順位とあなたが選んだ答えを振り返れます。</p></div></div>
        {profile.history.length === 0 ? <div className="empty"><span className="empty-mark" aria-hidden="true">?</span><div><h3>最初の戦績はこれから</h3><p className="muted">ゲームを最後まで遊ぶと、結果がここに残ります。</p></div></div> : <div className="game-history">{profile.history.map((game, gameIndex) => <details key={game.id} open={gameIndex === 0}>
          <summary><span className={`history-rank rank-${Math.min(game.rank, 4)}`}><strong>{game.rank}</strong>位</span><span className="history-game"><strong>{game.game_name}</strong><small>{formatDate(game.finished_at)} · ルーム {game.room_id}</small></span><span className="history-score">{game.score}<small>pt</small></span></summary>
          <div className="choice-trail">{game.answers.map((answer, index) => <article key={`${answer.question_id}-${index}`} className={`past-choice past-choice-${answer.choice || "none"}`}>
            <div className="choice-index">Q{index + 1}</div><div className="choice-history-copy"><strong><QuestionText title={answer.question} /></strong><span>{answer.choice ? (answer.choice === "A" ? "押す" : "押さない") : "未回答"}</span></div><div className="choice-history-result"><strong>{answer.score > 0 ? `+${answer.score}` : answer.score}</strong><small>押す {answer.a_count} : {answer.b_count} 押さない</small></div>
          </article>)}</div>
        </details>)}</div>}
      </section>
    </>}
    {!profile && <section className="card"><h1>プロフィールを表示できません</h1><p>{message}</p><Link className="text-link" href="/">ロビーへ戻る</Link></section>}
  </main>;
}
