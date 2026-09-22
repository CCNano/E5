# Microsoft 365 Scheduled Activity Runner

基于 GitHub Actions 与 Microsoft Graph API 的定时任务工具：每日在随机时间点、以随机任务组合向 Microsoft 365 租户产生轻量 API 活动（邮件、日历、OneDrive、联系人），并通过独立任务每日自动轮换运行时间与任务类型。

> 免责声明：使用本项目前请自行评估并遵守 Microsoft 服务条款及 Microsoft 365 开发者计划相关政策，由此产生的账号风险由使用者自行承担。

## 文件结构

```
.
├── daily_runner.py                  # 主任务脚本：认证 + 随机调用 Graph API
├── sync_config.py                   # 配置轮换脚本：每日随机化 cron 与任务池
├── config.json                      # 当前启用的任务池（由 Config Sync 每日更新）
├── requirements.txt                 # Python 依赖（仅 requests）
└── .github/workflows/
    ├── daily-tasks.yml              # Daily Tasks：每日两次，时间随机
    └── config-sync.yml              # Config Sync：每日 UTC 16:00 轮换配置
```

## 工作原理

1. **Config Sync**（每日 UTC 16:00）：运行 `sync_config.py`，随机重写 `daily-tasks.yml` 中的两条 cron（UTC 1-11、12-22 区间各取一个随机时间），并从 6 种任务类型中随机挑选 4-6 种写入 `config.json`，随后自动 commit/push 回仓库。
2. **Daily Tasks**（每日两次，时间由上一步指定）：运行 `daily_runner.py`，使用 OAuth2 client credentials flow 获取 token，从 `config.json` 任务池中随机选择任务执行。

> schedule 触发的 workflow 总是读取默认分支上的最新文件，因此轮换结果从次日起生效。

## 部署步骤

### 1. Azure AD 应用注册

1. 登录 [Microsoft Entra 管理中心](https://entra.microsoft.com)，进入 **App registrations → New registration**，名称任意，账户类型选择"仅此组织"，重定向 URI 留空。
2. 注册后记录 **Application (client) ID** 与 **Directory (tenant) ID**。
3. 进入 **API permissions → Add a permission → Microsoft Graph → Application permissions**，勾选以下 5 项，然后点击 **Grant admin consent**（管理员同意）：

   | 权限 | 用途 |
   |---|---|
   | `Mail.Send` | 发送邮件 |
   | `Mail.ReadWrite` | 创建邮件草稿 |
   | `Calendars.ReadWrite` | 创建日历事件 |
   | `Files.ReadWrite.All` | OneDrive 上传/清理 |
   | `Contacts.ReadWrite` | 创建联系人 |

4. 进入 **Certificates & secrets → New client secret**，记录生成的 **Value**（仅显示一次）。
5. 确认目标用户 UPN（Entra 管理中心 → Users），建议至少 2 个（用于互发邮件）。

### 2. 配置 GitHub Secrets

在仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 说明 | 示例 |
|---|---|---|
| `TENANT_ID` | 租户 ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `CLIENT_ID` | 应用 (客户端) ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `CLIENT_SECRET` | 应用密钥 Value | `xxxxxxxxxxxxxxxxxxxxxxxx` |
| `TARGET_USERS` | 目标用户 UPN，逗号分隔 | `a@contoso.onmicrosoft.com,b@contoso.onmicrosoft.com` |

### 3. 启用 Actions

push 到 GitHub 后 Actions 默认可用；两个 workflow 均支持 **workflow_dispatch** 手动触发，建议先手动运行一次 Daily Tasks 验证配置。

## 任务类型

| 任务名 | Graph API | 说明 |
|---|---|---|
| `send_mail` | `POST /users/{u}/sendMail` | 发送全随机内容的邮件 |
| `draft_mail` | `POST /users/{u}/messages` | 创建邮件草稿（不发送） |
| `create_event` | `POST /users/{u}/events` | 创建随机日历事件 |
| `onedrive_upload` | `PUT /users/{u}/drive/root:/daily-sync/{f}:/content` | 上传随机文件到自建目录 |
| `onedrive_cleanup` | `GET/DELETE /users/{u}/drive/...` | 仅清理 `/daily-sync/` 目录内文件 |
| `create_contact` | `POST /users/{u}/contacts` | 创建随机姓名联系人 |

所有任务只产生自建内容，不读取、转发或修改任何已有邮件/文件等真实用户数据。

## 本地运行

```powershell
# PowerShell
$env:TENANT_ID = "<租户ID>"
$env:CLIENT_ID = "<客户端ID>"
$env:CLIENT_SECRET = "<密钥>"
$env:TARGET_USERS = "a@contoso.onmicrosoft.com,b@contoso.onmicrosoft.com"
pip install -r requirements.txt
python daily_runner.py      # 执行任务
python sync_config.py       # 本地预览配置轮换（会修改 yml 与 config.json）
```

```bash
# Bash
export TENANT_ID="<租户ID>" CLIENT_ID="<客户端ID>" CLIENT_SECRET="<密钥>"
export TARGET_USERS="a@contoso.onmicrosoft.com,b@contoso.onmicrosoft.com"
pip install -r requirements.txt && python daily_runner.py
```

## 自定义

- **任务池/权重**：修改 `sync_config.py` 中的 `SAFE_TASKS` 与 `daily_runner.py` 中的 `TASKS`/`TASK_WEIGHTS`（新增任务需同步三处）。
- **时间区间**：修改 `sync_config.py` 中 `rand_cron(1, 11)` / `rand_cron(12, 22)` 的区间。
- **OneDrive 目录**：`daily_runner.py` 中 `daily-sync/` 字样（上传与清理两处需一致）。

## 隐私与安全设计

- 凭据全部走 GitHub Secrets，仓库与日志中无任何密钥/UPN；
- 日志统一脱敏（UPN → `userN`），不打印 API 响应体；
- 无状态、无持久化，token 仅存在于单次运行内存中；
- Config Sync 使用 GITHUB_TOKEN 提交，不会触发 workflow 递归。

## 常见问题

- **schedule 运行有延迟**：GitHub Actions 定时任务存在数分钟级漂移，属正常现象。
- **public 仓库 60 天无活动 schedule 被停用**：本仓库每日有 bot commit，天然保持活跃；也可手动 workflow_dispatch 兜底。
- **401/403 错误**：检查权限是否已管理员同意、密钥是否过期、`TARGET_USERS` 中的 UPN 是否存在于该租户。
- **429 限流**：脚本已内置指数退避重试，多次失败可检查任务权重是否设置过大。