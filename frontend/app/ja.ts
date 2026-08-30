const apiMessages: Record<string, string> = {
  ADMIN_UNAUTHORIZED: "管理者として認証できませんでした。",
  QUESTION_NOT_FOUND: "質問が見つかりません。",
  QUESTION_REQUIRES_SHIKASHI: "質問には転換語「しかし」を必ず入れてください。",
  QUESTION_SELECTION_NOT_ACTIVE: "現在は問題を選ぶ時間ではありません。",
  PARENT_ONLY: "今回の親だけが問題を選べます。",
  PARENT_ANSWERS_FIRST: "親が回答を決めるまでお待ちください。",
  PARENT_ANSWER_LOCKED: "親の回答はすでに確定しています。",
  USER_STORAGE_NOT_AVAILABLE: "ユーザーデータを利用できません。",
  USER_NOT_FOUND: "ユーザーが見つかりません。",
  AVATAR_NOT_AVAILABLE: "アバターを利用できません。",
  AVATAR_NOT_FOUND: "アバターが見つかりません。",
  ROOM_NOT_FOUND: "ルームが見つかりません。",
  GAME_ALREADY_STARTED: "ゲームはすでに始まっています。",
  ROOM_FULL: "このルームは満員です。",
  MAX_PLAYERS_BELOW_CURRENT_PLAYERS: "定員を現在の参加人数より少なくすることはできません。",
  NOT_ENOUGH_QUESTIONS: "出題数を現在の質問数以下にしてください。",
  INVALID_ROOM_SETTINGS: "ルーム設定の値を確認してください。",
  PLAYERS_NOT_READY: "全員が準備完了になるまで開始できません。",
  OWNER_ONLY: "ルームオーナーだけがこの操作を行えます。",
  OWNER_DOES_NOT_READY: "ルームオーナーは準備操作を行いません。",
  PLAYER_NOT_FOUND: "指定したプレイヤーが見つかりません。",
  INVALID_SESSION: "セッションが無効です。もう一度参加してください。",
  GAME_NOT_PAUSABLE: "現在の状態では一時停止できません。",
  GAME_NOT_PAUSED: "ゲームは一時停止されていません。",
  GAME_NOT_RUNNING: "ゲームは進行中ではありません。",
  GAME_NOT_FINISHED: "ゲーム終了後にルームへ戻れます。",
  INVALID_ANSWER: "この回答は受け付けられません。",
  QUESTION_EXPIRED: "回答時間が終了しました。",
  REACTIONS_NOT_AVAILABLE: "待機中か結果表示中にリアクションを送れます。",
  REACTION_SCOPE_EXPIRED: "表示が切り替わったため、リアクションを送れませんでした。",
  SELF_REACTION_NOT_ALLOWED: "自分にはリアクションを送れません。",
  REACTION_TARGET_UNAVAILABLE: "このプレイヤーには今リアクションを送れません。",
  REACTION_RATE_LIMITED: "リアクションは少し間をあけて送ってください。",
  ROOM_REACTION_RATE_LIMITED: "リアクションが混み合っています。少し待ってから送ってください。",
  INVALID_REACTION: "このリアクションは送れません。",
  "Add at least one question first": "先に質問を1問以上登録してください。",
  "Only waiting rooms can be edited": "待機中のルームだけ編集できます。",
  "Only waiting rooms can be deleted": "待機中のルームだけ削除できます。",
  "Game is not waiting": "このゲームは待機中ではありません。",
  "Countdown is not active": "カウントダウン中ではありません。",
  "No active question": "進行中の質問がありません。",
  "Question must be scored first": "先に回答を締め切って採点してください。",
};

const statusLabels: Record<string, string> = {
  WAITING: "待機中",
  COUNTDOWN: "開始前",
  SELECTING: "親が問題を選択中",
  PARENT_ANSWERING: "親が先に回答中",
  QUESTION: "回答中",
  PAUSED: "一時停止中",
  LOCK: "集計中",
  SHOW_RESULT: "結果表示中",
  FINISHED: "終了",
};

export function apiMessage(value: unknown, fallback: string): string {
  return typeof value === "string" ? apiMessages[value] || fallback : fallback;
}

export function statusLabel(status: string): string {
  return statusLabels[status] || status;
}
