# マジョリティ

Local development uses Docker for the API and storage emulators, while Next.js runs directly on the host with hot reload. See [local storage setup](docs/local-firestore.md) for the data model and reset commands.

基于 Next.js、FastAPI 和 WebSocket 的实时聚会二选一答题 MVP。房间游戏状态保存在后端进程内存，题库当前以内置种子数据启动；这是专为单实例 Cloud Run 设计的取舍。

## 本地启动

1. 复制根目录的 `.env.example` 为 `.env`，并修改 `ADMIN_PASSWORD`。
2. 在项目根目录运行 `docker compose up --build`，启动后端和本地存储服务。
3. 另开一个终端，在 `frontend` 目录依次运行：

   ```powershell
   Copy-Item .env.local.example .env.local
   npm install
   npm run dev
   ```

4. 打开 `http://localhost:3000`。修改 `frontend` 下的代码后，页面会自动热更新。

服务地址：前端 `http://localhost:3000`，后端 OpenAPI `http://localhost:8000/docs`。

## 当前 MVP 能力

- 管理员登录、创建房间、开始、锁题计分与下一题；
- 玩家姓名与本地 session 恢复；
- WebSocket 推送游戏状态、答题人数与结果；
- 服务端控制题目有效期；
- 多数派、少数派和固定答案三种独立计分策略；
- 每个房间使用 `asyncio.Lock` 串行化状态变更。

## 部署：Vercel 前端 + Cloud Run API

前端由 Vercel 连接 GitHub 仓库并自动部署，API 部署到东京区域的 Cloud Run。API 的实时房间状态保存在进程内存中，因此 **API 必须限制为单实例**；Firestore 负责持久化题库、设置、用户资料和游戏历史，Cloud Storage 负责保存玩家头像。

### 部署前准备

- 安装并登录 Google Cloud CLI，选择项目 `majority-504900`；
- 在项目中启用 Cloud Run、Cloud Build、Artifact Registry、Firestore、Cloud Storage 和 Secret Manager；
- 在 `asia-northeast1`（东京）创建 Firestore `(default)` 数据库；数据库创建后不能修改区域；
- 使用现有的 `majority-main` Bucket，或按数据驻留要求另建东京 Bucket；
- 创建名为 `party-quiz-admin-password` 的 Secret；
- 为 API 使用的 Cloud Run 服务账号授予 `roles/datastore.user`、头像 Bucket 的 `roles/storage.objectAdmin`，以及该 Secret 的 `roles/secretmanager.secretAccessor`。
- 准备一个 Vercel 账号，并授权 Vercel GitHub App 访问 `orzbigbang/majority`。

现有 `majority-main` 位于 `US-WEST1`，可使用 Cloud Storage Always Free；Cloud Run 和 Firestore 则放在东京以降低日本用户的实时交互延迟。如果要求头像数据也驻留日本，应新建东京 Bucket 并替换下面的 `AVATAR_BUCKET`，但东京对象存储不在 Cloud Storage Always Free 区域内。

下面的命令从项目根目录执行。先替换变量值：

```bash
export PROJECT_ID="majority-504900"
export REGION="asia-northeast1"
export AVATAR_BUCKET="majority-main"

gcloud config set project "$PROJECT_ID"
```

### 1. 部署 API

第一次部署时前端 URL 尚未生成，先使用占位 CORS 地址：

```bash
gcloud run deploy party-quiz-api \
  --source ./backend \
  --region "$REGION" \
  --allow-unauthenticated \
  --min 0 \
  --max 1 \
  --cpu 1 \
  --memory 512Mi \
  --timeout 3600 \
  --set-env-vars "CORS_ORIGINS=https://placeholder.invalid,FIRESTORE_ENABLED=true,FIRESTORE_PROJECT_ID=$PROJECT_ID,AVATAR_STORAGE_ENABLED=true,AVATAR_BUCKET=$AVATAR_BUCKET,AVATAR_OBJECT_PREFIX=user-thumbnail,AVATAR_STYLE_VERSION=cute-animal-v1" \
  --set-secrets "ADMIN_PASSWORD=party-quiz-admin-password:latest"

export API_URL="$(gcloud run services describe party-quiz-api \
  --region "$REGION" --format='value(status.url)')"
export WS_URL="${API_URL/https:/wss:}"
```

### 2. 连接 GitHub 并部署到 Vercel

1. 在 Vercel Dashboard 选择 **Add New → Project**，导入 GitHub 仓库 `orzbigbang/majority`。
2. 配置项目：

   - Framework Preset：`Next.js`
   - Root Directory：`frontend`
   - Build Command：保留默认值 `npm run build`
   - Output Directory：不要手动覆盖，由 Next.js/Vercel 集成读取配置

3. 在 Vercel 项目的 **Settings → Environment Variables** 中，为 Production 和 Preview 环境设置：

   ```text
   NEXT_PUBLIC_API_URL=<上一步得到的 API_URL，例如 https://party-quiz-api-xxxxx-an.a.run.app>
   NEXT_PUBLIC_WS_URL=<同一地址将 https:// 替换为 wss://>
   NEXT_PUBLIC_AVATAR_STYLE_VERSION=cute-animal-v1
   ```

4. 点击 **Deploy**。首次部署完成后，记录 Vercel 的 Production URL，例如 `https://majority.vercel.app`。
5. 在 **Settings → Environments → Production → Branch Tracking** 确认 Production Branch 为 `master`。

此后推送到 `master` 会自动创建 Production Deployment；推送到其他分支或创建 Pull Request 会自动创建独立的 Preview Deployment。`NEXT_PUBLIC_*` 会在构建时写入浏览器代码，因此 API 地址变化后需要在 Vercel 更新变量并重新部署。

Next.js 开发和生产构建均使用默认的 `.next` 输出目录，Vercel 会通过 Next.js 集成处理该构建产物，无需提交该目录。

### 3. 收紧 API 的 CORS

Vercel 首次部署完成后，将 API 的占位地址替换为真实 Production URL。这里使用 `--update-env-vars`，以保留前面设置的 Firestore 和 Storage 环境变量：

```bash
export WEB_URL="https://YOUR_VERCEL_PRODUCTION_URL"

gcloud run services update party-quiz-api \
  --region "$REGION" \
  --update-env-vars "CORS_ORIGINS=$WEB_URL"
```

`CORS_ORIGINS` 支持用逗号分隔多个固定地址。如果某个 Preview Deployment 需要连接真实 API，应将其稳定的分支 URL 加入该变量；由于值本身含逗号，`gcloud` 命令需要改用其他分隔符：

```bash
export PREVIEW_URL="https://YOUR_STABLE_BRANCH_URL"
gcloud run services update party-quiz-api \
  --region "$REGION" \
  --update-env-vars "^@^CORS_ORIGINS=$WEB_URL,$PREVIEW_URL"
```

不要为了方便直接允许所有来源。最后打开 `$WEB_URL`，并确认 `$API_URL/health` 返回 `{"ok":true}`。

Vercel Git 自动部署与分支规则参见 [Vercel Git 部署文档](https://vercel.com/docs/git)；Cloud Run API 部署参见 [Google Cloud 源码部署文档](https://cloud.google.com/run/docs/deploying-source-code)。

## 数据与实例限制

Firestore Repository 位于 `backend/app/repository/`，用于题库、设置、用户资料和游戏历史。`Room`、在线玩家、管理员登录令牌和答题过程不会写入 Firestore；API 重启会清空正在进行的房间，因此生产环境必须保持单实例，并接受发布或实例重启会中断当前游戏这一 MVP 限制。
