/**
 * SWUFE 社团活动 - 前端逻辑
 * 功能：数据加载、筛选、搜索、详情弹窗
 */

(function () {
  'use strict';

  // ===== 状态管理 =====
  const STATE = {
    activities: [],
    clubs: {},
    filtered: [],
    displayCount: 20,
    filters: {
      category: 'all',
      search: '',
      status: 'all',
    },
  };

  // ===== DOM 缓存 =====
  const DOM = {};

  function cacheDom() {
    DOM.loading = document.getElementById('loadingIndicator');
    DOM.grid = document.getElementById('activityGrid');
    DOM.searchInput = document.getElementById('searchInput');
    DOM.categoryNav = document.getElementById('categoryNav');
    DOM.statusTabs = document.getElementById('statusTabs');
    DOM.loadMore = document.getElementById('loadMore');
    DOM.loadMoreBtn = DOM.loadMore?.querySelector('button');
    DOM.dialog = document.getElementById('activityDialog');
    DOM.dialogTitle = document.getElementById('dialogTitle');
    DOM.dialogBody = document.getElementById('dialogBody');
    DOM.closeBtn = document.getElementById('closeDialog');
    DOM.lastUpdated = document.getElementById('lastUpdated');
  }

  // ===== 工具函数 =====

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function truncate(text, maxLen) {
    if (!text || text.length <= maxLen) return text || '';
    return text.slice(0, maxLen) + '...';
  }

  function formatTime(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    const month = d.getMonth() + 1;
    const day = d.getDate();
    const hour = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${month}月${day}日 ${hour}:${min}`;
  }

  function formatDate(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
  }

  function formatTimeRange(start, end) {
    if (!start) return '';
    const ds = new Date(start);
    if (isNaN(ds.getTime())) return start;
    const month = ds.getMonth() + 1;
    const day = ds.getDate();
    const hour = String(ds.getHours()).padStart(2, '0');
    const min = String(ds.getMinutes()).padStart(2, '0');
    if (!end) return `${month}月${day}日 ${hour}:${min}`;
    const de = new Date(end);
    if (isNaN(de.getTime())) return `${month}月${day}日 ${hour}:${min}`;
    const eh = String(de.getHours()).padStart(2, '0');
    const em = String(de.getMinutes()).padStart(2, '0');
    if (ds.toDateString() === de.toDateString()) {
      return `${month}月${day}日 ${hour}:${min} - ${eh}:${em}`;
    }
    const eMonth = de.getMonth() + 1;
    const eDay = de.getDate();
    return `${month}月${day}日 ${hour}:${min} - ${eMonth}月${eDay}日 ${eh}:${em}`;
  }

  function getStatusText(status) {
    const map = {
      upcoming: '即将开始',
      ongoing: '进行中',
      ended: '已结束',
    };
    return map[status] || status || '';
  }

  // ===== 数据加载 =====

  async function loadData() {
    DOM.loading.style.display = 'flex';

    try {
      const [actResp, clubResp] = await Promise.all([
        fetch('data/activities.json').then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        }),
        fetch('data/clubs.json').then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        }),
      ]);

      STATE.activities = actResp.activities || [];

      // 构建社团 Map
      const clubsMap = {};
      for (const club of (clubResp.clubs || [])) {
        if (club.is_active !== false) {
          clubsMap[club.id] = club;
        }
      }
      STATE.clubs = clubsMap;

      // 更新时间戳
      if (actResp.last_updated && DOM.lastUpdated) {
        DOM.lastUpdated.textContent = formatTime(actResp.last_updated);
      }

    } catch (err) {
      console.error('数据加载失败:', err);
      DOM.loading.style.display = 'none';
      DOM.grid.innerHTML = `
        <div class="empty-state">
          <p>😕 数据加载失败</p>
          <p>请刷新页面重试</p>
          <button onclick="location.reload()" class="secondary" style="margin-top:1rem">刷新</button>
        </div>`;
      return;
    }

    DOM.loading.style.display = 'none';

    // 读取 URL 参数
    const params = new URLSearchParams(location.search);
    if (params.get('category')) {
      const cat = params.get('category');
      STATE.filters.category = cat;
      highlightCategory(cat);
    }
    if (params.get('search')) {
      const q = params.get('search');
      STATE.filters.search = q;
      DOM.searchInput.value = q;
    }

    applyFilters();
    render();
    bindEvents();

    // 如果有 ?id=，打开对应详情
    if (params.get('id')) {
      const act = STATE.activities.find(a => a.id === params.get('id'));
      if (act) openDialog(act);
    }
  }

  // ===== 筛选逻辑 =====

  function applyFilters() {
    const { category, search, status } = STATE.filters;
    let result = [...STATE.activities];

    // 分类筛选
    if (category !== 'all') {
      result = result.filter(a => a.category === category);
    }

    // 状态筛选
    if (status !== 'all') {
      result = result.filter(a => a.status === status);
    }

    // 搜索
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(a => {
        const matchTitle = a.title.toLowerCase().includes(q);
        const clubName = (STATE.clubs[a.club_id] || {}).name || '';
        const matchClub = clubName.toLowerCase().includes(q);
        return matchTitle || matchClub;
      });
    }

    // 排序：进行中 > 即将开始 > 已结束，同状态下按开始时间升序
    result.sort((a, b) => {
      const order = { ongoing: 0, upcoming: 1, ended: 2 };
      const diff = (order[a.status] || 99) - (order[b.status] || 99);
      if (diff !== 0) return diff;
      return (a.start_time || '').localeCompare(b.start_time || '');
    });

    STATE.filtered = result;
    STATE.displayCount = 20;

    // 更新 URL
    const params = new URLSearchParams();
    if (category !== 'all') params.set('category', category);
    if (search) params.set('search', search);
    const newUrl = params.toString()
      ? `${location.pathname}?${params}`
      : location.pathname;
    history.replaceState(null, '', newUrl);
  }

  function highlightCategory(category) {
    DOM.categoryNav?.querySelectorAll('a').forEach(el => {
      el.classList.toggle('active', el.dataset.category === category);
    });
  }

  function highlightStatus(status) {
    DOM.statusTabs?.querySelectorAll('[data-status]').forEach(el => {
      el.classList.toggle('active', el.dataset.status === status);
    });
  }

  // ===== 渲染 =====

  function render() {
    const toShow = STATE.filtered.slice(0, STATE.displayCount);

    if (toShow.length === 0) {
      DOM.grid.innerHTML = `
        <div class="empty-state">
          <p>😕 没有找到匹配的活动</p>
          <p>试试其他筛选条件</p>
        </div>`;
      DOM.loadMore.style.display = 'none';
      return;
    }

    DOM.grid.innerHTML = toShow.map(act => {
      const club = STATE.clubs[act.club_id] || {};
      const clubName = club.name || '未知社团';
      const statusText = getStatusText(act.status);

      const timeStr = formatTimeRange(act.start_time, act.end_time);
      const dateStr = formatDate(act.start_time);

      return `
        <article class="activity-card" data-id="${act.id}">
          <span class="status-badge status-${act.status}">${statusText}</span>
          <h3 class="card-title">${escapeHtml(act.title)}</h3>
          <div class="card-meta">
            <span>🏛 ${escapeHtml(clubName)}</span>
          </div>
          ${timeStr ? `<div class="card-info-row"><span class="info-icon">🗓</span><span>${timeStr}</span></div>` : ''}
          ${act.location ? `<div class="card-info-row"><span class="info-icon">📍</span><span>${escapeHtml(act.location)}</span></div>` : ''}
          ${act.contact ? `<div class="card-info-row contact-row"><span class="info-icon">💬</span><span>${escapeHtml(act.contact)}</span></div>` : ''}
          ${act.description ? `<p class="card-desc">${escapeHtml(truncate(act.description, 80))}</p>` : ''}
          <div class="card-actions">
            ${act.article_url ? `<a href="${act.article_url}" target="_blank" rel="noopener" class="outline" onclick="event.stopPropagation()">📄 原文</a>` : '<span></span>'}
            <button class="detail-btn secondary" data-id="${act.id}" onclick="event.stopPropagation()">详情 →</button>
          </div>
        </article>
      `;
    }).join('');

    // 控制"加载更多"
    DOM.loadMore.style.display = STATE.displayCount >= STATE.filtered.length ? 'none' : 'block';
  }

  // ===== 事件绑定 =====

  function bindEvents() {
    // 分类点击 (事件委托)
    DOM.categoryNav?.addEventListener('click', (e) => {
      const link = e.target.closest('a[data-category]');
      if (!link) return;
      e.preventDefault();
      DOM.categoryNav.querySelectorAll('a').forEach(el => el.classList.remove('active'));
      link.classList.add('active');
      STATE.filters.category = link.dataset.category;
      applyFilters();
      render();
    });

    // 状态筛选 (事件委托)
    DOM.statusTabs?.addEventListener('click', (e) => {
      const span = e.target.closest('[data-status]');
      if (!span) return;
      DOM.statusTabs.querySelectorAll('[data-status]').forEach(el => el.classList.remove('active'));
      span.classList.add('active');
      STATE.filters.status = span.dataset.status;
      applyFilters();
      render();
    });

    // 搜索防抖
    let searchTimer;
    DOM.searchInput?.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        STATE.filters.search = DOM.searchInput.value;
        applyFilters();
        render();
      }, 300);
    });

    // 加载更多
    DOM.loadMoreBtn?.addEventListener('click', () => {
      STATE.displayCount += 20;
      render();
    });

    // 点击卡片打开详情 (事件委托)
    DOM.grid?.addEventListener('click', (e) => {
      // 如果点击的是链接或按钮，不处理
      if (e.target.closest('a') || e.target.closest('button')) return;
      const card = e.target.closest('.activity-card');
      if (card) {
        const id = card.dataset.id;
        const act = STATE.activities.find(a => a.id === id);
        if (act) openDialog(act);
      }
    });

    // 详情按钮点击
    DOM.grid?.addEventListener('click', (e) => {
      const btn = e.target.closest('.detail-btn');
      if (!btn) return;
      const id = btn.dataset.id;
      const act = STATE.activities.find(a => a.id === id);
      if (act) openDialog(act);
    });

    // 关闭弹窗
    DOM.closeBtn?.addEventListener('click', closeDialog);
    DOM.dialog?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closeDialog();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && DOM.dialog?.hasAttribute('open')) closeDialog();
    });
  }

  // ===== 弹窗 =====

  function openDialog(activity) {
    const club = STATE.clubs[activity.club_id] || {};
    const clubName = club.name || '未知社团';
    const statusText = getStatusText(activity.status);

    DOM.dialogTitle.textContent = activity.title;

    const timeStr = formatTimeRange(activity.start_time, activity.end_time);

    DOM.dialogBody.innerHTML = `
      <p><span class="status-badge status-${activity.status}">${statusText}</span></p>
      <p><strong>${escapeHtml(clubName)}</strong>${activity.category ? ' · ' + activity.category : ''}</p>

      ${timeStr ? `
        <p class="dialog-section-title">⏰ 时间</p>
        <p>${timeStr}</p>
      ` : ''}

      ${activity.location ? `
        <p class="dialog-section-title">📍 地点</p>
        <p>${escapeHtml(activity.location)}</p>
      ` : ''}

      ${activity.contact ? `
        <p class="dialog-section-title">💬 参与方式</p>
        <p>${escapeHtml(activity.contact)}</p>
      ` : ''}

      ${activity.description ? `
        <hr>
        <p class="dialog-section-title">📝 活动介绍</p>
        <p>${escapeHtml(activity.description)}</p>
      ` : ''}

      ${activity.cover_url ? `
        <hr>
        <p class="dialog-section-title">🖼 活动海报</p>
        <p><img src="${escapeHtml(activity.cover_url)}" alt="活动海报" style="max-width:100%;border-radius:0.5rem;" loading="lazy"></p>
      ` : ''}

      <hr>
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
        ${activity.article_url ? `<a href="${activity.article_url}" target="_blank" rel="noopener" class="contrast">📄 查看公众号原文</a>` : ''}
        <button class="secondary" onclick="document.getElementById('closeDialog').click()">关闭</button>
      </div>
    `;

    DOM.dialog.showModal();

    // 更新 URL
    const url = new URL(location);
    url.searchParams.set('id', activity.id);
    history.replaceState(null, '', url);
  }

  function closeDialog() {
    DOM.dialog.close();

    const url = new URL(location);
    url.searchParams.delete('id');
    history.replaceState(null, '', url);
  }

  // ===== 启动 =====

  document.addEventListener('DOMContentLoaded', () => {
    cacheDom();
    loadData();
  });

})();
