# Party Quiz Game

基于 Next.js、FastAPI 和 WebSocket 的实时聚会二选一答题 MVP。房间游戏状态保存在后端进程内存，题库当前以内置种子数据启动；这是专为单实例 Cloud Run 设计的取舍。

## 本地启动

1. 复制 `.env.example` 为 `.env`，并修改 `ADMIN_PASSWORD`。
2. 运行 `docker compose up --build`。
3. 打开 `http://localhost:3000/admin`，使用管理员密码登录，创建房间并展示二维码。

服务地址：前端 `http://localhost:3000`，后端 OpenAPI `http://localhost:8000/docs`。

## 当前 MVP 能力

- 管理员登录、创建房间、开始、锁题计分与下一题；
- 玩家姓名与本地 session 恢复；
- WebSocket 推送游戏状态、答题人数与结果；
- 服务端控制题目有效期；
- 多数派、少数派和固定答案三种独立计分策略；
- 每个房间使用 `asyncio.Lock` 串行化状态变更。

## Cloud Run 部署

前端和后端是两个 Cloud Run 服务。**后端必须保持单实例**，否则内存房间状态无法共享。

```bash
# 先部署 API；用实际的前端网址替换 CORS_ORIGINS
gcloud run deploy party-quiz-api --source ./backend --region asia-northeast1 \
  --allow-unauthenticated --max-instances 1 \
  --set-env-vars CORS_ORIGINS=https://YOUR_FRONTEND_URL \
  --set-secrets ADMIN_PASSWORD=party-quiz-admin-password:latest

# 前端 URL 需要在构建期注入。先通过 Cloud Build 传入 Docker build args，
# 再把已构建镜像部署到 Cloud Run。
gcloud builds submit ./frontend --config ./frontend/cloudbuild.yaml \
  --substitutions=_IMAGE=asia-northeast1-docker.pkg.dev/PROJECT/REPOSITORY/party-quiz-web,_API_URL=https://YOUR_API_URL,_WS_URL=wss://YOUR_API_URL
gcloud run deploy party-quiz-web --image asia-northeast1-docker.pkg.dev/PROJECT/REPOSITORY/party-quiz-web \
  --region asia-northeast1 --allow-unauthenticated

# 部署前端后，用实际前端 URL 收紧 API 的 CORS 白名单。
gcloud run services update party-quiz-api --region asia-northeast1 \
  --set-env-vars CORS_ORIGINS=https://YOUR_FRONTEND_URL
```

Cloud Run `--source` 会使用后端目录内的 Dockerfile。实际 API URL 在前端构建阶段注入，因此修改后需要重新构建、部署前端。建议另外配置 Cloud Run 的 IAM、预算告警和自定义域名。

## 后续接入 Firestore

游戏引擎没有依赖存储层。生产题库、配置及游戏历史可在 `backend/app/repository/` 中实现 Repository，再替换 `GameManager.questions/settings` 的加载与保存；不要将 `Room`、在线玩家或答题过程写入 Firestore。
