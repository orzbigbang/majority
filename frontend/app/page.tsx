"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const identityKey = "party-quiz-player";
const avatarStyleVersion = process.env.NEXT_PUBLIC_AVATAR_STYLE_VERSION || "party-token-v1";
type Identity = { player_id: string; username: string; avatar_url?: string; session_id?: string };
type LobbyRoom = { room_id: string; status: string; player_count: number; max_players: number; game_name: string };

function savedIdentity(): Identity | null {
  try { return JSON.parse(localStorage.getItem(identityKey) || "null"); } catch { return null; }
}

function currentAvatarUrl(avatarUrl?: string): string | undefined {
  if (!avatarUrl) return undefined;
  return `${avatarUrl.split("?")[0]}?v=${encodeURIComponent(avatarStyleVersion)}`;
}

export default function Home() {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [nickname, setNickname] = useState("");
  const [rooms, setRooms] = useState<LobbyRoom[]>([]);
  const [message, setMessage] = useState("");
  const [destination, setDestination] = useState<string>();

  async function loadRooms() {
    try {
      const response = await fetch(`${api}/api/rooms`);
      if (!response.ok) throw new Error();
      setRooms(await response.json());
    } catch { setMessage("暂时无法连接游戏服务，请稍后重试。"); }
  }

  useEffect(() => {
    const existing = savedIdentity();
    if (existing?.player_id && existing.username) {
      const restored = { ...existing, avatar_url: currentAvatarUrl(existing.avatar_url) };
      if (restored.avatar_url !== existing.avatar_url) localStorage.setItem(identityKey, JSON.stringify(restored));
      setIdentity(restored);
      if (!existing.avatar_url) {
        fetch(`${api}/api/players/identity`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(existing),
        }).then(response => response.ok ? response.json() : null).then(data => {
          if (data) { localStorage.setItem(identityKey, JSON.stringify(data)); setIdentity(data); }
        });
      }
    }
    setDestination(new URLSearchParams(window.location.search).get("room")?.toUpperCase());
    loadRooms();
    const interval = window.setInterval(loadRooms, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (identity && destination) router.replace(`/room/${destination}`);
  }, [identity, destination, router]);

  async function saveIdentity(event: FormEvent) {
    event.preventDefault();
    const response = await fetch(`${api}/api/players/identity`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: nickname }),
    });
    const data = await response.json();
    if (!response.ok) { setMessage(data.detail || "无法保存昵称"); return; }
    localStorage.setItem(identityKey, JSON.stringify(data));
    setIdentity(data);
  }

  function enterRoom(roomId: string) { router.push(`/room/${roomId}`); }

  if (!identity) return <main className="lobby"><div className="row page-heading"><div className="hero"><span className="eyebrow">PARTY QUIZ</span><h1>开始今晚的选择题</h1><p className="muted">输入一个昵称，之后即使不小心关闭页面，也能回到你的游戏。</p></div><a className="secondary admin-button" href="/admin">管理后台</a></div><div className="card identity-card"><h2>你想怎么被称呼？</h2><form onSubmit={saveIdentity}><label>昵称<input autoFocus value={nickname} onChange={event => setNickname(event.target.value)} maxLength={30} placeholder="例如：小林" required /></label><button className="wide">进入大厅</button></form><p className="error">{message}</p></div></main>;

  return <main className="lobby"><div className="row page-heading"><div className="identity-summary">{identity.avatar_url && <img className="avatar" src={`${api}${identity.avatar_url}`} alt="你的头像" />}<div><span className="eyebrow">PARTY QUIZ</span><h1>欢迎，{identity.username}</h1></div></div><a className="secondary admin-button" href="/admin">管理后台</a></div>{destination && <p className="notice">请从大厅选择房间 {destination} 加入。</p>}<section className="card"><div className="row"><div><h2>游戏大厅</h2><p className="muted">房间每 5 秒自动更新</p></div><button className="secondary" onClick={loadRooms}>刷新</button></div>{rooms.length === 0 ? <div className="empty"><p>暂时还没有房间。</p><p className="muted">等待主持人创建游戏后，房间会显示在这里。</p></div> : <div className="room-list">{rooms.map(room => <article className="room-card" key={room.room_id}><div><span className={`status status-${room.status.toLowerCase()}`}>{room.status === "WAITING" ? "等待加入" : "游戏进行中"}</span><h3>{room.game_name}</h3><p className="muted">房间 {room.room_id} · {room.player_count}/{room.max_players} 人</p></div><button disabled={room.status !== "WAITING" || room.player_count >= room.max_players} onClick={() => enterRoom(room.room_id)}>{room.status === "WAITING" ? "加入" : "已开始"}</button></article>)}</div>}</section><p className="error">{message}</p></main>;
}
