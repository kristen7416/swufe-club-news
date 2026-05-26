/**
 * SWUFE 社团活动 - 发布活动表单逻辑
 */

(function () {
  'use strict';

  // ===== 发布 API 配置 =====
  // Cloudflare Worker URL（部署后替换为实际地址）
  // Vercel 备选: '/api/submit-activity'（国内可能不可达）
  var PUBLISH_API_URL = 'https://swufe-publish.swufe-news.workers.dev';

  var DOM = {};

  function cacheDom() {
    DOM.publishBtn = document.getElementById('publishBtn');
    DOM.publishOverlay = document.getElementById('publishOverlay');
    DOM.publishClose = document.getElementById('publishClose');
    DOM.publishCancel = document.getElementById('publishCancel');
    DOM.publishForm = document.getElementById('publishForm');
    DOM.clubSelect = document.getElementById('publishClub');
    DOM.articleUrl = document.getElementById('publishArticleUrl');
    DOM.title = document.getElementById('publishTitle');
    DOM.startTime = document.getElementById('publishStartTime');
    DOM.endTime = document.getElementById('publishEndTime');
    DOM.location = document.getElementById('publishLocation');
    DOM.contact = document.getElementById('publishContact');
    DOM.description = document.getElementById('publishDescription');
    DOM.submitBtn = document.getElementById('publishSubmit');
    DOM.statusMsg = document.getElementById('publishStatus');
  }

  function init() {
    cacheDom();
    if (!DOM.publishBtn) return; // element not found, skip
    loadClubs();
    bindEvents();
  }

  async function loadClubs() {
    try {
      const resp = await fetch('data/clubs.json');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      // only show clubs with wechat_name (can verify identity)
      const clubs = (data.clubs || []).filter(function (c) {
        return c.is_active !== false && c.wechat_name;
      });
      var html = '<option value="">请选择社团</option>';
      clubs.forEach(function (c) {
        html += '<option value="' + c.id + '">' + escapeHtml(c.name) + '</option>';
      });
      DOM.clubSelect.innerHTML = html;
    } catch (err) {
      console.error('加载社团列表失败:', err);
    }
  }

  function bindEvents() {
    DOM.publishBtn.addEventListener('click', openPublish);
    DOM.publishClose.addEventListener('click', closePublish);
    DOM.publishCancel.addEventListener('click', closePublish);
    DOM.publishOverlay.addEventListener('click', function (e) {
      if (e.target === e.currentTarget) closePublish();
    });
    DOM.publishForm.addEventListener('submit', handleSubmit);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && DOM.publishOverlay.classList.contains('open')) {
        closePublish();
      }
    });
  }

  function openPublish() {
    DOM.publishOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    setStatus('', '');
    // reset form
    DOM.publishForm.reset();
  }

  function closePublish() {
    DOM.publishOverlay.classList.remove('open');
    // only restore scroll if activity dialog is also not open
    if (!document.getElementById('activityDialog').classList.contains('open')) {
      document.body.style.overflow = '';
    }
  }

  function setStatus(msg, type) {
    DOM.statusMsg.textContent = msg;
    DOM.statusMsg.className = 'publish-status';
    if (type) DOM.statusMsg.classList.add('publish-status--' + type);
  }

  async function handleSubmit(e) {
    e.preventDefault();

    // --- validation ---
    var clubId = DOM.clubSelect.value;
    var articleUrl = DOM.articleUrl.value.trim();
    var title = DOM.title.value.trim();
    var startTime = DOM.startTime.value;
    var endTime = DOM.endTime.value;

    if (!clubId || !articleUrl || !title || !startTime) {
      setStatus('请填写必填字段', 'error');
      return;
    }

    if (articleUrl.indexOf('mp.weixin.qq.com') === -1) {
      setStatus('请填写有效的微信公众号文章链接（mp.weixin.qq.com）', 'error');
      return;
    }

    // --- submit ---
    DOM.submitBtn.disabled = true;
    DOM.submitBtn.textContent = '正在验证公众号身份...';
    setStatus('正在验证公众号身份，请稍候...', 'info');

    try {
      var resp = await fetch(PUBLISH_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          club_id: clubId,
          article_url: articleUrl,
          title: title,
          start_time: startTime ? new Date(startTime).toISOString() : '',
          end_time: endTime ? new Date(endTime).toISOString() : '',
          location: DOM.location.value.trim(),
          contact: DOM.contact.value.trim(),
          description: DOM.description.value.trim(),
        }),
      });

      var result = await resp.json();

      if (result.success) {
        setStatus('✅ 发布成功！活动将在 30-60 秒后上线', 'success');
        setTimeout(closePublish, 3000);
      } else {
        setStatus('❌ ' + (result.message || '发布失败，请重试'), 'error');
      }
    } catch (err) {
      console.error('发布失败:', err);
      // 检查是否是 Worker URL 未配置占位符
      if (PUBLISH_API_URL.indexOf('your-subdomain') !== -1) {
        setStatus('⚠️ 发布服务尚未配置，请联系管理员部署 Cloudflare Worker', 'error');
      } else {
        setStatus('❌ 网络错误，请稍后重试。如持续失败，请联系社团管理团队手动录入', 'error');
      }
    } finally {
      DOM.submitBtn.disabled = false;
      DOM.submitBtn.textContent = '提交发布';
    }
  }

  function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  document.addEventListener('DOMContentLoaded', init);
})();
