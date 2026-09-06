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
