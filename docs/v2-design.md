# V2 设计文档 — 活动卡片优化与时区修复

## 1. 活动卡片信息密度提升

### 现状
- 卡片已显示社团名
- `contact` 字段始终为空
- 时间仅显示 `start_time`，无明确日期行
- 地点提取正则较简单

### 目标
卡片应一目了然包含：
- 活动时间（日期 + 时段，如 "5月25日 14:00-16:00"）
- 活动地点（如 "学生活动中心多功能厅"）
- 参与方式/联系方式（如 "QQ群: 915495134"）

### 数据层改动

#### `extract_activity.py` — 增强提取规则

**联系方式提取**（新增正则）：
```python
CONTACT_PATTERNS = [
    r"(?:QQ|QQ群|群号)[：:]\s*(\d{5,12})",
    r"(?:微信|微信号)[：:]\s*(\w+)",
    r"(?:电话|手机|联系电话)[：:]\s*(1\d{10})",
    r"(?:报名|报名方式|参与方式)[：:]\s*(.*?)(?:\n|$|。|；)",
    r"(?:邮箱|E[- ]?Mail)[：:]\s*([\w.@]+)",
]
```

**时间提取增强**：
- 添加 `end_time` 提取（当前仅提取 `start_time`）
- 支持 "14:00-16:00" 格式解析

#### `merge_data.py` — 保留 contact 字段
- 合并时确保 `contact` 字段被保留和传递

### 前端改动

#### `app.js` — 卡片渲染重构

卡片 HTML 结构改为：
```
┌──────────────────────────┐
│ [即将开始]                │
│ 活动标题                  │
│ ─────────────────────     │
│ 🗓 5月25日 14:00-16:00    │  ← 日期行（独立）
│ 📍 学生活动中心多功能厅    │  ← 地点行（独立）
│ 💬 QQ群: 915495134        │  ← 联系方式行（新增）
│ ─────────────────────     │
│ [原文]          [详情 →]  │
└──────────────────────────┘
```

- 当无数据时整行不显示（保持干净）
- 联系方式新增 emoji 前缀 `💬`

#### 详情弹窗增强
- 添加 "参与方式" 区块
- 添加 "活动海报" 区（如有 cover_url）
- 活动介绍支持多行文本

### CSS 微调
- 卡片增加最小高度，避免空字段导致布局跳跃
- 联系方式样式（背景高亮，边框）
- 时间地点行独立间距

---

## 2. 活动状态使用北京时间计算

### 问题
- `merge_data.py` 中 `compute_status` 使用 `datetime.now().astimezone()`
- GitHub Actions runner 时区为 UTC
- 举例：北京 23:00 结束的活动，UTC 15:01 就被标记为 "已结束"

### 修复方案

强制使用北京时间（UTC+8），不依赖系统时区：

```python
from datetime import timezone, datetime
import datetime as dt

BEIJING_TZ = timezone(dt.timedelta(hours=8))
now = datetime.now(BEIJING_TZ)
```

### 影响范围

| 文件 | 函数 | 改动 |
|------|------|------|
| `scripts/merge_data.py` | `compute_status()` | `now` 改为北京时间 |
| `scripts/extract_activity.py` | `compute_status()` | `now` 改为北京时间 |

### 验证方法
- 在本地模拟 UTC 环境运行 `merge_data.py`，检查状态标记是否按北京时间

---

## 3. 数据模型

活动对象格式（保持不变，仅填充现有字段）：

```json
{
  "id": "act_xxx",
  "club_id": "club_001",
  "title": "活动标题",
  "description": "活动描述",
  "category": "文化艺术",
  "location": "学生活动中心",
  "start_time": "2026-05-25T14:00:00+08:00",
  "end_time": "2026-05-25T16:00:00+08:00",
  "contact": "QQ群: 915495134",
  "article_url": "https://...",
  "cover_url": "https://...",
  "status": "upcoming"
}
```

---

## 4. DeepSeek AI 提取模式

### 4.1 概述

在现有的规则提取（正则）基础上，增加 AI 提取模式作为可选增强方案。AI 模式通过调用 DeepSeek API，从文章正文中直接提取结构化活动信息，包括标题、描述、地点、时间、联系方式、状态、分类。

AI 模式设计为规则模式的**互补和增强**，而非替代：
- AI 提取失败时自动降级到规则模式，不影响流水线
- AI 提取结果中缺失的字段用规则提取器补齐
- AI 模式通过 `CONFIG["mode"] = "ai"` 开启，默认仍为规则模式

### 4.2 配置方式

#### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（必填） | `""` |
| `DEEPSEEK_MODEL` | 模型名称（可选） | `"deepseek-chat"` |

#### CONFIG 扩展

```python
CONFIG = {
    # ... 现有配置 ...
    "mode": "rule",  # 改为 "ai" 启用 AI 模式
    "ai": {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "endpoint": "https://api.deepseek.com/chat/completions",
        "timeout": 30,
        "max_text_length": 3000,  # 发送给 AI 的最大字符数（成本控制）
        "retry_count": 1,
        "retry_delay": 3,
    }
}
```

### 4.3 AI 提取流程

```
extract_activity(article, club)
  │
  ├─ 抓取文章正文 HTML → 纯文本
  │
  ├─ mode == "rule" ?
  │     └─→ extract_activity_fallback()  ← 规则提取（现有逻辑）
  │
  ├─ mode == "ai" ?
  │     ├─→ extract_with_deepseek(title, text)
  │     │     ├─ 成功 → 返回结构化 dict
  │     │     └─ 失败 → 返回 {}，回退到规则模式
  │     └─→ 规则提取补齐缺失字段（location/contact/start_time）
  │
  └─→ _resolve_status()  ← 状态级联推断（time → title → default）
        ├─ 有 start_time/end_time → compute_status() 三状态判断
        ├─ 无时间数据 → infer_status_from_title() 标题关键词推断
        └─ 以上均无 → 默认 "upcoming"
```

### 4.4 Prompt 设计

#### System Prompt

```
你是一个专门从中文社团活动推文中提取结构化信息的助手。
请从给定的文章文本中提取活动信息，严格按照 JSON 格式返回。

提取规则：
1. title: 活动标题，清理多余空格和特殊字符，保持简洁
2. description: 活动描述，50-200字摘要
3. location: 活动地点，如明确提及则提取，否则为空字符串
4. start_time: 开始时间，ISO 8601 格式 YYYY-MM-DDTHH:MM:SS+08:00，使用北京时间
5. end_time: 结束时间，ISO 8601 格式 YYYY-MM-DDTHH:MM:SS+08:00，使用北京时间
6. contact: 联系方式（QQ群、微信群、电话、邮箱等），如 "QQ群: 123456" 或 "微信: abc123"
7. status: 活动状态，从文本推断："upcoming"（即将开始）, "ongoing"（进行中）, "ended"（已结束）
8. category: 活动分类，从以下选择：学术科技, 文化艺术, 体育竞技, 志愿服务, 创新创业, 其他

注意：
- 如果某字段无法从文本中提取，设为空字符串
- 时间必须使用北京时间时区 +08:00
- status 优先从文本中的时间描述推断，而非文章发布时间
- 只返回 JSON 对象，不要包含其他文字说明
```

#### User Prompt Template

```
请从以下社团活动文章中提取结构化信息：

标题：{title}

文章正文：
{text}

请返回 JSON 对象，包含：title, description, location, start_time, end_time, contact, status, category
```

#### 参数配置

- `temperature: 0.1` — 低温度确保输出稳定、可重复
- `max_tokens: 1024` — 足够的输出空间
- `response_format: {"type": "json_object"}` — DeepSeek 原生支持强制 JSON 输出

### 4.5 JSON Schema

#### 请求 Payload

```json
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "你是一个专门从..."},
    {"role": "user", "content": "请从以下社团活动文章中提取结构化信息：\n\n标题：{title}\n\n文章正文：\n{text}\n\n请返回 JSON 对象..."}
  ],
  "temperature": 0.1,
  "max_tokens": 1024,
  "response_format": {"type": "json_object"}
}
```

#### 响应解析

```json
{
  "choices": [{
    "message": {
      "content": "{\"title\": \"...\", \"description\": \"...\", \"location\": \"...\", \"start_time\": \"...\", \"end_time\": \"...\", \"contact\": \"...\", \"status\": \"...\", \"category\": \"...\"}"
    }
  }]
}
```

#### 内部结构（与现有数据模型一致）

```python
{
    "title": str,        # 清洗后的标题
    "description": str,  # 50-200 字摘要
    "location": str,     # 提取失败则为空
    "start_time": str,   # ISO 8601 +08:00 或空
    "end_time": str,     # ISO 8601 +08:00 或空
    "contact": str,      # 如 "QQ群: 123456789"
    "status": str,       # "upcoming" | "ongoing" | "ended"
    "category": str,     # 来自固定分类列表
}
```

### 4.6 错误处理与降级策略

分层降级，确保任何异常都不阻塞流水线：

| 层级 | 异常场景 | 处理方式 |
|------|----------|----------|
| L1 | 未配置 API key | 打印警告，返回 {}，降级到规则模式 |
| L2 | 网络超时/连接异常 | 重试 1 次后返回 {}，降级到规则模式 |
| L3 | HTTP 4xx/5xx | 重试 1 次后返回 {}，降级到规则模式 |
| L4 | 响应 JSON 解析失败 | 捕获异常，返回 {}，降级到规则模式 |
| L5 | AI 返回但部分字段缺失 | 用规则提取器补齐缺失字段（混合模式） |

#### 成本控制

- 正文截断至 3000 字符后才发送给 API
- 每篇文章约消耗 1000 tokens
- 每次运行 50 篇文章 ≈ 50K tokens ≈ 0.007 元（DeepSeek 定价 ~0.14 元/百万 tokens）
- `retry_count: 1` 限制重试次数，避免异常重复消费

### 4.7 标题关键词状态推断

#### 问题

当前状态完全依赖 `start_time` / `end_time` 的时间比较。当时间字段为空时，活动默认标记为 "upcoming"。但标题本身包含语义线索 — "XX活动圆满结束" 显然应该是 "ended"。

#### 方案

在时间推断无法得出结果时，降级到标题关键词匹配：

```python
STATUS_TITLE_HINTS = {
    "ended": ["圆满结束", "精彩回顾", "活动总结", "回顾", "落幕",
              "收官", "成功举办", "圆满落幕"],
    "upcoming": ["预告", "倒计时", "即将", "敬请期待",
                 "抢鲜", "预热", "剧透", "通知"],
}
```

#### 状态推断总入口 `_resolve_status()`：

```
compute_status(start_time, end_time)
  → 有准确时间? → 返回三状态结果
  → 无时间数据? → infer_status_from_title(title)
    → 标题匹配 ended 关键词? → "ended"
    → 标题匹配 upcoming 关键词? → "upcoming"
    → 均不匹配 → "upcoming"
```

此逻辑适用于**规则模式**和 **AI 模式**，对所有活动生效。

### 4.8 新增/修改函数清单

| 函数 | 位置 | 说明 |
|------|------|------|
| `compute_status(start_time, end_time="")` | `extract_activity.py` | 升级为三状态（复制 merge_data.py 逻辑） |
| `infer_status_from_title(title)` | `extract_activity.py` | 新增，标题关键词 → 状态 |
| `_resolve_status(extracted, title)` | `extract_activity.py` | 新增，状态推断总入口 |
| `extract_with_deepseek(title, text)` | `extract_activity.py` | 新增，DeepSeek API 调用 |
| `extract_activity_fallback()` | `extract_activity.py` | 修改，增加 AI/rule 双模式派发 |

---

## 5. 实施步骤

### 第一阶段：提取增强（规则 + AI）

1. `extract_activity.py`: 添加联系方式提取 + 结束时间提取 + 北京时间 tz ✅（V1 已完成）
2. `merge_data.py`: 修复北京时间 + contact 字段保留 ✅（V1 已完成）
3. `extract_activity.py`: 升级 `compute_status()` 为三状态（复制 merge_data 逻辑）
4. `extract_activity.py`: 新增 `infer_status_from_title()` 和 `_resolve_status()` — 标题状态推断
5. `extract_activity.py`: 扩展 CONFIG 添加 ai 子配置
6. `extract_activity.py`: 新增 DeepSeek API 调用函数 + prompt 模板
7. `extract_activity.py`: `extract_activity_fallback()` 增加 AI 模式派发
8. `.github/workflows/crawl-and-deploy.yml`: 添加 `DEEPSEEK_API_KEY` 环境变量

### 第二阶段：前端展示

9. `app.js`: 重构卡片渲染 + 详情弹窗增强（已完成设计，见第 1 节）
10. `style.css`: 卡片样式微调（已完成设计，见第 1 节）

### 第三阶段：验证

11. 规则模式回归测试：`python extract_activity.py`（默认行为不变）
12. AI 模式测试：设置 `DEEPSEEK_API_KEY` + `mode=ai` 运行
13. 全链路测试：crawl → extract (rule/ai) → merge → 前端验证
14. 提交推送
