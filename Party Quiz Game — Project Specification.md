# Party Quiz Game — Project Specification

## 1. 项目目标

实现一个适合聚会场景的实时多人答题 Web 应用。

核心玩法：

1. 主持人创建一个游戏房间。
2. 页面显示房间二维码。
3. 玩家扫码进入。
4. 第一次进入时输入用户名。
5. 浏览器保存 `session_id`，以后重新进入时自动恢复身份。
6. 所有人进入后，主持人开始游戏。
7. 每一题所有玩家同时看到两个选项。
8. 玩家选择 A 或 B。
9. 时间结束后统一公布结果。
10. 根据配置好的评分策略计算每个玩家得分。
11. 游戏结束后显示最终排行榜。
12. 取前三名。

目标用户规模：

- 单个房间约 10 人。
- MVP 不需要考虑大规模并发。
- 可以优先保证简单、稳定、低延迟。

---

# 2. 技术栈

## Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- WebSocket Client
- QR Code

前端包含两个区域：

```text
/player
/admin
```

---

## Backend

- Python
- FastAPI
- WebSocket
- Cloud Run

Cloud Run 初期限制：

```text
max instances = 1
```

原因：

MVP 阶段一个游戏房间只有约 10 人，可以直接将实时游戏状态保存在 Python 内存中。

---

## Persistence

MVP 可以使用：

- Firestore

但不要依赖 Firestore 保存实时游戏状态。

Firestore 主要保存：

```text
questions
game configuration
optional game history
```

实时状态保存在 Cloud Run 内存。

---

# 3. 总体架构

```text
                         ┌─────────────────┐
                         │     Browser     │
                         │                 │
                         │ Next.js / React │
                         └────────┬────────┘
                                  │
                         HTTP / WebSocket
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    Cloud Run    │
                         │                 │
                         │    FastAPI      │
                         │                 │
                         │ ┌─────────────┐ │
                         │ │ Game Engine │ │
                         │ ├─────────────┤ │
                         │ │ Room Manager│ │
                         │ ├─────────────┤ │
                         │ │Score Engine │ │
                         │ ├─────────────┤ │
                         │ │Admin API    │ │
                         │ └─────────────┘ │
                         │                 │
                         │ In-Memory State │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    Firestore    │
                         │                 │
                         │ Questions       │
                         │ Game Config     │
                         │ History         │
                         └─────────────────┘
```

---

# 4. 核心设计原则

## 4.1 游戏状态与持久化数据分离

实时游戏状态：

```text
Room
Player
Current Question
Answers
Timer
Scores
Game State
```

全部保存在内存。

持久化数据：

```text
Question
Game Configuration
Game History
```

保存在 Firestore。

不要为了每一次玩家操作都访问 Firestore。

---

# 5. 游戏状态机

游戏必须使用明确的状态机。

```text
WAITING
   │
   ▼
COUNTDOWN
   │
   ▼
QUESTION
   │
   ▼
LOCK
   │
   ▼
SHOW_RESULT
   │
   ▼
NEXT
   │
   ├───────────────┐
   │               │
   ▼               │
QUESTION ◄─────────┘
   │
   ▼
FINISHED
```

状态定义：

### WAITING

玩家加入房间。

主持人可以查看在线玩家。

### COUNTDOWN

开始游戏前倒计时，例如：

```text
3
2
1
```

### QUESTION

玩家可以提交答案。

### LOCK

禁止继续提交答案。

### SHOW_RESULT

公布：

- A/B 投票数量
- 多数派
- 每个玩家获得的分数
- 当前排行榜

### NEXT

进入下一题。

### FINISHED

显示最终排行榜。

---

# 6. Player Session

第一次进入：

```text
Browser
    │
    ▼
输入 username
    │
    ▼
POST /api/rooms/{room_id}/join
    │
    ▼
session_id
player_id
    │
    ▼
localStorage
```

localStorage：

```json
{
  "session_id": "...",
  "player_id": "...",
  "room_id": "..."
}
```

重新进入：

```text
localStorage
      │
      ▼
session_id
      │
      ▼
Backend
      │
      ▼
恢复 Player
```

session 不需要复杂认证。

MVP 可以使用随机 UUID。

---

# 7. Room

Room 是游戏运行的核心对象。

```python
class Room:
    id: str
    status: GameStatus

    players: dict[str, Player]

    questions: list[Question]

    current_question_index: int

    answers: dict[str, Answer]

    started_at: datetime | None

    question_started_at: datetime | None
```

Player：

```python
class Player:
    id: str
    session_id: str
    username: str
    score: int
    connected: bool
```

---

# 8. Question

Question：

```python
class Question:
    id: str
    title: str

    option_a: str
    option_b: str

    score_strategy: str

    score_config: dict
```

例如：

```json
{
  "id": "q001",
  "title": "你更喜欢猫还是狗？",
  "option_a": "猫",
  "option_b": "狗",
  "score_strategy": "majority",
  "score_config": {
    "winner_score": 1,
    "loser_score": 0
  }
}
```

---

# 9. Answer

```python
class Answer:
    player_id: str
    question_id: str
    choice: Literal["A", "B"]
    answered_at: datetime
```

同一个玩家对于同一道题只能提交一次。

服务器必须保证：

```text
QUESTION 状态
+
未回答
=
允许提交
```

其他情况拒绝。

---

# 10. WebSocket

实时游戏使用 WebSocket。

客户端发送：

```text
join
answer
heartbeat
```

服务器发送：

```text
player_joined
player_left

game_state

countdown

question

timer

answer_received

answer_count

question_locked

result

leaderboard

game_finished
```

统一消息格式：

```json
{
  "type": "question",
  "payload": {}
}
```

---

# 11. Question Flow

服务器发送：

```json
{
  "type": "question",
  "payload": {
    "question_id": "q001",
    "title": "你喜欢猫还是狗？",
    "option_a": "猫",
    "option_b": "狗",
    "duration": 20
  }
}
```

客户端开始显示倒计时。

玩家发送：

```json
{
  "type": "answer",
  "payload": {
    "question_id": "q001",
    "choice": "A"
  }
}
```

服务器记录答案。

服务器广播：

```json
{
  "type": "answer_count",
  "payload": {
    "answered": 7,
    "total": 10
  }
}
```

时间结束：

```text
QUESTION
    ↓
LOCK
    ↓
calculate score
    ↓
SHOW_RESULT
```

---

# 12. Score Engine

评分系统必须设计成可扩展接口。

```python
class ScoreStrategy(Protocol):

    def calculate(
        self,
        question: Question,
        answers: list[Answer],
    ) -> dict[str, int]:
        ...
```

输出：

```python
{
    "player001": 1,
    "player002": 0,
    "player003": 1
}
```

---

# 13. MVP Score Strategies

## Majority

多数派获得分数。

例如：

```text
A = 7
B = 3
```

A：

```text
+1
```

B：

```text
0
```

配置：

```json
{
  "winner_score": 1,
  "loser_score": 0
}
```

---

## Minority

少数派获得分数。

```json
{
  "winner_score": 2,
  "loser_score": 0
}
```

---

## Fixed

根据正确答案判断。

例如：

```json
{
  "correct_answer": "A",
  "correct_score": 1,
  "wrong_score": 0
}
```

---

# 14. Score Strategy Registry

不要使用大量 if/else。

使用 Registry：

```python
STRATEGIES = {
    "majority": MajorityStrategy(),
    "minority": MinorityStrategy(),
    "fixed": FixedStrategy(),
}
```

以后可以增加：

```text
speed
streak
random
multiplier
custom
```

而不修改 Game Engine。

---

# 15. Tie Handling

多人最终分数可能相同。

MVP：

```text
按照最终得分降序排列。

如果前三名出现并列：

使用答题时间总和作为第二排序条件。
```

未来可以增加：

```text
答题正确数量
平均答题速度
最后一题得分
```

---

# 16. Player UI

## Join

```text
┌─────────────────────┐
│                     │
│    PARTY QUIZ       │
│                     │
│   输入你的名字      │
│                     │
│   [____________]    │
│                     │
│       [加入]        │
│                     │
└─────────────────────┘
```

---

## Waiting

```text
Party Quiz

房间：ABCD

玩家：

Alice
Bob
Charlie
David
...

等待主持人开始

已加入 8 / 10
```

---

## Question

```text
第 5 / 10 题

你更喜欢？

┌──────────┐
│   猫     │
└──────────┘

┌──────────┐
│   狗     │
└──────────┘

剩余 12 秒

已回答 7 / 10
```

---

## Result

```text
本题结果

猫 ███████ 7

狗 ███     3

你获得 +1

当前排名

1 Alice  6
2 Bob    5
3 David  4
```

---

## Final

```text
FINAL RESULT

🥇 Alice    12

🥈 Bob      10

🥉 David     8

────────────

Charlie      7
Emily        5
...
```

---

# 17. Admin UI

Admin UI：

```text
/admin
```

包含：

```text
Dashboard
Questions
Game Settings
Room Control
```

---

# 18. Question Management

管理员可以：

```text
Create
Edit
Delete
Reorder
Duplicate
```

Question Editor：

```text
Question

[________________________]

Option A

[________________________]

Option B

[________________________]

Score Strategy

[ Majority ▼ ]

Score Configuration

Winner Score: [1]
Loser Score:  [0]

[Save]
```

---

# 19. Game Configuration

```text
Game Settings

Game Name
[Party Quiz]

Question Duration
[20] seconds

Result Duration
[5] seconds

Countdown
[3] seconds

Questions
[10]

Score Strategy
[Per Question]

[Save]
```

---

# 20. Admin Room Control

这是 Admin UI 的核心。

```text
ROOM ABCD

Status: QUESTION

Players: 8 / 10

Current Question: 5 / 10

Time Remaining: 12s

A: 5
B: 3

──────────────────

[Next Question]

[Pause]

[Reset Game]

[End Game]
```

管理员可以实时控制游戏。

---

# 21. Admin API

```text
GET    /api/admin/questions

POST   /api/admin/questions

GET    /api/admin/questions/{id}

PUT    /api/admin/questions/{id}

DELETE /api/admin/questions/{id}

POST   /api/admin/questions/reorder
```

Game：

```text
GET /api/admin/game

PUT /api/admin/game

POST /api/admin/game/start

POST /api/admin/game/pause

POST /api/admin/game/resume

POST /api/admin/game/next

POST /api/admin/game/reset

POST /api/admin/game/end
```

---

# 22. Admin Authentication

MVP 不需要复杂 RBAC。

可以使用：

```text
ADMIN_PASSWORD
```

存储在 Cloud Run Secret / Environment Variable。

Admin 登录：

```text
POST /api/admin/login
```

成功后返回 admin session。

不要把 admin password 放到前端代码中。

---

# 23. Firestore

建议 Collections：

```text
questions/
    {question_id}

games/
    {game_id}

game_history/
    {game_id}
```

Question：

```json
{
  "title": "...",
  "option_a": "...",
  "option_b": "...",
  "score_strategy": "majority",
  "score_config": {
    "winner_score": 1,
    "loser_score": 0
  },
  "order": 1
}
```

实时 Room 不需要保存到 Firestore。

---

# 24. In-Memory Architecture

推荐：

```python
class GameManager:

    rooms: dict[str, Room]

    def create_room(...)
    def join_room(...)
    def leave_room(...)
    def start_game(...)
    def submit_answer(...)
    def next_question(...)
    def calculate_result(...)
```

GameManager 是整个应用的核心。

FastAPI Router 不应该直接修改 Room 内部状态。

例如：

```text
API/WebSocket
      ↓
GameManager
      ↓
Room
      ↓
ScoreEngine
```

---

# 25. Concurrency

因为使用 WebSocket + asyncio：

所有 Room 状态修改必须考虑并发。

例如：

```python
async with room.lock:
    submit_answer(...)
```

必须避免：

```text
两个请求同时提交答案

↓

重复提交

↓

score calculation race condition
```

每个 Room 使用自己的 asyncio Lock。

---

# 26. Timer

不要依赖前端倒计时。

服务器保存：

```python
question_started_at
question_duration
```

客户端只负责显示：

```text
remaining =
question_started_at
+ duration
- current_time
```

服务器负责最终判断是否超时。

这样客户端修改时间不会作弊。

---

# 27. QR Code

创建 Room 后：

```text
https://example.com/room/ABCD
```

Admin 页面显示二维码。

玩家扫码：

```text
/room/ABCD
```

---

# 28. Room ID

使用短 ID：

```text
ABCD
```

或者：

```text
7K3P
```

避免使用 UUID 作为玩家输入。

内部仍然可以使用 UUID。

---

# 29. Error Handling

WebSocket 错误：

```json
{
  "type": "error",
  "payload": {
    "code": "ALREADY_ANSWERED",
    "message": "Already answered"
  }
}
```

至少定义：

```text
ROOM_NOT_FOUND
ROOM_FULL
GAME_ALREADY_STARTED
INVALID_ANSWER
ALREADY_ANSWERED
QUESTION_EXPIRED
INVALID_SESSION
ADMIN_UNAUTHORIZED
```

---

# 30. MVP Scope

第一版只实现：

### Player

- [ ] 扫码进入
- [ ] 输入用户名
- [ ] localStorage session
- [ ] 等待页面
- [ ] WebSocket
- [ ] 二选一
- [ ] 倒计时
- [ ] 结果
- [ ] 当前排行榜
- [ ] 最终 Top 3

### Admin

- [ ] Admin Login
- [ ] Question CRUD
- [ ] Question reorder
- [ ] Score strategy configuration
- [ ] Game settings
- [ ] Create Room
- [ ] QR Code
- [ ] Start
- [ ] Next
- [ ] Pause
- [ ] Reset
- [ ] End

### Backend

- [ ] FastAPI
- [ ] WebSocket
- [ ] GameManager
- [ ] Room state machine
- [ ] Score Engine
- [ ] Firestore repository
- [ ] Admin API

---

# 31. 不要在 MVP 实现

暂时不要加入：

- Redis
- PostgreSQL
- Kubernetes
- 微服务
- 多实例游戏状态同步
- 复杂用户认证
- 用户注册
- 好友系统
- 社交功能
- 多房间联动
- 排行榜历史分析
- 复杂权限系统

当前目标是：

```text
一个 Cloud Run
+
一个 Next.js
+
一个 Firestore
+
10 个玩家
```

先实现完整游戏闭环。

---

# 32. 推荐项目结构

```text
party-quiz/
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx
│   │   ├── room/[roomId]/
│   │   └── admin/
│   │
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   └── types/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── api/
│   │   │   ├── player.py
│   │   │   ├── admin.py
│   │   │   └── websocket.py
│   │   │
│   │   ├── game/
│   │   │   ├── manager.py
│   │   │   ├── room.py
│   │   │   ├── state_machine.py
│   │   │   └── timer.py
│   │   │
│   │   ├── scoring/
│   │   │   ├── base.py
│   │   │   ├── majority.py
│   │   │   ├── minority.py
│   │   │   └── fixed.py
│   │   │
│   │   ├── repository/
│   │   │   └── firestore.py
│   │   │
│   │   └── models/
│   │
│   ├── tests/
│   └── Dockerfile
│
├── docs/
│   └── architecture.md
│
└── README.md
```

---

# 33. Implementation Order

Codex 应按照以下顺序实现，不要一开始同时开发全部功能。

## Phase 1 — Backend Core

实现：

```text
Room
Player
Question
Answer
GameState
GameManager
```

以及：

```text
WAITING
QUESTION
LOCK
SHOW_RESULT
FINISHED
```

先用内存数据测试。

---

## Phase 2 — Score Engine

实现：

```text
ScoreStrategy
MajorityStrategy
MinorityStrategy
FixedStrategy
```

为每个策略编写单元测试。

---

## Phase 3 — WebSocket

实现：

```text
connect
join
answer
broadcast
disconnect
```

确保 10 个客户端可以同时连接。

---

## Phase 4 — Player UI

实现：

```text
Join
Waiting
Question
Result
Leaderboard
Final
```

---

## Phase 5 — Admin

实现：

```text
Login
Question CRUD
Game Settings
Room Control
```

---

## Phase 6 — Firestore

将：

```text
Questions
Game Settings
Game History
```

接入 Firestore。

使用 Repository abstraction，避免 Game Engine 直接依赖 Firestore SDK。

---

## Phase 7 — Deployment

部署：

```text
Next.js
    ↓
Cloud Run

FastAPI
    ↓
Cloud Run
```

配置：

```text
max instances = 1
```

---

# 34. Codex Implementation Rules

1. 优先实现 MVP，不提前引入复杂基础设施。
2. Game Engine 不依赖 FastAPI。
3. Game Engine 不直接依赖 Firestore。
4. Scoring Engine 不依赖 HTTP/WebSocket。
5. WebSocket 只负责 transport。
6. 所有游戏状态变更必须经过 GameManager。
7. 所有状态转换必须经过 State Machine。
8. 所有评分必须经过 ScoreStrategy。
9. 所有客户端时间只用于显示，服务器时间用于最终判定。
10. 所有关键状态变化编写测试。
11. 不要为了未来的多实例架构过度设计。
12. 保持 Python 类型完整。
13. 使用 Pydantic 定义 API/WebSocket payload。
14. 使用 pytest 编写 backend tests。
15. 前后端共享 TypeScript/Python API schema 时优先保持明确的数据契约。

---

# 35. Definition of Done

MVP 完成标准：

```text
Admin 创建房间
        ↓
生成二维码
        ↓
10 个手机扫码
        ↓
输入用户名
        ↓
所有人进入等待页面
        ↓
Admin 点击 Start
        ↓
所有客户端同时出现问题
        ↓
玩家选择 A/B
        ↓
20 秒结束
        ↓
服务器计算多数派
        ↓
显示本题结果
        ↓
进入下一题
        ↓
完成全部问题
        ↓
显示最终 Top 3
```

整个流程无需刷新页面。

Cloud Run 重启导致当前游戏状态丢失属于 MVP 可接受行为。