/**
 * Cloudflare Worker — SWUFE 活动发布 API
 *
 * POST /  — 提交活动（公众号身份验证 + GitHub Content API 写入）
 * GET  /  — 诊断端点
 *
 * 环境变量 / Secrets:
 *   GITHUB_TOKEN  (secret) — 具有 repo/content write 权限的 PAT
 *   GITHUB_REPO   (var)    — "owner/repo"，默认 kristen7416/swufe-club-news
 */

// ===== 标题关键词 → 状态推断 =====
const STATUS_TITLE_HINTS = {
  ended: ['圆满结束', '圆满落幕', '圆满', '精彩回顾', '活动总结',
          '回顾', '落幕', '收官', '成功举办', '顺利举办',
          '顺利举行', '顺利结束', '顺利闭幕', '圆满完成'],
  upcoming: ['预告', '倒计时', '即将', '敬请期待', '抢鲜', '预热', '剧透', '通知', '报名'],
};

// ===== 微信 nickname 提取正则 =====
const NICKNAME_PATTERNS = [
  /var nickname\s*=\s*htmlDecode\(["']([^"']+)["']\)/,
  /var nickname\s*=\s*["']([^"']+)["']/,
  /var nick_name\s*=\s*["']([^"']+)["']/,
  /profile_nickname\s*=\s*["']([^"']+)["']/,
];

// ===== 工具函数 =====

function beijingNow() {
  const now = new Date();
  // 返回 ISO 字符串 with +08:00 offset
  const offset = 8 * 60;
  const local = new Date(now.getTime() + offset * 60 * 1000);
  return local.toISOString().replace('Z', '+08:00');
}

function beijingDate() {
  const now = new Date();
  const offset = 8 * 60;
  const local = new Date(now.getTime() + offset * 60 * 1000);
  const y = local.getFullYear();
  const m = String(local.getMonth() + 1).padStart(2, '0');
  const d = String(local.getDate()).padStart(2, '0');
  return `${y}${m}${d}`;
}

function randomHex(len) {
  const chars = '0123456789abcdef';
  let result = '';
  for (let i = 0; i < len; i++) {
    result += chars[Math.floor(Math.random() * 16)];
  }
  return result;
}

function base64Encode(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64Decode(str) {
  const binary = atob(str);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder().decode(bytes);
}

function jsonResponse(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

// ===== 公众号名称提取 =====

async function extractWechatName(articleUrl) {
  let html;
  try {
    const resp = await fetch(articleUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      },
      timeout: 15,
    });
    if (!resp.ok) {
      return [null, `文章页面返回错误 (HTTP ${resp.status})`];
    }
    html = await resp.text();
  } catch (err) {
    return [null, `无法访问文章页面 [${err.constructor.name}]: ${String(err).slice(0, 80)}`];
  }

  for (const pattern of NICKNAME_PATTERNS) {
    const m = html.match(pattern);
    if (m) {
      return [m[1].trim(), null];
    }
  }

  const debugLines = html.split('\n')
    .filter(l => l.toLowerCase().includes('nickname'))
    .slice(0, 5)
    .map(l => l.trim().slice(0, 150));
  return [null, `未找到公众号名称 (匹配行: ${debugLines.join(' | ')})`];
}

function matchWechatName(extracted, expected) {
  if (!extracted || !expected) return false;
  extracted = extracted.trim();
  expected = expected.trim();
  if (extracted === expected) return true;

  const prefixes = ['西财', 'SWUFE', '西南财大', '西南财经大学'];
  for (const p of prefixes) {
    if (expected.startsWith(p)) {
      const suffix = expected.slice(p.length);
      if (suffix && extracted.includes(suffix)) return true;
    }
    if (extracted.startsWith(p)) {
      const suffix = extracted.slice(p.length);
      if (suffix && expected.includes(suffix)) return true;
    }
  }
  if (extracted.length >= 2 && expected.length >= 2) {
    if (extracted.includes(expected) || expected.includes(extracted)) return true;
  }
  return false;
}

// ===== GitHub Content API =====

function ghHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github.v3+json',
  };
}

async function ghGet(token, repo, path) {
  const url = `https://api.github.com/repos/${repo}/contents/${path}`;
  const resp = await fetch(url, { headers: ghHeaders(token) });
  if (resp.status === 404) return [null, null];
  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`GitHub GET ${path} failed: ${resp.status} ${errText}`);
  }
  const data = await resp.json();
  const raw = base64Decode(data.content);
  return [JSON.parse(raw), data.sha];
}

async function ghPut(token, repo, path, content, sha, message) {
  const url = `https://api.github.com/repos/${repo}/contents/${path}`;
  const encoded = base64Encode(JSON.stringify(content, null, 2) + '\n');
  const body = { message, content: encoded };
  if (sha) body.sha = sha;
  const resp = await fetch(url, {
    method: 'PUT',
    headers: ghHeaders(token),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`GitHub PUT ${path} failed: ${resp.status} ${errText}`);
  }
  return resp.json();
}

// ===== 活动状态计算 =====

function computeStatus(act) {
  const now = new Date();
  const nowMs = now.getTime();
  const start = act.start_time ? new Date(act.start_time).getTime() : null;
  const end = act.end_time ? new Date(act.end_time).getTime() : null;

  if (end && end < nowMs) return 'ended';
  if (start && start <= nowMs) {
    if (!end || end > nowMs) {
      if (end === null && (nowMs - start) > 7 * 24 * 60 * 60 * 1000) return 'ended';
      return 'ongoing';
    }
    return 'ended';
  }
  if (start && start > nowMs) return 'upcoming';

  for (const [status, keywords] of Object.entries(STATUS_TITLE_HINTS)) {
    for (const kw of keywords) {
      if ((act.title || '').includes(kw)) return status;
    }
  }
  return 'upcoming';
}

// ===== 合并活动 =====

function mergeActivities(existing, manual) {
  const merged = new Map();
  for (const a of existing) {
    const k = a.article_url || a.id || '';
    if (k) merged.set(k, { ...a });
  }
  for (const a of manual) {
    const k = a.article_url || a.id || '';
    if (!k) continue;
    a.source = 'manual';
    a.status = computeStatus(a);
    merged.set(k, a);
  }
  const result = Array.from(merged.values());
  const order = { ongoing: 0, upcoming: 1, ended: 2 };
  result.sort((a, b) => {
    const diff = (order[a.status] ?? 99) - (order[b.status] ?? 99);
    if (diff !== 0) return diff;
    return (a.start_time || '').localeCompare(b.start_time || '');
  });
  return result;
}

// ===== 加载社团 =====

async function loadClubs(token, repo) {
  // Try GitHub API (primary: Worker has no local filesystem)
  try {
    const [data] = await ghGet(token, repo, 'site/data/clubs.json');
    if (data && Array.isArray(data.clubs)) return data.clubs;
  } catch { /* fallback to empty */ }
  return [];
}

// ===== 请求处理 =====

async function handlePOST(request, env) {
  const token = env.GITHUB_TOKEN;
  const repo = env.GITHUB_REPO || 'kristen7416/swufe-club-news';

  if (!token) {
    return jsonResponse(500, { success: false, message: '服务器配置错误（GITHUB_TOKEN 未设置）' });
  }

  // ---- parse body ----
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse(400, { success: false, message: '请求格式错误' });
  }

  // ---- validate ----
  const clubId = (body.club_id || '').trim();
  const articleUrl = (body.article_url || '').trim();
  const title = (body.title || '').trim();
  const startTime = (body.start_time || '').trim();

  if (!clubId || !articleUrl || !title || !startTime) {
    return jsonResponse(400, { success: false, message: '请填写必填字段' });
  }
  if (!articleUrl.includes('mp.weixin.qq.com')) {
    return jsonResponse(400, { success: false, message: '请填写有效的公众号文章链接' });
  }
  if (title.length > 100) {
    return jsonResponse(400, { success: false, message: '标题过长（最多100字）' });
  }

  // ---- club ----
  const clubs = await loadClubs(token, repo);
  const club = clubs.find(c => c.id === clubId);
  if (!club) {
    return jsonResponse(400, { success: false, message: '无效的社团' });
  }
  const expectedName = club.wechat_name;
  if (!expectedName) {
    return jsonResponse(400, { success: false, message: `社团 "${club.name}" 暂未配置公众号` });
  }

  // ---- verify wechat ----
  const [extractedName, err] = await extractWechatName(articleUrl);
  if (err) {
    return jsonResponse(400, { success: false, message: `公众号验证失败: ${err}` });
  }
  if (!matchWechatName(extractedName, expectedName)) {
    return jsonResponse(400, {
      success: false,
      message: `公众号不匹配：文章来自"${extractedName}"，社团"${club.name}"的公众号为"${expectedName}"`,
    });
  }

  // ---- build activity ----
  const nowIso = beijingNow();
  const activityId = `manual_${beijingDate()}_${randomHex(6)}`;
  const newAct = {
    id: activityId,
    club_id: clubId,
    title,
    description: (body.description || '').trim(),
    category: club.category || '其他',
    location: (body.location || '').trim(),
    start_time: startTime,
    end_time: (body.end_time || '').trim() || '',
    article_url: articleUrl,
    cover_url: '',
    publish_time: nowIso,
    contact: (body.contact || '').trim(),
    source: 'manual',
    status: 'upcoming',
    created_at: nowIso,
  };

  // ---- read GitHub ----
  let manualData, manualSha, actData, actSha;
  try {
    [manualData, manualSha] = await ghGet(token, repo, 'site/data/manual_activities.json');
    if (!manualData) manualData = { activities: [] };
    [actData, actSha] = await ghGet(token, repo, 'site/data/activities.json');
    if (!actData) actData = { activities: [] };
  } catch (e) {
    return jsonResponse(500, { success: false, message: `读取数据失败: ${e.message}` });
  }

  // ---- duplicate check ----
  const existingUrls = manualData.activities.map(a => a.article_url || '');
  if (existingUrls.includes(articleUrl)) {
    return jsonResponse(400, { success: false, message: '该文章链接已提交过' });
  }

  // ---- append & merge ----
  manualData.activities.push(newAct);
  const merged = mergeActivities(actData.activities || [], manualData.activities);
  const sc = { upcoming: 0, ongoing: 0, ended: 0 };
  for (const a of merged) {
    const s = a.status || 'upcoming';
    sc[s] = (sc[s] || 0) + 1;
  }
  const mergedOutput = {
    activities: merged,
    last_updated: nowIso,
    total_count: merged.length,
    status_counts: sc,
  };

  // ---- write ----
  const msg = `feat(manual): 新增活动 "${title}" by ${club.name}`;
  try {
    await ghPut(token, repo, 'site/data/manual_activities.json', manualData, manualSha, msg);
    // re-fetch sha for activities.json (race condition)
    const [, newSha] = await ghGet(token, repo, 'site/data/activities.json');
    await ghPut(token, repo, 'site/data/activities.json', mergedOutput, newSha || actSha, msg);
  } catch (e) {
    return jsonResponse(500, { success: false, message: `写入数据失败: ${e.message}` });
  }

  return jsonResponse(200, {
    success: true,
    message: '发布成功！活动将在 30-60 秒后上线',
    activity_id: activityId,
  });
}

function handleGET() {
  return jsonResponse(200, {
    status: 'alive',
    runtime: 'cloudflare-workers',
    version: '2026-05-26',
  });
}

// ===== 入口 =====

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // Health check
    if (url.pathname === '/health' || url.pathname === '/') {
      return handleGET();
    }

    // POST submit
    if (request.method === 'POST') {
      return handlePOST(request, env);
    }

    return jsonResponse(405, { success: false, message: 'Method not allowed' });
  },
};
