# 卡片一键保存功能方案

## 概述

在分享二维码卡片上增加「保存图片」按钮，用户点击可将整张卡片（Logo + 标题 + 简介 + 二维码）保存为 PNG 图片，方便分享到微信/QQ/朋友圈。

---

## 方案一：html2canvas 截图保存（推荐）

### 原理

使用 [html2canvas](https://html2canvas.hertzen.com/) 库将 DOM 元素渲染为 Canvas，再导出为 PNG。

```
用户点击「保存图片」→ html2canvas 渲染 .qr-card 为 canvas
                                         ↓
                              canvas.toBlob() 生成 PNG
                                         ↓
                            创建 <a> 标签触发下载
```

### 技术选型

| 项 | 选择 |
|---|------|
| 库 | html2canvas（1.4.1，~32KB gzipped） |
| 加载方式 | 自托管 `site/js/html2canvas.min.js` |
| 触发方式 | 按钮点击 → 截取 → 下载 |

### 实现细节

1. **保存按钮位置**
   - 二维码下方，扫码提示文字下方
   - 样式：140px 宽，圆角按钮，带下载图标

2. **截图范围**
   - 目标：`.qr-card` 整个卡片元素
   - 含阴影、圆角、渐变文字

3. **下载文件命名**
   - `swufe-club-qr.png`

4. **兼容性**
   - html2canvas 支持所有现代浏览器
   - 支持 CSS 渐变、圆角、阴影
   - 注意：`background-clip: text` 渐变文字可能需额外配置（`useCORS: true`）

### 优缺点

| 优势 | 劣势 |
|------|------|
| 截取所见即所得，样式完全一致 | 增加 32KB 依赖 |
| 实现简单，约 15 行代码 | 截图对某些 CSS 属性有限制 |
| 交互自然，用户无感 | 渲染需 100-300ms，进度反馈 |

---

## 方案二：Canvas 手工绘制（零依赖）

### 原理

不使用任何库，用原生 Canvas API 重新绘制卡片内容。

```javascript
1. 创建 canvas（320×420px）
2. 绘制白色圆角矩形背景
3. 绘制 Logo 文字（渐变）
4. 绘制标题和简介文字
5. 遍历 QR 码表格 <td>，读取背景色
6. 在 canvas 上逐格绘制二维码
7. 绘制底部提示文字
8. canvas.toBlob() → 下载 PNG
```

### 优缺点

| 优势 | 劣势 |
|------|------|
| 零外部依赖 | 实现复杂（40+ 行） |
| 完全可控 | 样式不易与 CSS 完全一致 |
| 渲染速度快 | 需解析 QR 码表格 DOM |

---

## 方案三：SVG + foreignObject（无依赖）

### 原理

利用 SVG 的 `<foreignObject>` 嵌入 HTML，再通过 `<image>` 绘制到 Canvas：

```javascript
const svg = `
  <svg xmlns="http://www.w3.org/2000/svg" width="320" height="420">
    <foreignObject width="320" height="420">
      <div xmlns="http://www.w3.org/1999/xhtml">
        ...卡片 HTML...
      </div>
    </foreignObject>
  </svg>
`;
const blob = new Blob([svg], { type: 'image/svg+xml' });
const url = URL.createObjectURL(blob);
// 绘制到 canvas 后下载
```

### 优缺点

| 优势 | 劣势 |
|------|------|
| 零外部依赖 | `<foreignObject>` 在部分浏览器有渲染差异 |
| 保留完整 DOM 样式 | Blob URL 有跨域限制 |
| 实现较简单 | 不支持外部字体加载 |

---

## 推荐方案

**方案一（html2canvas）**。理由：
1. 所见即所得，卡片样式与截图完全一致
2. 开发成本最低，代码量最小
3. 库成熟稳定，支持所有 CSS 属性
4. 32KB 体积可接受

### 备选流程（若 html2canvas 未加载）

```
if (typeof html2canvas === 'undefined') {
  降级方案：提示用户使用系统截图
}
```

---

## 改动文件

| 文件 | 改动 |
|------|------|
| `site/index.html` | 二维码卡片底部添加「保存图片」按钮 + html2canvas CDN（fallback 自托管） |
| `site/css/style.css` | 保存按钮样式（~20 行） |
| `site/js/app.js` | 保存按钮点击事件：html2canvas 截图 → 下载 PNG（~20 行） |

---

## 预期交互

1. 点击分享 → 弹出二维码卡片
2. 点击「保存图片」 → 按钮变为「生成中...」
3. ~200ms → 浏览器自动下载 `swufe-club-qr.png`
4. 用户可直接发送图片到微信/QQ

---

请审核方案。
