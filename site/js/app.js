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
    DOM.loadMoreBtn = DOM.loadMore?.querySelector('.load-more-btn');
    DOM.dialogOverlay = document.getElementById('activityDialog');
    DOM.dialogTitle = document.getElementById('dialogTitle');
    DOM.dialogBody = document.getElementById('dialogBody');
    DOM.dialogFooter = document.getElementById('dialogFooter');
    DOM.dialogClose = document.getElementById('closeDialog');
    DOM.lastUpdated = document.getElementById('lastUpdated');
    DOM.shareBtn = document.getElementById('shareBtn');
    DOM.qrOverlay = document.getElementById('qrOverlay');
    DOM.qrClose = document.getElementById('qrClose');
    DOM.qrCode = document.getElementById('qrCode');
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

  function highlightCategory(category) {
    DOM.categoryNav?.querySelectorAll('.category-btn').forEach(el => {
      el.classList.toggle('active', el.dataset.category === category);
    });
  }

  function highlightStatus(status) {
    DOM.statusTabs?.querySelectorAll('.status-btn').forEach(el => {
      el.classList.toggle('active', el.dataset.status === status);
    });
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

      const clubsMap = {};
      for (const club of (clubResp.clubs || [])) {
        if (club.is_active !== false) {
          clubsMap[club.id] = club;
        }
      }
      STATE.clubs = clubsMap;

      if (actResp.last_updated && DOM.lastUpdated) {
        DOM.lastUpdated.textContent = formatTime(actResp.last_updated);
      }
    } catch (err) {
      console.error('数据加载失败:', err);
      DOM.loading.style.display = 'none';
      DOM.grid.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📭</div>
          <h3>数据加载失败</h3>
          <p>请刷新页面重试</p>
          <button onclick="location.reload()" style="margin-top:16px;padding:8px 24px;border-radius:8px;background:var(--swufe-blue);color:white;border:none;font-size:14px;font-weight:600;cursor:pointer">刷新</button>
        </div>`;
      return;
    }

    DOM.loading.style.display = 'none';

    // URL 参数
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

    if (params.get('id')) {
      const act = STATE.activities.find(a => a.id === params.get('id'));
      if (act) openDialog(act);
    }
  }

  // ===== 筛选逻辑 =====

  function applyFilters() {
    const { category, search, status } = STATE.filters;
    let result = [...STATE.activities];

    if (category !== 'all') {
      result = result.filter(a => a.category === category);
    }

    if (status !== 'all') {
      result = result.filter(a => a.status === status);
    }

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(a => {
        const matchTitle = a.title.toLowerCase().includes(q);
        const clubName = (STATE.clubs[a.club_id] || {}).name || '';
        const matchClub = clubName.toLowerCase().includes(q);
        return matchTitle || matchClub;
      });
    }

    // 排序：进行中 > 即将开始 > 已结束
    result.sort((a, b) => {
      const order = { ongoing: 0, upcoming: 1, ended: 2 };
      const diff = (order[a.status] || 99) - (order[b.status] || 99);
      if (diff !== 0) return diff;
      return (a.start_time || '').localeCompare(b.start_time || '');
    });

    STATE.filtered = result;
    STATE.displayCount = 20;

    // URL 更新
    const params = new URLSearchParams();
    if (category !== 'all') params.set('category', category);
    if (search) params.set('search', search);
    const newUrl = params.toString()
      ? `${location.pathname}?${params}`
      : location.pathname;
    history.replaceState(null, '', newUrl);
  }

  // ===== 渲染 =====

  function render() {
    const toShow = STATE.filtered.slice(0, STATE.displayCount);

    if (toShow.length === 0) {
      DOM.grid.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <h3>没有找到匹配的活动</h3>
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

      return `
        <article class="activity-card" data-id="${act.id}">
          <div class="card-header">
            <span class="status-badge status-${act.status}">${statusText}</span>
            <span class="card-club">
              <span class="club-dot">${clubName.charAt(0)}</span>
              ${escapeHtml(clubName)}
            </span>
          </div>
          <h3 class="card-title">${escapeHtml(act.title)}</h3>
          ${act.description ? `<p class="card-desc">${escapeHtml(truncate(act.description, 80))}</p>` : ''}
          <div class="card-info">
            ${timeStr ? `<div class="card-info-row"><span class="info-icon">🗓</span><span>${timeStr}</span></div>` : ''}
            ${act.location ? `<div class="card-info-row"><span class="info-icon">📍</span><span>${escapeHtml(act.location)}</span></div>` : ''}
            ${act.contact ? `<div class="card-info-row contact-row"><span class="info-icon">💬</span><span>${escapeHtml(act.contact)}</span></div>` : ''}
          </div>
          <div class="card-footer">
            ${act.article_url ? `<a href="${act.article_url}" target="_blank" rel="noopener" class="source-link">📄 原文</a>` : '<span></span>'}
            <button class="detail-btn" data-id="${act.id}">详情 →</button>
          </div>
        </article>
      `;
    }).join('');

    DOM.loadMore.style.display = STATE.displayCount >= STATE.filtered.length ? 'none' : 'block';
  }

  // ===== 事件绑定 =====

  function bindEvents() {
    // 分类点击
    DOM.categoryNav?.addEventListener('click', (e) => {
      const btn = e.target.closest('.category-btn');
      if (!btn) return;
      DOM.categoryNav.querySelectorAll('.category-btn').forEach(el => el.classList.remove('active'));
      btn.classList.add('active');
      STATE.filters.category = btn.dataset.category;
      applyFilters();
      render();
    });

    // 状态筛选
    DOM.statusTabs?.addEventListener('click', (e) => {
      const btn = e.target.closest('.status-btn');
      if (!btn) return;
      DOM.statusTabs.querySelectorAll('.status-btn').forEach(el => el.classList.remove('active'));
      btn.classList.add('active');
      STATE.filters.status = btn.dataset.status;
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

    // 点击卡片打开详情 (排除链接和按钮)
    DOM.grid?.addEventListener('click', (e) => {
      if (e.target.closest('a') || e.target.closest('button')) return;
      const card = e.target.closest('.activity-card');
      if (card) {
        const id = card.dataset.id;
        const act = STATE.activities.find(a => a.id === id);
        if (act) openDialog(act);
      }
    });

    // 详情按钮
    DOM.grid?.addEventListener('click', (e) => {
      const btn = e.target.closest('.detail-btn');
      if (!btn) return;
      const id = btn.dataset.id;
      const act = STATE.activities.find(a => a.id === id);
      if (act) openDialog(act);
    });

    // 弹窗关闭
    DOM.dialogClose?.addEventListener('click', closeDialog);
    DOM.dialogOverlay?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closeDialog();
    });
    // 弹窗底部按钮 (事件委托)
    DOM.dialogFooter?.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-secondary');
      if (btn) closeDialog();
    });

    // 分享
    DOM.shareBtn?.addEventListener('click', openShare);
    DOM.qrClose?.addEventListener('click', closeShare);
    DOM.qrOverlay?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closeShare();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (DOM.qrOverlay?.classList.contains('open')) closeShare();
        else if (DOM.dialogOverlay?.classList.contains('open')) closeDialog();
      }
    });
  }

  // ===== 弹窗 =====

  function openDialog(activity) {
    const club = STATE.clubs[activity.club_id] || {};
    const clubName = club.name || '未知社团';
    const statusText = getStatusText(activity.status);
    const timeStr = formatTimeRange(activity.start_time, activity.end_time);

    DOM.dialogTitle.textContent = activity.title;

    DOM.dialogBody.innerHTML = `
      <div class="dialog-club-info">
        <span class="status-badge status-${activity.status}">${statusText}</span>
        <span>${escapeHtml(clubName)}${activity.category ? ' · ' + activity.category : ''}</span>
      </div>

      ${timeStr ? `
        <hr class="dialog-divider">
        <p class="dialog-section-title">⏰ 时间</p>
        <p class="dialog-value">${timeStr}</p>
      ` : ''}

      ${activity.location ? `
        <hr class="dialog-divider">
        <p class="dialog-section-title">📍 地点</p>
        <p class="dialog-value">${escapeHtml(activity.location)}</p>
      ` : ''}

      ${activity.contact ? `
        <hr class="dialog-divider">
        <p class="dialog-section-title">💬 参与方式</p>
        <p class="dialog-value">${escapeHtml(activity.contact)}</p>
      ` : ''}

      ${activity.description ? `
        <hr class="dialog-divider">
        <p class="dialog-section-title">📝 活动介绍</p>
        <p class="dialog-value">${escapeHtml(activity.description)}</p>
      ` : ''}

      ${activity.cover_url ? `
        <hr class="dialog-divider">
        <p class="dialog-section-title">🖼 活动海报</p>
        <img src="${escapeHtml(activity.cover_url)}" alt="活动海报" loading="lazy">
      ` : ''}
    `;

    DOM.dialogFooter.innerHTML = `
      ${activity.article_url ? `<a href="${activity.article_url}" target="_blank" rel="noopener" class="btn-primary">📄 查看原文</a>` : ''}
      <button class="btn-secondary">关闭</button>
    `;

    DOM.dialogOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';

    const url = new URL(location);
    url.searchParams.set('id', activity.id);
    history.replaceState(null, '', url);
  }

  function closeDialog() {
    DOM.dialogOverlay.classList.remove('open');
    document.body.style.overflow = '';

    const url = new URL(location);
    url.searchParams.delete('id');
    history.replaceState(null, '', url);
  }

  // ===== 分享二维码 =====

  let qrInstance = null;

  function openShare() {
    if (typeof QRCode === 'undefined') {
      DOM.qrCode.innerHTML = '<p style="color:var(--text-muted);padding:80px 0">二维码库加载中，请稍后重试</p>';
      DOM.qrOverlay.classList.add('open');
      return;
    }

    if (!qrInstance) {
      qrInstance = new QRCode(DOM.qrCode, {
        text: new URL('/', window.location.href).href,
        width: 184,
        height: 184,
        colorDark: '#003D7A',
        colorLight: '#FFFFFF',
        correctLevel: QRCode.CorrectLevel.H,
      });
    }

    DOM.qrOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeShare() {
    DOM.qrOverlay.classList.remove('open');
    if (!DOM.dialogOverlay?.classList.contains('open')) {
      document.body.style.overflow = '';
    }
  }

  // ===== 顶部区域折叠 (25% → 15%) =====

  function initCollapse() {
    const topSection = document.getElementById('topSection');
    const cardsSection = document.getElementById('cardsSection');
    if (!topSection || !cardsSection) return;

    const threshold = 30;
    let compact = false;

    cardsSection.addEventListener('scroll', () => {
      const should = cardsSection.scrollTop > threshold;
      if (should !== compact) {
        compact = should;
        topSection.classList.toggle('compact', compact);
      }
    });

    // 滚到底部时展开
    cardsSection.addEventListener('scroll', () => {
      const { scrollTop, scrollHeight, clientHeight } = cardsSection;
      if (scrollTop + clientHeight >= scrollHeight - 10 && compact) {
        compact = false;
        topSection.classList.remove('compact');
      }
    });
  }

  // ===== 字体加载 =====

  function loadFonts() {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700&display=swap';
    link.onload = () => document.documentElement.classList.add('fonts-loaded');
    document.head.appendChild(link);
  }

  // ===== 启动 =====

  document.addEventListener('DOMContentLoaded', () => {
    cacheDom();
    loadFonts();
    initCollapse();
    loadData();
  });

})();
