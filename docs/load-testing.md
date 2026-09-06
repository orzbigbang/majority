# 12 人压力测试

脚本使用真实 HTTP + WebSocket，不导入后端游戏引擎、不跳过服务端倒计时。默认创建 12 人、每人当一次亲的完整游戏，通常约 5 分钟。

## 本地运行（PowerShell，项目根目录）

先启动现有 Firestore 模拟器：

```powershell
docker compose up -d firestore
docker compose run -d --no-deps --name majority-loadtest-api -p 8002:8000 -e FIRESTORE_PROJECT_ID=majority-loadtest -e AVATAR_STORAGE_ENABLED=false backend uvicorn app.main:app --host 0.0.0.0 --port 8000
uv run --python 3.13 backend/loadtest.py --container majority-loadtest-api --reconnect --output loadtest-report.json
```

需要 Docker 和 uv；uv 自动安装脚本固定版本的 HTTP/WebSocket 客户端依赖。首次使用先执行 `docker compose build backend`。测试容器使用当前挂载的后端代码、单个 worker、无 reload；端口 8002 与正常开发端口分开。Firestore 使用独立的 `majority-loadtest` 项目，但仍共用模拟器计算资源。不要把示例项目变量改成生产项目。

正常场景去掉 `--reconnect`；重复 10 局加 `--games 10`。每局创建新房间。小规模快速验证可用 `--players 2`。单局超时默认 900 秒，可用 `--game-timeout` 调整。

完成后只删除本次创建的容器：

```powershell
docker stop majority-loadtest-api
docker rm majority-loadtest-api
```

测试房间和测试用户保留在模拟器测试项目里方便调查，不清空共享模拟器数据。再次运行前需要先移除上次同名容器。报告不含 session 凭据。

## 已实现的检查

- 创建者入房后，其余 11 人并发加入；额外一人收到满员拒绝。
- 12 条独立连接全部准备，房主启动游戏。
- 根据实际服务端阶段选题，亲先提交，其余 11 人并发提交。
- 确认后发送相反草稿，最终逐题核对已确认答案未被覆盖。
- 使用独立的默认规则计算核对每题得分、票数、最终分数；12 个客户端的完整复盘一致。
- 可选：第一题选题阶段断开亲和两名玩家；答题确认后断开三名普通玩家，重连后继续完成整局。
- 记录答题确认延迟、同一 clock revision 首次到达所有客户端的时间差、重连到首个状态的耗时。
- 记录每题普通玩家并发发送的起始时间跨度，超过 100ms 时不通过（压测端未形成目标突发）。
- 可选读取独立测试容器本次运行时间范围内的日志；出现 ERROR、Traceback 或 RuntimeError 则失败。

报告中的 `passed` 同时要求业务检查和性能门槛通过。失败退出码为 1；报告包含失败原因、消息错误及各玩家最后阶段。未指定 `--container` 时 `server_logs.checked=false`，不能据此声称服务端无异常。

建议门槛：确认 P95 ≤ 500ms、P99 ≤ 1000ms；状态到达差 P95 ≤ 300ms；恢复连接到快照 ≤ 5000ms。样本数和分位数一同报告。状态到达差只统计所有玩家都收到的 revision，不等于服务端截止推进延迟，也不代表屏幕渲染同步。重连耗时不含脚本故意断开的 500ms。

## 范围与后续验证

这是协议层满员业务压测，尚未包含浏览器/手机渲染、网络丢包、慢消费者背压、表情洪峰、截止前后竞态注入、实例重启、多房间并发、持续资源采样。`--games 10` 可以重复运行，但不是已经完成了 10 局耐久验证。性能数字混合各题角色；启用重连时报告应与正常场景分开比较。

本地 Emulator 结果不能代表真实 Firestore / Cloud Run。云端应使用独立测试服务与数据项目，再通过 `--url https://测试服务` 运行；该选项会真实创建玩家和房间。确认单实例设置及 WebSocket 并发/超时配置后再测。服务端锁等待、持久化耗时和自动推进耗时还没有专门埋点。

## 2026-09-06 本地实测

环境：当前工作区后端，独立 8002 端口，无 reload，Firestore Emulator 测试项目；客户端与 Docker 在同一台电脑。未设置与 Cloud Run 相同的 CPU/内存上限。

12 人、1 局、12 题、6 次连接恢复，耗时 282.55 秒。144 次确认全部收到，逐题答案、票数、计分和所有客户端最终复盘核对通过。确认 P95 193.15ms、P99 217.16ms、最大 225.53ms；完整状态 revision 到达差 P95 3.68ms；重连到快照最大 49.94ms。见 [完整报告](loadtest-local-result.json)。

**修复前整体验收未通过。** 独立容器日志出现 3 次 `Exception in ASGI application`，异常为 `RuntimeError: WebSocket is not connected. Need to call "accept" first.`，栈指向 `backend/app/main.py` WebSocket 循环中的 `ws.receive_json()`。发生于本次断线/重连流程；客户端最终恢复并不代表服务端清理路径正确。此报告保留为修复前基线。

首次 12 人运行过程中补充了自动日志门槛；这份报告的服务端检查来自运行结束后对独立容器日志的复核，已明确写在 `server_logs.scope`。该次运行未采集后加的 `burst_send_span` 指标。最终版本另用两人短局验证，报告为 [短局报告](loadtest-smoke-result.json)。

以上不能推导线上承载能力、长时间无内存泄漏或多房间容量。

## 断线异常修复

Starlette 在发送时遇到关闭的底层连接，会将 `application_state` 改成 `DISCONNECTED`。广播层已经处理了发送失败，但接收循环原先无条件继续调用 `receive_json()`，于是抛出上述 RuntimeError。接收循环现在只在连接状态为 `CONNECTED` 时继续，断开后进入原有 finally 清理路径。没有通过捕获所有 RuntimeError 隐藏其他程序错误。

新增 `backend/tests/test_websocket_send_disconnect.py`，使用真实 Starlette WebSocket 注入底层 OSError，覆盖初始状态广播失败和已进入接收循环后的回复失败。两个案例在修复前稳定复现原异常；修复后验证连接注册表清理、亲身份/分数/草稿保留和同一 session 重连。

相关测试 10 项通过。全量测试首次 57 通过、1 失败（`test_failed_save_preserves_a_newer_watch_state`）；该持久化测试单独复跑通过，全量复跑 58 项全部通过。该项曾失败的记录保留，尚未针对其偶发性另行排查。

修复后使用最终版脚本完成同样的 12 人完整游戏：12 题、144 次确认、6 次连接恢复，耗时 282.73 秒。所有业务核对及性能门槛通过，自动检查服务端日志无异常。确认 P95 208.98ms、P99 231.30ms；状态到达差 P95 4.50ms；重连到快照最大 78.11ms；11 人集中提交的起始跨度最大 6.42ms。见 [修复后报告](loadtest-fixed-result.json)。这是本地单局复测，未进行线上或 10 局耐久验证。

## 2026-09-06 线上测试

目标为 `majority-git`，区域 `asia-northeast1`，修订 `majority-git-00015-6df`；1 vCPU / 512MiB，并发配置 80，请求超时 3600 秒。服务级 `maxScale=1`，修订级上限 20；服务级限制仍将服务限制为单实例。由本机作为单个压测节点发起，使用真实 HTTP、WebSocket 和线上持久化；没有修改部署配置。

首次重连尝试在脚本主动关闭连接后遇到 `sent 1000 (OK); no close frame received`，旧脚本将其计为意外连接错误而停止，见 [首次尝试](loadtest-online-result.json)。现将主动关闭期间的 ConnectionClosed 单独记为 `planned_close_warnings`，意外断线和其他异常仍失败。缺失关闭握手的原因尚未确定，不能据此认定后端崩溃；警告不会从报告中删除。分类行为通过 `backend/test_loadtest_client.py` 的 3 个案例验证。

正常基准局（房间 `2VMD`）完成 12 题、144 次确认，耗时 290.01 秒，答案、计分和各客户端复盘一致；确认 P95 1038.69ms、P99 4620.50ms、最大 4623.62ms，未达到 500ms / 1000ms 的目标。状态到达差 P95 7.67ms；11 人提交起始跨度最大 5.57ms。见 [基准报告](loadtest-online-baseline-result.json)。该局运行的是调整前脚本，收尾主动关闭的一条握手警告仍在 errors 中；即使排除它，延迟门槛仍未通过。

云端日志另行审计，见 [Cloud Run 日志摘要](loadtest-online-cloud-audit.json)；协议报告的 `server_logs.checked=false` 仅表示没有运行本地 Docker 日志检查。日志摘要保留查询时间范围、实例、修订及 HTTP 状态分布，避免保存含 session 查询参数的普通访问日志。409 满员拒绝是脚本有意触发的预期响应。

调整后的重连场景（房间 `DTRF`）完成 12 题、144 次确认及 6 次连接恢复，耗时 291.07 秒。答案、计分、复盘一致，没有客户端错误或关闭握手警告。确认 P95 995.08ms、P99 1155.71ms、最大 1162.64ms；仍未达到延迟门槛。状态到达差 P95 13.79ms；重连到快照最大 620.29ms；11 人提交起始跨度最大 3.28ms。见 [重连报告](loadtest-online-reconnect-result.json)。

结论：两局完整线上流程的业务一致性通过，重连恢复通过，确认延迟性能不通过。应先增加房间锁等待、Firestore 保存、确认发送的分段耗时记录，定位尾延迟后再优化；不应在缺少证据时直接扩容实例或放宽验收门槛。

测试创建了 `W9LH`、`2VMD`、`DTRF` 三个房间及对应测试用户/历史；没有批量删除线上数据。此测试不覆盖分布式客户端、真实手机渲染或长期容量。确认延迟尚无服务端分段追踪，不能仅凭结果将原因归结为 Firestore 或 CPU。

## 延迟诊断与可选计时

已查询同一测试时间段的 Cloud Monitoring 容器 CPU / 内存利用率，按 60 秒窗口使用 ALIGN_PERCENTILE_99 对齐：CPU 样本约 2.99%～10.99%，内存约 24.99%～26.99%。见 [CPU 原始指标](loadtest-online-cpu.json)、[内存原始指标](loadtest-online-memory.json)。这不支持持续资源饱和的判断，但分钟级采样无法排除短暂尖峰或事件循环阻塞。Firestore `(default)` 与 Cloud Run 均位于 `asia-northeast1`。

当前答题链路持有房间锁，等待 `save_room()` 的 Firestore 事务读取和提交完成，之后才发送 `answer_saved`。因此 11 人集中提交会串行等待多次持久化，这是尾延迟的候选原因，尚非线上分段计时确认的结论。尤其不能据此将基准局 4.62 秒的尖峰直接归因于 Firestore。

新增 `app/timing.py`，默认关闭。部署包含该代码的版本后，设置环境变量 `ROOM_TIMING_ENABLED=true`，运行一局同样的测试，并搜索日志中的 `room_command_timing`。完成诊断后设回 `false` 即可停止记录。本次未部署或修改线上变量。

每条 `answer` / `select_answer` 记录带独立 trace_id、room_id、operation、outcome，并包含以下耗时（毫秒）：

- `room_lock_wait_ms`：等待房间锁，含重试的累计值。
- `room_lock_hold_ms`：持锁时长，含持久化与失败回滚。
- `persistence_ms`：等待线程池中的 repository.save_room 完成，包含线程池排队、事务读写及内部重试，并非纯网络耗时。
- `mutation_ms`：游戏操作总耗时，包含锁等待、持久化及 CAS 重试。
- `ack_send_ms`：确认发送耗时，包含该 WebSocket 的发送锁等待；发送失败另记 `ack_send_failures`。
- `broadcast_ms`：随后向房间广播的总等待时长。
- `conflict_retries`：应用层 RoomConflictError 重试次数，缺省代表 0。
- `total_ms`：操作处理到广播结束的时间，包含确认之后的工作，不等于客户端确认 RTT，也不包含进入消息分支前的处理与网络传播。

各字段存在包含关系，不应全部相加。日志不含玩家名、player_id、session_id、题目、答案或异常详情。事件循环内每个命令使用独立 ContextVar，取消、失败和并发操作均保留原有异常与锁释放行为。

本地新增成功保存、失败回滚、并发隔离/取消、默认禁用等计时测试，全量结果 65 passed / 1 skipped（Docker 未运行，Firestore 模拟器集成测试跳过）。真实云端各段耗时仍需部署启用后采集。

## 修订 00016 线上复测

对 `majority-git-00016-bsd` 再次执行 12 人、12 题、批量重连场景。线上环境未配置 `ROOM_TIMING_ENABLED`，因此没有分段耗时；本次没有更改部署或环境变量。

第一轮房间 `K9A7` 收到全部 144 次答题确认，并恢复 6 条连接，但在最后一题的 QUESTION 阶段后发生一名客户端意外断线，未完成全员 FINISHED/复盘一致性断言。确认 P95 1001.22ms、P99 1086.72ms、最大 1159.49ms，重连到快照最大 781.57ms。该轮整体失败，详见 [复测报告](loadtest-online-retest-result.json)。失败运行未汇总完整阶段到达差，报告中的该指标 count=0 不表示没有收到状态。

对应时间段日志仅观察到一个实例和同一修订，开始时存在一次实例启动；未发现应用异常或测试中途重启，服务超时配置为 3600 秒。日志摘要见 [复测日志](loadtest-online-retest-audit.json)。随后 HTTP 查询该房间为 FINISHED，含 12 条复盘，见 [服务端状态](loadtest-online-retest-server-state.json)；这不能替代客户端最终同步检查。断线根因仍未确定，不将收尾阶段主动关闭产生的握手警告与这次意外断线混为一谈。

再次执行相同场景，房间 `RAKZ` 完成 12 题、144 次确认和 6 次重连，耗时 301.87 秒。答案、计分、复盘和全员 FINISHED 一致，没有意外断线；另有 3 条主动关闭握手警告。确认 P95 1184.28ms、P99 1273.02ms、最大 1298.63ms，仍未达到门槛；状态到达差 P95 6.02ms，恢复连接到快照最大 1004.92ms。见 [确认轮报告](loadtest-online-retest-confirm-result.json)。

确认轮日志只观察到 `majority-git-00016-bsd` 的一个实例，开局发生冷启动，没有应用错误、期间重启或计时日志，见 [确认轮日志](loadtest-online-retest-confirm-audit.json)。两轮都保留失败结论：第一轮存在意外断线且延迟超标，第二轮流程通过但延迟超标。本次没有调整线上配置，也没有因再次完成游戏而抹去首轮断线记录。

## 修订 00018 分段计时实测

`majority-git-00018-r4q` 保留 `ROOM_TIMING_ENABLED=true`。房间 `5FYV` 完成 12 题、144 次答题确认、6 次连接恢复，耗时 291.95 秒，答案、计分、全员最终复盘一致，无客户端错误或主动关闭警告。客户端确认 P95 1155.28ms、P99 1292.94ms，仍未达标；恢复连接到快照最大 933.81ms。见 [压测报告](loadtest-online-timed-result.json)。

取得该房间 276 条独立计时记录，包含 144 次 answer 和 132 次 select_answer，无失败 outcome、无应用层 CAS 重试。见 [原始计时](loadtest-online-timed-traces.json)、[汇总分析](loadtest-online-timed-analysis.json)。时间段内应用错误/关闭日志查询见 [日志检查](loadtest-online-timed-audit.json)。

| 正式答题阶段 | P50 | P95 | P99 |
| --- | ---: | ---: | ---: |
| 房间锁等待 | 438.24ms | 1022.15ms | 1152.99ms |
| 持久化（含线程池等待） | 93.40ms | 118.98ms | 124.09ms |
| 游戏操作总耗时 | 544.70ms | 1137.52ms | 1276.59ms |
| 确认发送（服务端） | 0.19ms | 0.30ms | 0.47ms |
| 后续广播 | 6.13ms | 15.80ms | 19.35ms |

这些分位数不能相加。作为同一请求证据，最慢的正式答题 mutation=1296.71ms，其中锁等待 1196.64ms、持锁 99.90ms（内含持久化 91.53ms）；确认发送 0.19ms。锁等待占该操作约 92.3%。据此可确认本轮尾延迟主要发生在房间锁排队，锁内逐次等待约 100ms 的持久化造成串行积累；不是确认消息发送本身慢。该结论不解释其他轮次的所有偶发网络尖峰。

后续优化应优先研究同房间短窗口合并答题持久化：同一批有效答案一次写入，成功后分别确认；需保留截止校验、confirmed 优先、CAS/失败回滚和亲阶段推进语义。不要通过先确认后异步保存来降低表面延迟。减少草稿重复写入可另行评估，但不能单独消除 11 次正式确认的串行写入。本次仅测量和定位，没有修改业务或线上配置；计时开关仍保持启用。
