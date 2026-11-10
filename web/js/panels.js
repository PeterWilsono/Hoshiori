// ===== 交互面板 - 搜索 / 她今天 / 编辑重发 / 主动消息 =====
//
// 这一层补的是"操作完之后你不知道成没成"的那部分：
// - 全库搜索（Ctrl+F），点结果直接跳到那句话并高亮
// - 她今天：她不在你面前的时候在做什么
// - 改一下重发：真的替换，不是叠一条
// - 她先开口的那条，抬头长得跟回你的不一样

(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);

    /* ==========================================================
       一、反馈动效的小工具
       ========================================================== */

    function pulse(el, cls, ms) {
        if (!el) return;
        el.classList.add(cls);
        setTimeout(() => el.classList.remove(cls), ms);
    }

    /** 发送按钮：转圈 */
    function markSending() {
        const btn = $('sendBtn');
        if (!btn) return;
        btn.classList.remove('is-sent', 'is-failed');
        btn.classList.add('is-sending');
        btn.setAttribute('aria-label', '正在发送');
    }

    /** 发送按钮：打勾 600ms 再复位 */
    function markSent() {
        const btn = $('sendBtn');
        if (!btn) return;
        btn.classList.remove('is-sending');
        btn.classList.add('is-sent');
        setTimeout(() => btn.classList.remove('is-sent'), 700);
    }

    /** 发送按钮：抖一下 */
    function markFailed() {
        const btn = $('sendBtn');
        if (!btn) return;
        btn.classList.remove('is-sending');
        btn.classList.add('is-failed');
        setTimeout(() => btn.classList.remove('is-failed'), 900);
    }

    /** 让某个按钮进入"正在处理"，结束后恢复 */
    function withBusy(btn, task) {
        if (!btn) return task();
        btn.classList.add('is-busy');
        return Promise.resolve(task()).finally(() => btn.classList.remove('is-busy'));
    }

    /* ==========================================================
       二、全库搜索
       ========================================================== */

    let searchTimer = null;
    let searchHits = [];
    let searchCursor = -1;
    let lastSearched = null;

    function openSearch() {
        const overlay = $('searchOverlay');
        if (!overlay) return;
        overlay.hidden = false;
        overlay.classList.remove('is-closing');

        const input = $('searchInput');
        if (input) {
            input.value = '';
            input.focus({ preventScroll: true });
        }
        searchHits = [];
        searchCursor = -1;
        lastSearched = null;
        renderSearchHint('输入两个字以上开始搜。可以搜任何一段对话里说过的话。');
        const count = $('searchCount');
        if (count) count.textContent = '共 0 条';
    }

    function closeSearch() {
        const overlay = $('searchOverlay');
        if (!overlay || overlay.hidden) return;
        overlay.classList.add('is-closing');
        setTimeout(() => {
            overlay.hidden = true;
            overlay.classList.remove('is-closing');
        }, 180);
    }

    function renderSearchHint(text) {
        const box = $('searchResults');
        if (box) box.innerHTML = `<p class="search-hint">${escapeHtml(text)}</p>`;
    }

    function highlightSnippet(text, q) {
        const safe = escapeHtml(text || '');
        if (!q) return safe;
        const idx = safe.toLowerCase().indexOf(q.toLowerCase());
        if (idx < 0) return safe;
        return safe.slice(0, idx) +
            '<mark>' + safe.slice(idx, idx + q.length) + '</mark>' +
            safe.slice(idx + q.length);
    }

    async function runSearch(q) {
        const box = $('searchResults');
        const count = $('searchCount');
        if (!box) return;

        if (!q || q.length < 1) {
            searchHits = [];
            renderSearchHint('输入两个字以上开始搜。可以搜任何一段对话里说过的话。');
            if (count) count.textContent = '共 0 条';
            return;
        }

        let hits = [];
        try {
            hits = await eel.search_messages(q, 40)() || [];
        } catch (e) {
            console.error('搜索失败:', e);
            renderSearchHint('搜索出错了，再试一次。');
            return;
        }

        searchHits = hits;
        searchCursor = hits.length ? 0 : -1;

        if (count) {
            count.textContent = hits.length ? `共 ${hits.length} 条` : '没有找到';
        }

        if (!hits.length) {
            renderSearchHint(`所有对话里都没有「${q}」。换个说法试试？`);
            return;
        }

        box.innerHTML = hits.map((h, i) => `
            <button class="search-hit${i === 0 ? ' is-active' : ''}" type="button" data-i="${i}">
                <div class="search-hit__top">
                    <span class="search-hit__who">${h.role === 'user' ? '你' : '星织'}</span>
                    <span class="search-hit__dot">·</span>
                    <span class="search-hit__conv">${escapeHtml(h.conv_title || '未命名对话')}</span>
                    <span class="search-hit__dot">·</span>
                    <span>${escapeHtml(h.day || '')} ${escapeHtml(h.clock || '')}</span>
                </div>
                <div class="search-hit__text">${highlightSnippet(h.snippet, q)}</div>
            </button>
        `).join('');

        box.querySelectorAll('.search-hit').forEach(el => {
            el.addEventListener('click', () => jumpToHit(Number(el.dataset.i)));
        });
    }

    function moveCursor(delta) {
        if (!searchHits.length) return;
        searchCursor = (searchCursor + delta + searchHits.length) % searchHits.length;
        const box = $('searchResults');
        box.querySelectorAll('.search-hit').forEach((el, i) => {
            el.classList.toggle('is-active', i === searchCursor);
            if (i === searchCursor) el.scrollIntoView({ block: 'nearest' });
        });
    }

    async function jumpToHit(i) {
        const hit = searchHits[i];
        if (!hit) return;
        closeSearch();

        try {
            const cur = await eel.get_current_conversation()();
            const curId = cur && (cur.id ?? cur.conv_id);
            if (String(curId) !== String(hit.conv_id)) {
                await eel.load_conversation_from_web(hit.conv_id)();
                await loadCurrentConversation();
            }
            await flashMessage(hit.id);
        } catch (e) {
            console.error('跳转失败:', e);
            if (typeof showNotification === 'function') {
                showNotification('跳过去的时候出了点问题', 'error');
            }
        }
    }

    /** 滚到某条消息并让它亮一下 */
    async function flashMessage(msgId) {
        const box = $('chatMessages');
        if (!box) return;
        // 消息可能还在渲染，给一帧时间
        await new Promise(r => setTimeout(r, 60));

        let node = box.querySelector(`[data-msg-id="${msgId}"]`);
        if (!node) {
            // 是被拆成多泡的那一轮，id 挂在第一个泡上；还被折叠就先滚到底
            scrollToBottom(false);
            await new Promise(r => setTimeout(r, 120));
            node = box.querySelector(`[data-msg-id="${msgId}"]`);
        }
        if (!node) return;

        node.scrollIntoView({ block: 'center', behavior: 'smooth' });
        pulse(node, 'is-flash', 1600);
    }

    function initSearch() {
        const overlay = $('searchOverlay');
        const input = $('searchInput');
        if (!overlay || !input) return;

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeSearch();
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                moveCursor(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                moveCursor(-1);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (searchCursor >= 0) jumpToHit(searchCursor);
            }
        });

        // 不靠 input 事件：WebView2 里粘贴/输入法上屏有时不发 input，
        // 结果就是"字进去了但没搜"。这里盯着 value 自己变，稳得多。
        let lastSeen = null;
        let settleAt = 0;
        setInterval(() => {
            if (overlay.hidden) {
                lastSeen = null;
                return;
            }
            const q = (input.value || '').trim();
            if (q !== lastSeen) {
                lastSeen = q;
                settleAt = Date.now() + 220;
                return;
            }
            if (lastSeen === lastSearched) return;
            if (Date.now() < settleAt) return;
            lastSearched = lastSeen;
            runSearch(lastSeen);
        }, 100);
    }

    /* ==========================================================
       三、她今天
       ========================================================== */

    let lifeOpen = false;

    async function openLife() {
        const drawer = $('lifeDrawer');
        if (!drawer) return;
        lifeOpen = true;
        drawer.classList.add('is-open');
        drawer.setAttribute('aria-hidden', 'false');
        await renderLife();
    }

    function closeLife() {
        const drawer = $('lifeDrawer');
        if (!drawer) return;
        lifeOpen = false;
        drawer.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
    }

    async function renderLife() {
        const body = $('lifeBody');
        if (!body) return;
        body.innerHTML = '<p class="life-empty">正在想今天做了什么…</p>';

        let life = null;
        try {
            life = await eel.get_daily_life()();
        } catch (e) {
            console.error('读取她今天失败:', e);
        }

        if (!life) {
            body.innerHTML = '<p class="life-empty">没读出来。稍后再看看？</p>';
            return;
        }

        const title = $('lifeDayTitle');
        const sub = $('lifeDaySub');
        if (title) title.textContent = life.label || '她今天';
        if (sub) {
            const bits = [];
            if (life.weather) bits.push(life.weather);
            if (life.mood) bits.push('心情 ' + life.mood);
            sub.textContent = bits.length ? bits.join(' · ')
                : '你不在的时候，她也在过自己的日子。';
        }

        if (life.empty) {
            body.innerHTML = `<p class="life-empty">今天还没记下什么。<br>
                聊几句，或者点下面的「再过一会儿」，她就会去做点什么。</p>`;
            return;
        }

        const rows = (life.entries || []).map((e, i) => `
            <li class="life-entry" style="animation-delay:${i * 0.03}s">
                <span class="life-entry__time">${escapeHtml(e.t || '')}</span>
                <span class="life-entry__text">${escapeHtml(e.act || '')}</span>
                ${e.note ? `<span class="life-entry__note">${escapeHtml(e.note)}</span>` : ''}
            </li>
        `).join('');

        body.innerHTML = `
            ${life.now ? `<div class="life-now"><span class="life-now__dot"></span>
                <span>此刻：${escapeHtml(life.now)}</span></div>` : ''}
            <ol class="life-timeline">${rows}</ol>
            ${life.thought ? `<div class="life-thought">
                <span class="life-thought__label">今天想跟你说</span>
                ${escapeHtml(life.thought)}
            </div>` : ''}
        `;
    }

    async function refreshLife(btn) {
        await withBusy(btn, async () => {
            let res = null;
            try {
                res = await eel.refresh_daily_life()();
            } catch (e) {
                console.error('补写失败:', e);
            }
            if (!res || !res.success) {
                showNotification('这会儿没写成，可能是模型没连上', 'error', 2600);
                return;
            }
            if (res.state) renderLifeState(res.state);
            else await renderLife();
            showNotification(res.wrote ? '她又过了一小段日子' : '刚才才写过，等会儿再说',
                'success', 2000);
        });
    }

    /** 用后端返回的状态直接渲染（省一次请求） */
    function renderLifeState(life) {
        const body = $('lifeBody');
        if (!body || !life) return;
        if (life.empty) {
            body.innerHTML = '<p class="life-empty">今天还没记下什么。</p>';
            return;
        }
        const rows = (life.entries || []).map((e, i) => `
            <li class="life-entry" style="animation-delay:${i * 0.03}s">
                <span class="life-entry__time">${escapeHtml(e.t || '')}</span>
                <span class="life-entry__text">${escapeHtml(e.act || '')}</span>
                ${e.note ? `<span class="life-entry__note">${escapeHtml(e.note)}</span>` : ''}
            </li>
        `).join('');
        body.innerHTML = `
            ${life.now ? `<div class="life-now"><span class="life-now__dot"></span>
                <span>此刻：${escapeHtml(life.now)}</span></div>` : ''}
            <ol class="life-timeline">${rows}</ol>
        `;
    }

    /** 光室那行小字：她此刻在做什么 */
    async function refreshChamberNow() {
        const text = $('chamberNowText');
        if (!text) return;
        if (typeof eel === 'undefined' || typeof eel.get_daily_life !== 'function') {
            text.textContent = '她今天还没记下什么';
            return;
        }
        try {
            const life = await eel.get_daily_life()();
            if (!life) {
                text.textContent = '她今天还没记下什么';
                return;
            }
            if (life.now) {
                text.textContent = life.now;
            } else if (life.entries && life.entries.length) {
                text.textContent = '她今天记了 ' + life.entries.length + ' 件事';
            } else {
                text.textContent = '她今天还没记下什么';
            }
        } catch (e) {
            console.error('读取她今天失败:', e);
        }
    }

    /* ==========================================================
       四、改一下重发
       ========================================================== */

    let pendingEdit = null;   // { msgId, text }

    function beginEditMessage(msgId, text) {
        const bar = $('composerEditBar');
        const barText = $('composerEditText');
        const input = $('messageInput');
        const composer = $('composer');
        if (!input) return;

        pendingEdit = { msgId: msgId, text: text };
        input.value = text;

        // 别调 resetComposer：它会清空。这里只把高度重新算一遍
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 168) + 'px';

        if (bar) bar.hidden = false;
        if (barText) {
            barText.textContent = '改完发送，会替换这一条和它之后的内容';
        }
        if (composer) composer.classList.add('is-editing');
        input.focus({ preventScroll: true });
        input.setSelectionRange(text.length, text.length);
    }

    function cancelEditMessage() {
        const bar = $('composerEditBar');
        const composer = $('composer');
        const input = $('messageInput');
        pendingEdit = null;
        if (bar) bar.hidden = true;
        if (composer) composer.classList.remove('is-editing');
        if (input) {
            input.value = '';
            input.style.height = 'auto';
        }
    }

    /** 发送前调用：如果正在编辑，先把旧的那条删掉 */
    async function applyPendingEdit() {
        // 没有在改的时候必须返回 false：调用方靠它决定要不要重建聊天区。
        // 以前一律返回 true，等于每发一条消息都重绘整段对话。
        if (!pendingEdit) return false;
        const target = pendingEdit.msgId;
        pendingEdit = null;
        try {
            await eel.truncate_from(target)();
        } catch (e) {
            console.error('替换旧消息失败:', e);
            showNotification('没能替换掉旧的那条，就直接发新的了', 'info', 2600);
        }
        const bar = $('composerEditBar');
        const composer = $('composer');
        if (bar) bar.hidden = true;
        if (composer) composer.classList.remove('is-editing');
        // 返回被替换的那条的 id：调用方据此只摘掉这一段气泡，
        // 不用把整段对话清空重画（那样会闪，还会重放所有入场动画）。
        return target;
    }

    /* ==========================================================
       五、她先开口
       ========================================================== */

    eel.expose(pushProactive);
    function pushProactive(text) {
        if (!text) return;
        if (typeof isWaitingForResponse !== 'undefined' && isWaitingForResponse) {
            // 正在回复的时候插一条会打断节奏，等它说完
            setTimeout(() => pushProactive(text), 2400);
            return;
        }

        const stick = typeof isNearBottom === 'function' ? isNearBottom() : true;
        const box = $('chatMessages');
        if (!box) return;

        const node = buildMessageNode('ai', text, box.children.length, false, '');
        // 抬头加一个"她先开口"的小标记，别让它看起来像你没说话她突然回你
        if (typeof flagProactive === 'function') flagProactive(node);

        box.appendChild(node);
        if (typeof updateWelcome === 'function') updateWelcome();
        if (stick) scrollToBottom(false);

        // 光室里也动一下，让她"刚说过话"这件事有落点
        const avatar = $('avatarImage');
        if (avatar) {
            pulse(avatar, 'talking', Math.min(text.length * 60, 2600));
        }
    }

    /* ==========================================================
       六、主动消息设置卡
       ========================================================== */

    async function renderProactiveCard() {
        const box = $('proactiveCardBody');
        if (!box) return;

        let st = null;
        try {
            st = await eel.get_proactive_status()();
        } catch (e) {
            st = null;
        }
        if (!st) {
            box.innerHTML = '<p class="form-hint">读取状态失败。</p>';
            return;
        }

        const gap = st.gap_hours || 6;
        const cap = st.daily_cap || 2;
        box.innerHTML = `
            <p class="proactive-card__why">${escapeHtml(st.why || '')}</p>
            <div class="proactive-card__actions">
                <button class="btn btn-outline" type="button" onclick="fireProactiveNow(this)">现在试一句</button>
            </div>
            <details class="proactive-card__more">
                <summary>调整节奏</summary>
                <div class="proactive-card__grid">
                    <div class="form-group">
                        <label class="form-label">多久没说话才找</label>
                        <select class="form-select" id="proactiveGap" onchange="saveProactiveCard()">
                            ${[2, 4, 6, 12, 24].map(h =>
                                `<option value="${h}" ${Number(gap) === h ? 'selected' : ''}>${h} 小时</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">一天最多几句</label>
                        <select class="form-select" id="proactiveCap" onchange="saveProactiveCard()">
                            ${[1, 2, 3, 4].map(n =>
                                `<option value="${n}" ${Number(cap) === n ? 'selected' : ''}>${n} 句</option>`
                            ).join('')}
                        </select>
                    </div>
                </div>
                <div class="form-group" style="margin-top:10px;">
                    <label class="form-label">不打扰的时段</label>
                    <input type="text" class="form-input" id="proactiveQuiet"
                           value="${escapeHtml(st.quiet || '23:30-07:30')}"
                           placeholder="23:30-07:30" onchange="saveProactiveCard()">
                    <p class="form-hint">这段时间她一定不会出声。跨零点也认。改完自动保存。</p>
                </div>
            </details>
        `;
    }

    async function saveProactiveCard(btn) {
        const gapEl = $('proactiveGap');
        const capEl = $('proactiveCap');
        const quietEl = $('proactiveQuiet');
        if (!gapEl || !capEl || !quietEl) return;

        const gap = Number(gapEl.value || 6);
        const cap = Number(capEl.value || 2);
        const quiet = (quietEl.value || '23:30-07:30').trim();

        try {
            const res = await eel.save_proactive_settings({
                gap_hours: gap, daily_cap: cap, quiet: quiet
            })();
            if (res && res.success) {
                showNotification('改好了', 'success', 1600);
                // 只更新状态那句，别整卡重绘——重绘会把展开的 details 收起来
                const why = box => box && box.querySelector('.proactive-card__why');
                const el = why($('proactiveCardBody'));
                if (el && res.status) el.textContent = res.status.why || el.textContent;
            } else {
                showNotification('保存失败', 'error');
            }
        } catch (e) {
            console.error('保存主动消息设置失败:', e);
            showNotification('保存失败', 'error');
        }
    }

    async function fireProactiveNow(btn) {
        await withBusy(btn, async () => {
            let res = null;
            try {
                res = await eel.fire_proactive()();
            } catch (e) {
                console.error('让她说一句失败:', e);
            }
            if (res && res.ok) {
                showNotification('她开口了', 'success', 1800);
                renderProactiveCard();
            } else {
                showNotification((res && res.reason) || '这次没说出来', 'error', 3000);
            }
        });
    }

    async function toggleProactive(enabled) {
        try {
            const res = await eel.save_proactive_settings({ enabled: !!enabled })();
            if (res && res.success) {
                showNotification(enabled ? '她可以主动找你了' : '她不会主动出声了',
                    'success', 2200);
                renderProactiveCard();
                return true;
            }
        } catch (e) {
            console.error(e);
        }
        showNotification('设置失败', 'error');
        return false;
    }

    /* ==========================================================
       七、启动
       ========================================================== */

    function initPanels() {
        initSearch();

        document.addEventListener('keydown', (e) => {
            const typing = e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
            const cmd = e.ctrlKey || e.metaKey;

            // Ctrl+F 搜索（输入框里也照常触发：找的就是你写过的话）
            if (cmd && (e.key === 'f' || e.key === 'F')) {
                e.preventDefault();
                openSearch();
                return;
            }
            if (cmd && e.shiftKey && (e.key === 'l' || e.key === 'L')) {
                // 用 Ctrl+Shift+L 而不是 Ctrl+L：WebView2 会把 Ctrl+L 当成
                // "选地址栏"先吃掉，页面根本收不到
                e.preventDefault();
                openLife();
                return;
            }
            // Esc：先关最上面这层
            if (e.key === 'Escape') {
                const overlay = $('searchOverlay');
                if (overlay && !overlay.hidden) {
                    e.preventDefault();
                    closeSearch();
                    return;
                }
                if (lifeOpen) {
                    e.preventDefault();
                    closeLife();
                    return;
                }
                if (pendingEdit && !typing) {
                    cancelEditMessage();
                }
            }
        });

        // 光室那行字：进来先刷一次，之后每 6 分钟跟着时间走
        setTimeout(refreshChamberNow, 1200);
        setInterval(refreshChamberNow, 6 * 60 * 1000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPanels);
    } else {
        initPanels();
    }

    window.openSearch = openSearch;
    window.closeSearch = closeSearch;
    window.openLife = openLife;
    window.closeLife = closeLife;
    window.refreshLife = refreshLife;
    window.flashMessage = flashMessage;
    window.beginEditMessage = beginEditMessage;
    window.cancelEditMessage = cancelEditMessage;
    window.applyPendingEdit = applyPendingEdit;
    window.pushProactive = pushProactive;
    window.renderProactiveCard = renderProactiveCard;
    window.saveProactiveCard = saveProactiveCard;
    window.fireProactiveNow = fireProactiveNow;
    window.toggleProactive = toggleProactive;
    window.refreshChamberNow = refreshChamberNow;

    // chat.js 里发送流程要用
    window.markSending = markSending;
    window.markSent = markSent;
    window.markFailed = markFailed;
})();
