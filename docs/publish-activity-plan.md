# 方案：增加"发布活动"功能

> SWUFE 社团活动资讯平台 — 新增活动发布通道
> 2026-05-25

---

## 一、背景与目标

### 现状

- 平台目前**只读**：所有活动数据来自微信公众号爬虫
- 已有 `manual_activities.json`（人工提交通道），目前为空
- `merge_data.py` 已支持三源合并（爬虫 / 已有 / 人工），人工数据优先级最高

### 目标

增加**社团自主发布活动**的通道，使社团负责人可以直接在平台上发布活动信息，无需依赖微信公众号推文。

### 约束

1. 平台为**纯静态站点**（Vercel 香港 + GitHub Pages），无数据库
2. 无后端服务器
3. 发布的数据需进入现有 `merge_data.py → activities.json` 流水线
4. 需防滥用（验证身份 / 频率限制）

---

## 二、方案对比

### 方案一（当前实现）：Vercel API（已部署，中国不可达）

> 已实现但 `.vercel.app` 域名在国内被阻断。已被方案三替代。

### 方案三（推荐）：Cloudflare Worker + 前端发布表单

**架构**：

```
用户 → 前端发布表单 → Vercel Serverless API → GitHub API → manual_activities.json
                                                                    ↓
                                                          merge_data.py (下次爬取)
                                                                    ↓
                                                              activities.json
```

**流程**：
1. 前端增加"发布活动"入口（导航栏按钮）
2. 弹出发布表单：选择社团、填写公众号文章链接、标题、时间、地点等
3. 表单提交到 Vercel Serverless Function (`POST /api/submit-activity`)
4. Vercel Function 验证输入：
   - 爬取用户提交的公众号文章页，提取公众号名称
   - 与 `clubs.json` 中该社团的 `wechat_name` 比对
   - 匹配通过 → 写入 `manual_activities.json`；不匹配 → 拒绝
5. GitHub push 触发 Vercel 自动重新部署，约 30-60s 生效

**技术要点**：

| 项 | 方案 |
|------|------|
| Serverless Runtime | Vercel Python，与现有爬虫一致 |
| 身份认证 | **公众号文章链接验证**（用户提交链接 → 爬取 → 提取公众号名 → 匹配社团） |
| GitHub API | Fine-grained Token（仅 `contents:write`，限单仓库单文件） |
| 防滥用 | 公众号认证（天然防滥用）+ IP 频率限制 |
| 前端验证 | 选社团（从 clubs.json 加载）、文章链接必填、标题必填 |

**优点**：
- 用户体验好：填写公众号文章链接即可验证身份，无需额外邀请码
- 验证可靠：公众号名称是微信官方的，不可伪造
- 防滥用天然：每个提交对应一篇真实公众号文章，造假成本高
- 全自动化：发布后自动进入合并流水线，30-60s 上线
- 利用现有 Vercel 基础设施，不增加额外成本

**缺点**：
- 需要实现 Serverless Function（约 150 行 Python）
- 需要管理 GitHub Token
- 未配置 `wechat_name` 的社团无法使用此方式（需补全数据）
- Vercel 免费版函数有 10s 冷启动和 100s 执行限制（对验证+写入足够）

**工作量估算**：
- Vercel API 函数（含公众号名验证）：~150 行 Python
- 前端表单 UI + JS：~150 行 HTML/CSS + ~100 行 JS
- 总工作量：约 1 个工作日

### 方案二：GitHub Issue 模板 + Actions 自动化

**架构**：

```
用户 → 创建 GitHub Issue (模板) → Actions 检测新 Issue → 解析为 JSON → 创建 PR
                                                                              ↓
                                                                    合并 → manual_activities.json
                                                                              ↓
                                                                    merge_data.py → 部署
```

**流程**：
1. 创建 GitHub Issue 模板（.github/ISSUE_TEMPLATE/publish-activity.yml）
2. 用户填写模板：社团名、活动标题、时间、地点、联系方式等
3. GitHub Actions 监听 `issues:opened` 事件
4. Actions 脚本解析 Issue body → 追加到 `manual_activities.json` → 创建 Pull Request
5. 维护者审核 PR 后合并 → 触发部署

**优点**：
- 零额外基础设施：纯 GitHub 生态
- 天然审核机制（PR Review）
- 开源透明，所有提交可追溯
- Token 管理简单（GITHUB_TOKEN 自动可用）

**缺点**：
- 用户必须拥有 GitHub 账号，对非技术用户门槛高
- 发布流程繁琐（打开 GitHub → 创建 Issue → 填模板 → 等待审核）
- 不支持匿名/游客发布
- 无法在移动端便捷操作

**工作量估算**：
- Issue 模板 YAML：~30 行
- Actions 工作流：~40 行 YAML + ~50 行 Python 解析脚本
- 总工作量：约 0.5 个工作日

---

### 方案三：第三方表单 + 现有数据通道

**架构**：

```
用户 → Google Form / 腾讯文档 → Google Sheets
                                       ↓
                              sync_from_sheets.py (已有)
                                       ↓
                              manual_activities.json → merge → deploy
```

**流程**：
1. 创建一个 Google Form（或腾讯文档表单）
2. 用户填写表单提交活动信息
3. Google Sheets 自动收集提交数据
4. 管理员手动运行 `sync_from_sheets.py` 同步到 `manual_activities.json`
5. （可选）配置 GitHub Actions 定时同步

**优点**：
- 实现最简单：无需编码（表单工具已有）
- 不需要后端或 Token 管理
- 适合过渡期快速上线
- 手机友好（Google Form 自适应）

**缺点**：
- 用户跳出平台：需要跳转到外部表单
- 非实时：需要手动 / 定时同步
- 依赖第三方服务（Google 在国内可访问性不确定）
- 无法做到发布后立即在平台展示
- 表单数据与平台 UI 风格割裂

**工作量估算**：
- 配置表单：~30 分钟
- 同步脚本调整：~30 分钟
- 总工作量：约 1 小时

---

## 三、推荐方案：方案一（Vercel API）

### 为什么选方案一

1. **本项目已部署在 Vercel（香港节点）**，增加 Serverless Function 是自然延伸
2. 用户需求本质是**让社团能在平台上自主发布**，方案一体验最接近"发布"操作
3. `manual_activities.json` + `merge_data.py` 已准备好接收人工数据，只需把表单输出对接进去
4. Vercel Hobby 计划的免费额度（每月 100h 函数运行时间）对此场景足够

### 详细设计

#### 3.1 新增文件

```
api/submit-activity.py          # Vercel Serverless Function (Python)
site/publish.html               # 发布表单页面 (或嵌入为弹窗)
site/js/publish.js              # 发布表单逻辑
```

#### 3.2 Vercel API 设计

**端点**：`POST /api/submit-activity`

**请求体**：
```json
{
  "club_id": "club_022",
  "title": "洞察市场 智胜千里|CFA全球分析大赛校内选拔赛",
  "description": "比赛内容...",
  "location": "经世楼B101",
  "start_time": "2026-06-01T14:00:00+08:00",
  "end_time": "2026-06-01T16:00:00+08:00",
  "contact": "QQ群: 123456789",
  "article_url": "https://mp.weixin.qq.com/s/xxx"
}
```

**响应**：
```json
{
  "success": true,
  "message": "发布成功",
  "activity_id": "act_manual_001"
}
```

**验证逻辑**（按顺序）：
1. 验证必填字段（club_id, title, article_url, start_time）
2. 验证 club_id 存在于 clubs.json
3. 验证 article_url 格式（必须是 mp.weixin.qq.com 链接）
4. **公众号名称验证（核心）**：
   - 用 requests 抓取文章页面 HTML
   - 正则提取 `var nickname = "公众号名称"` 或 `var nickname = '公众号名称'`
   - 与 `clubs.json` 中该社团的 `wechat_name` 做模糊匹配
   - 匹配 → 通过 | 不匹配 → 拒绝并提示"公众号名称与所选社团不一致"
5. 验证时间格式和合理性
6. 频率限制（同 IP 每 10 分钟 1 次）

**GitHub API 写文件逻辑**：
1. 通过 GitHub API GET `contents/site/data/manual_activities.json` → 获取内容 + SHA
2. 追加新活动到 manual 列表
3. 通过 GitHub API GET `contents/site/data/activities.json` → 获取 content 段中的已有活动列表
4. **同步合并**：读取已有活动 + 所有 manual 活动（按 `article_url` 去重，manual 优先），用 `compute_status()` 重算状态
5. PUT 同时写回两个文件（同一 commit）
   - `site/data/manual_activities.json` — 追加新活动
   - `site/data/activities.json` — 合并后的完整数据
6. Commit message: `feat(manual): 新增活动 "${title}" by ${club_name}`

> **说明**：`compute_status()` 是纯日期逻辑（~50 行），已在 `merge_data.py` 中实现。Vercel API 中内嵌相同逻辑即可，无需额外依赖。

#### 3.3 前端设计

- 在导航栏增加"发布活动"按钮
- 点击后弹出全屏/弹窗表单（复用现有 dialog-overlay 样式）
- 表单字段：
  - **选择社团**（下拉框，从 `clubs.json` 加载，仅显示有 `wechat_name` 的社团）+ 搜索过滤
  - **公众号文章链接**（必填，用于身份验证，格式如 `https://mp.weixin.qq.com/s/...`）
  - **活动标题**（必填，50 字以内）
  - **活动分类**（自动填充，跟随所选社团）
  - **开始时间 / 结束时间**（日期时间选择器）
  - **地点**（文本输入，可选）
  - **参与方式**（文本输入，可选，如 QQ 群号）
  - **活动描述**（多行文本，可选，300 字以内）
- 提交后显示处理中（等待公众号验证），结果返回成功/失败
- 所有提交活动标记 `source: "manual"`，状态由 `compute_status()` 自动计算

#### 3.4 身份验证 / 防滥用

**方案：公众号文章链接认证**

核心逻辑：用户提交的 `article_url` 必须是其社团公众号的已发文章。Vercel API 验证流程：

1. **爬取文章页** — 用 `requests` 获取 `mp.weixin.qq.com/s/...` 页面 HTML
2. **提取公众号名** — 从页面 `<script>` 中正则匹配 `var nickname = "西财金投";`
3. **匹配验证** — 与 `clubs.json` 中该社团的 `wechat_name` 进行比较
   - 支持模糊匹配（忽略"西财"、"SWUFE"等前缀，子串匹配）
4. **结果** — 匹配 → 写入 | 不匹配 → 拒绝

**爬虫风险评估**：

| 维度 | 评估 |
|------|------|
| 接口类型 | 公开文章页面（非内部 API），无需 Cookie |
| 频率 | 每次提交仅爬取 1 篇 |
| 风控触发概率 | **极低** — 相当于正常用户打开链接 |
| 和主爬虫的区别 | 主爬虫调用 `cgi-bin/appmsgpublish`（需 Cookie，高频），本方案爬公开文章页（零 Cookie，低频）|

**防滥用措施**：

| 措施 | 实现 |
|------|------|
| **公众号认证（主要）** | 必须提供所属公众号的有效文章链接，造假成本高 |
| **IP 频率限制** | 同 IP 每 10 分钟 1 次（Vercel API 中计数） |
| **内容限制** | 标题 50 字、描述 300 字上限 |
| **链接去重** | 同 `article_url` 不可重复提交（比对已有 manual_activities.json） |

**对于未配置 `wechat_name` 的社团**：
- 表单下拉中不显示（仅显示有 `wechat_name` 的社团）
- 或降级为管理员手动审核（提交后标记 `status: "pending_review"`）

#### 3.5 Vercel 配置更新

```json
{
  "functions": {
    "api/submit-activity.py": {
      "maxDuration": 30,
      "memory": 256
    }
  }
}
```

#### 3.6 与现有流水线的整合

```
用户提交 → Vercel API → GitHub Commit (同时写入两个文件)
                              ├── manual_activities.json (追加)
                              └── activities.json (同步合并)
                                        ↓
                               Vercel 自动重新部署
                                        ↓
                              用户刷新页面可见 (~30-60s)
```

**合并逻辑**（Vercel API 内的同步合并）：
- 读取现有 `activities.json` 的活动列表
- 读取所有 `manual_activities.json` 的活动
- manual 数据按 `article_url` 覆盖已有数据（与 `merge_data.py` 相同策略）
- 用 `compute_status()` 重算每个活动的状态
- 写入 `activities.json` 供前端直接使用

**第二天爬虫运行时**：
- `merge_data.py` 再次合并（爬虫 + manual + 已有），manual 数据仍然优先
- 爬虫如果爬到了同一篇文章（同 `article_url`），`merge_data.py` 中 manual 的 `contact`/`location`/`description` 等字段会被保留（`enrich_fields` 逻辑）
- 不会丢失用户提交的补充信息

#### 3.7 安全考虑

| 风险 | 缓解措施 |
|------|----------|
| Token 泄露 | GitHub Fine-grained Token，仅限单仓库、单文件写入 |
| 恶意提交 | 公众号文章验证（必须提供真实公众号链接）+ IP 频率限制 |
| 假冒社团 | 公众号名称与 `clubs.json` 的 `wechat_name` 比对，微信官方名称不可伪造 |
| XSS | 前端和服务端双重 HTML 转义 |
| 批量爬取 | 每个提交需要真实公众号文章，无法自动化伪造 |
| Token 在 Vercel 泄露 | 使用 Vercel Environment Variables（加密存储） |

---

## 四、工作量与优先级

| 阶段 | 内容 | 预估工时 |
|------|------|----------|
| Phase 1 | Vercel API 函数（含公众号名称验证）+ 前端发布表单 | 1 天 |
| Phase 2 | 未配 `wechat_name` 社团的降级审核后台 | 0.5 天 |
| Phase 3 | 发布历史管理（我的发布、编辑、撤销） | 0.5 天 |

**建议**：先实施 Phase 1 上线基本发布能力，观察使用情况后再决定是否增加审核和管理功能。

---

## 五、备选讨论

### 公众号名称如何提取？

微信文章页面 HTML 中，公众号名称通常写在 `<script>` 标签内：
```javascript
var nickname = "西财金投";
```
直接用 `requests` + 正则表达式 `var nickname\s*=\s*["']([^"']+)["']` 提取即可。无需 Cookie，无需渲染 JS。

### 需要所有社团都配置 `wechat_name` 吗？

优先为已有爬虫配置的社团补充 `wechat_name`。当前 `clubs.json` 中 95 个社团约 30+ 个已有 `wechat_name`，可以逐步补充：

| 优先级 | 社团 | 现状 |
|--------|------|------|
| 高 | 已配置 `biz` 的爬虫社团 | 大部分已有 `wechat_name`，可以直接使用 |
| 中 | 已收录但无 `wechat_name` 的 | 手动补查公众号名称 |
| 低 | 无 `wechat_name` 的 | 表单中不显示，等待管理员补充后启用 |

### 数据可以即时展示吗？

**基本即时（30-60 秒）**。流程：
1. 用户提交 → Vercel API 处理 + GitHub API 写入（~2-5s）
2. GitHub push 触发 Vercel 自动重新部署（~20-40s）
3. CDN 缓存刷新（~10s）

刷新页面后新活动即可见。无需等待次日爬虫。Vercel API 同步合并 `activities.json` 确保前端文件已有新数据。

---

## 六、总结

| 维度 | 方案一 (Vercel API) | 方案二 (GitHub Issue) | 方案三 (第三方表单) |
|------|:---:|:---:|:---:|
| 用户体验 | ★★★★★ | ★★ | ★★★ |
| 实现难度 | ★★★ | ★★ | ★ |
| 维护成本 | ★★ | ★ | ★★★ |
| 安全性 | ★★★★ | ★★★★★ | ★★★ |
| 可扩展性 | ★★★★★ | ★★★ | ★ |
| **推荐度** | **推荐** | 备选 | 过渡方案 |
