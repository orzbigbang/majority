"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export type RoomExitReason = "not-found" | "already-started" | "full" | "deleted" | "access-lost";

type RoomExitNotice = {
  roomId: string;
  title: string;
  detail: string;
};

const noticeCopy: Record<RoomExitReason, (roomId: string) => Omit<RoomExitNotice, "roomId">> = {
  "not-found": roomId => ({
    title: `ルーム ${roomId} が見つかりません。`,
    detail: "ルームが終了または削除された可能性があります。参加できるルームを下から選んでください。",
  }),
  "already-started": roomId => ({
    title: `ルーム ${roomId} のゲームはすでに始まっています。`,
    detail: "ゲーム進行中のため途中参加できません。参加できるルームを下から選んでください。",
  }),
  full: roomId => ({
    title: `ルーム ${roomId} は満員です。`,
    detail: "参加人数が上限に達しました。参加できるルームを下から選んでください。",
  }),
  deleted: roomId => ({
    title: `ルーム ${roomId} は削除されました。`,
    detail: "このルームは利用できなくなりました。参加できるルームを下から選んでください。",
  }),
  "access-lost": roomId => ({
    title: `ルーム ${roomId} との接続を継続できませんでした。`,
    detail: "ルームまたは参加情報が無効になった可能性があります。参加できるルームを下から選んでください。",
  }),
};

const joinErrorReasons: Record<string, RoomExitReason> = {
  ROOM_NOT_FOUND: "not-found",
  GAME_ALREADY_STARTED: "already-started",
  ROOM_FULL: "full",
  INVALID_SESSION: "access-lost",
};

export function useRoomExitRedirect() {
  const router = useRouter();

  const exitRoom = useCallback((reason: RoomExitReason, roomId: string) => {
    const search = new URLSearchParams({ roomExit: reason, roomId: roomId.toUpperCase() });
    router.replace(`/?${search.toString()}`);
  }, [router]);

  const exitForJoinError = useCallback((detail: unknown, status: number, roomId: string) => {
    const reason = typeof detail === "string" ? joinErrorReasons[detail] : undefined;
    if (reason) {
      exitRoom(reason, roomId);
      return true;
    }
    if (status === 404) {
      exitRoom("not-found", roomId);
      return true;
    }
    return false;
  }, [exitRoom]);

  return { exitRoom, exitForJoinError };
}

export function useRoomExitNotice(): { notice: RoomExitNotice | null; clearNotice: () => void } {
  const [notice, setNotice] = useState<RoomExitNotice | null>(null);
  const clearNotice = useCallback(() => setNotice(null), []);

  useEffect(() => {
    const url = new URL(window.location.href);
    let reason = url.searchParams.get("roomExit") as RoomExitReason | null;
    let roomId = url.searchParams.get("roomId")?.toUpperCase() || "";

    // Accept links produced by the previous redirect implementation.
    const legacyMissingRoom = url.searchParams.get("roomNotFound")?.toUpperCase();
    const legacyStartedRoom = url.searchParams.get("roomAlreadyStarted")?.toUpperCase();
    if (!reason && legacyMissingRoom) { reason = "not-found"; roomId = legacyMissingRoom; }
    if (!reason && legacyStartedRoom) { reason = "already-started"; roomId = legacyStartedRoom; }

    if (reason && roomId && reason in noticeCopy) {
      setNotice({ roomId, ...noticeCopy[reason](roomId) });
      ["roomExit", "roomId", "roomNotFound", "roomAlreadyStarted"].forEach(key => url.searchParams.delete(key));
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, []);

  return { notice, clearNotice };
}
