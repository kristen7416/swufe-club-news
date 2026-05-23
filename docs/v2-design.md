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

## 4. 实施步骤

1. `extract_activity.py`: 添加联系方式提取 + 结束时间提取 + 北京时间 tz
2. `merge_data.py`: 修复北京时间 + contact 字段保留
3. `app.js`: 重构卡片渲染 + 详情弹窗增强
4. `style.css`: 卡片样式微调
5. 全链路测试: crawl → extract → merge → 前端验证
6. 提交推送
