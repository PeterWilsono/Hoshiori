// ===== 聊天功能 - 星织AI助手 =====

// 全局变量
let isWaitingForResponse = false;
let uploadedFileContent = null;
let uploadedFileName = null;

/**
 * 轻量富文本渲染：先转义，再处理代码块 / 行内代码 / 加粗 / 链接
 * @param {string} raw
 * @returns {string} 安全的 HTML
 */
function renderRichText(raw) {
    const codeBlocks = [];

    let text = escapeHtml(raw).replace(/```([\w+#-]*)\r?\n([\s\S]*?)```/g, (m, lang, code) => {
        const idx = codeBlocks.push(`<pre><code>${code.replace(/\n$/, '')}</code></pre>`) - 1;
        return `\u0000${idx}\u0000`;
    });

    text = text
        .replace(/`([^`\n]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(（])(https?:\/\/[^\s<）)]+)/g,
            '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');

    const parts = text.split(/\u0000(\d+)\u0000/);
    let out = '';

    parts.forEach((part, i) => {
        if (i % 2 === 1) {
            out += codeBlocks[Number(part)] || '';
            return;
        }
        let text = part.replace(/\n{3,}/g, '\n\n');
        // 与代码块相邻的空行交给代码块自身的间距处理
        if (i > 0) text = text.replace(/^\n+/, '');
        if (i < parts.length - 1) text = text.replace(/\n+$/, '');
        out += text.replace(/\n/g, '<br>');
    });

    return out;
}

/**
 * 初始化聊天功能
 */
function initChat() {
    const messageInput = document.getElementById('messageInput');
    if (!messageInput) return;

    // 回车发送消息
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendMessage();
        }
    });

    // 加载历史消息（返回 Promise，好让启动画面等到消息真的画出来）
    updateWelcome();
    loadResumeHint();
    return loadCurrentConversation();
}

/**
 * 空状态：显示「上次停在这里」的入口
 */
async function loadResumeHint() {
    const hint = document.getElementById('resumeHint');
    const titleEl = document.getElementById('resumeTitle');
    if (!hint || !titleEl) return;

    try {
        const list = await eel.get_conversations_list()();
        const last = (list || []).find(c => !c.is_current && (c.message_count || 0) > 0);
        if (!last) {
            hint.hidden = true;
            return;
        }
        titleEl.textContent = last.title || '未命名对话';
        hint.hidden = false;
        hint.onclick = () => loadConversation(last.id);
    } catch (e) {
        hint.hidden = true;
    }
}

/**
 * 同步空状态 / 会话抬头
 */
function updateWelcome() {
    const chatMessages = document.getElementById('chatMessages');
    const welcome = document.getElementById('welcomeState');
    if (!chatMessages || !welcome) return;

    const hasAny = chatMessages.children.length > 0;
    welcome.classList.toggle('is-hidden', hasAny);
    chatMessages.classList.toggle('is-empty', !hasAny);

    const head = document.getElementById('sessionHead');
    const label = document.getElementById('sessionHeadLabel');
    if (head) {
        head.hidden = !hasAny;
        if (label) label.textContent = sessionLabel();
    }
}

/**
 * 生成会话抬头的时间标签
 */
function sessionLabel() {
    const now = new Date();
    const h = now.getHours();
    const part = h < 5 ? '凌晨' : h < 11 ? '上午' : h < 14 ? '午后' : h < 18 ? '黄昏' : h < 23 ? '夜' : '深夜';
    const month = now.getMonth() + 1;
    const day = now.getDate();
    return `${month}月${day}日 · ${part}`;
}

/**
 * 是否已贴在底部
 */
function isNearBottom(threshold = 140) {
    const container = document.getElementById('chatContainer');
    if (!container) return true;
    return container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
}

/**
 * 发送消息
 */
async function sendMessage() {
    const input = document.getElementById('messageInput');
    let message = input.value.trim();

    if (!message && !uploadedFileContent) {
        showNotification('还没写内容呢', 'info', 1800);
        input.focus();
        return;
    }

    if (isWaitingForResponse) {
        showNotification('星织正在回复，稍等一下', 'info', 1800);
        return;
    }

    // 如果有文件，添加文件内容（Word/Excel/PPT/PDF 已在后端转成纯文本）
    if (uploadedFileContent) {
        const head = message ? `${message}\n\n` : '';
        message = `${head}--- 文件内容（${uploadedFileName}）---\n${uploadedFileContent}`;
    }

    // 正在"改一下重发"的话，先把旧的那条（以及它之后的）删掉。
    // 必须先截断再插新消息，否则会多出一条重复的。
    //
    // 注意这里要看返回值：以前写成「函数存在就重建」，而它永远存在，
    // 结果每发一条消息都把整个聊天区清空重拉一遍——屏幕先空一下，
    // 再从顶部滑下来。这就是"闪一下"的来源。
    if (typeof applyPendingEdit === 'function') {
        const cutFrom = await applyPendingEdit();
        if (cutFrom) {
            // 只摘掉被换掉的那条及其之后的，其余的留在原地。
            // 整段清空重画会闪一下，也没必要——库里已经截断好了。
            if (!removeMessagesFrom(cutFrom)) {
                clearChat();
                await loadCurrentConversation();
            }
        }
    }

    // 显示用户消息
    displayMessage('user', message);

    // 清空输入
    input.value = '';
    clearFile();
    if (typeof window.resetComposer === 'function') window.resetComposer();

    // 输入框清空后会变矮，聊天区的可视高度跟着变。
    // 等这一帧的布局算完再贴一次底——必须立刻贴，不能滑。
    requestAnimationFrame(() => scrollToBottom(false));

    // 设置等待状态
    isWaitingForResponse = true;
    if (typeof markSending === 'function') markSending();

    // 显示typing指示器
    showTypingIndicator();

    // 添加思考动画
    const avatarImage = document.getElementById('avatarImage');
    if (avatarImage) avatarImage.classList.add('thinking');

    try {
        const ok = await eel.send_message_from_web(message)();
        if (ok === false) throw new Error('服务端拒绝了这条消息');
    } catch (e) {
        console.error('Send message error:', e);
        removeTypingIndicator();
        if (avatarImage) avatarImage.classList.remove('thinking');
        if (typeof markFailed === 'function') markFailed();
        // 说清楚哪一步坏了，别只丢一句"失败"
        showNotification('没发出去。检查一下网络或者模型配置，再说一次？', 'error', 3600);
        isWaitingForResponse = false;
        // 把内容还回输入框，省得重打
        const box = document.getElementById('messageInput');
        if (box && !box.value.trim()) {
            box.value = message;
            box.dispatchEvent(new Event('input'));
            box.focus({ preventScroll: true });
        }
    }
}

/**
 * 构建单条消息节点
 * @param {string} role - user / ai / system
 * @param {string} content
 * @param {number} index
 * @param {boolean} continuation - 是否是同一轮回复的续句（不重复落款）
 * @returns {HTMLElement}
 */
function buildMessageNode(role, content, index = 0, continuation = false, clock = '', msgId = '') {
    const node = document.createElement('div');
    node.className = `message-bubble ${role}`;
    if (continuation) node.classList.add('is-cont');
    node.style.setProperty('--i', Math.min(index, 5));
    // 存了 id 才能在搜索里"跳回这一句"、才能"改一下重发"
    if (msgId !== '' && msgId !== null && msgId !== undefined) {
        node.dataset.msgId = String(msgId);
    }
    // 历史消息带真实时间；刚发出来的才用"此刻"
    const stamp = clock || nowClock();

    if (role === 'ai') {
        node.innerHTML = `
            <div class="msg-rule">
                <span class="msg-rule__star"><svg viewBox="0 0 24 24"><use href="#i-star"></use></svg></span>
                <span class="msg-rule__line"></span>
                <time class="msg-rule__time">${stamp}</time>
                <button class="msg-copy" type="button" aria-label="复制这段话" title="复制">
                    <svg class="icon" viewBox="0 0 24 24"><use href="#i-copy"></use></svg>
                </button>
            </div>
            <div class="msg-body">${renderRichText(content)}</div>
        `;

        const copyBtn = node.querySelector('.msg-copy');
        copyBtn.addEventListener('click', async () => {
            const ok = await copyToClipboard(content, true);
            if (!ok) return;
            copyBtn.classList.add('is-done');
            copyBtn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-check"></use></svg>';
            setTimeout(() => {
                copyBtn.classList.remove('is-done');
                copyBtn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-copy"></use></svg>';
            }, 1400);
        });
    } else if (role === 'user') {
        // 用户不拆气泡，但换行要留住（renderRichText 不管换行）
        node.innerHTML = `
            <div class="msg-body">${renderRichText(content).replace(/\n/g, '<br>')}</div>
            <div class="msg-meta">${stamp}</div>
        `;

        // 只有带 id 的历史消息才允许改：刚发出去还没落库的那条没得改
        if (node.dataset.msgId) {
            const actions = document.createElement('div');
            actions.className = 'msg-actions';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'msg-action';
            btn.title = '改一下，重新说';
            btn.setAttribute('aria-label', '改一下重发');
            btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-edit"></use></svg>';
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                beginEditMessage(node.dataset.msgId, content);
            });
            actions.appendChild(btn);
            node.appendChild(actions);
        }
    } else {
        node.textContent = content;
    }

    return node;
}

/**
 * 把一条气泡标成「她先开口」：星标换成暖色，抬头多一点小字。
 * @param {HTMLElement} node
 */
function flagProactive(node) {
    if (!node) return;
    node.classList.add('is-proactive');
    const rule = node.querySelector('.msg-rule');
    if (!rule || rule.querySelector('.msg-rule__flag')) return;
    const flag = document.createElement('span');
    flag.className = 'msg-rule__flag';
    flag.textContent = '她先开口';
    const time = rule.querySelector('.msg-rule__time');
    if (time) rule.insertBefore(flag, time);
    else rule.appendChild(flag);
}

/**
 * 最后一条真实消息是谁说的（跳过「正在书写」的占位）
 */
function lastMessageRole() {
    const box = document.getElementById('chatMessages');
    if (!box) return '';
    for (let i = box.children.length - 1; i >= 0; i--) {
        const node = box.children[i];
        if (node.id === 'typingIndicator') continue;
        if (node.classList.contains('message-bubble')) {
            if (node.classList.contains('ai')) return 'ai';
            if (node.classList.contains('user')) return 'user';
        }
        return '';
    }
    return '';
}

/**
 * 显示消息气泡
 * @param {string} role - 角色: user, ai, system
 * @param {string} content - 消息内容
 * @param {boolean} continuation - 同一轮回复的续句
 */
function displayMessage(role, content, continuation = false) {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;

    const stick = isNearBottom();
    const index = chatMessages.children.length;
    const isCont = role === 'ai' && (continuation || lastMessageRole() === 'ai');
    const node = buildMessageNode(role, content, index, isCont);

    chatMessages.appendChild(node);
    updateWelcome();

    // 自己发的消息无论如何都要看见；她的话只在本来就在底部时才跟。
    // 这里必须是「立刻」：用平滑动画的话，长对话里会从上面一路滑下来。
    if (stick || role === 'user') {
        scrollToBottom(false);
    }
}

/**
 * 从Python接收AI回复
 * @param {string} content - AI回复内容
 */
eel.expose(receiveAIResponse);
function receiveAIResponse(content) {
    removeTypingIndicator();

    const avatarImage = document.getElementById('avatarImage');
    if (avatarImage) avatarImage.classList.remove('thinking');

    // 说话动画（静态立绘用；Live2D 的嘴由语音回调驱动，别两边抢）
    if (window.avatarAnimationManager && avatarImage) {
        const live2dActive = (typeof Live2DManager !== 'undefined') && Live2DManager.isInitialized;
        if (appState.voiceEnabled && !live2dActive) {
            avatarImage.classList.add('talking');
            const duration = Math.min(String(content).length * 60, 4000);
            setTimeout(() => avatarImage.classList.remove('talking'), duration);
        } else {
            avatarImage.classList.remove('talking');
        }
    }

    displayMessage('ai', content);

    isWaitingForResponse = false;
    if (typeof markSent === 'function') markSent();
}

/**
 * 给上一条 AI 气泡补一小段文字（比如结尾单独飘过来的 emoji）
 */
eel.expose(appendAIResponse);
function appendAIResponse(extra) {
    if (!extra) return;
    const box = document.getElementById('chatMessages');
    if (!box) return;
    for (let i = box.children.length - 1; i >= 0; i--) {
        const node = box.children[i];
        if (node.id === 'typingIndicator') continue;
        if (!node.classList.contains('ai')) break;
        const body = node.querySelector('.msg-body');
        if (!body) break;
        body.appendChild(document.createTextNode(extra));
        if (isNearBottom()) scrollToBottom(false);
        return;
    }
    // 没有可追加的气泡，就当成一条新消息
    displayMessage('ai', extra);
}

/**
 * 显示打字指示器
 */
function showTypingIndicator() {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages || document.getElementById('typingIndicator')) return;

    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'message-bubble ai';
    indicator.innerHTML = `
        <div class="msg-rule">
            <span class="msg-rule__star"><svg viewBox="0 0 24 24"><use href="#i-star"></use></svg></span>
            <span class="msg-rule__line"></span>
            <time class="msg-rule__time">此刻</time>
        </div>
        <div class="msg-body">
            <div class="loading-dots"><span></span><span></span><span></span>
                <em class="typing-label">星织正在书写</em>
            </div>
        </div>
    `;

    chatMessages.appendChild(indicator);
    updateWelcome();
    scrollToBottom(false);
}

/**
 * 移除打字指示器
 */
function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
    updateWelcome();
}

/**
 * 滚动到底部
 * @param {boolean} smooth
 */
function scrollToBottom(smooth = false) {
    const container = document.getElementById('chatContainer');
    if (!container) return;

    const top = Math.max(0, container.scrollHeight - container.clientHeight);

    if (smooth) {
        container.scrollTo({ top, behavior: 'smooth' });
        return;
    }

    // 容器上写着 scroll-behavior: smooth，所以连 scrollTop = xxx 都会被做成动画。
    // 想「真的立刻贴上底部」只能先把这条规则临时摘掉，写完再恢复。
    const prev = container.style.scrollBehavior;
    container.style.scrollBehavior = 'auto';
    container.scrollTop = top;
    void container.offsetHeight;        // 强制应用一次，别让恢复样式把这次滚动吞掉
    container.style.scrollBehavior = prev;
}

/**
 * 滚动到顶部
 */
function scrollToTop() {
    const container = document.getElementById('chatContainer');
    if (container) container.scrollTop = 0;
}

/**
 * 回到最新（供浮标调用）
 */
function scrollToLatest() {
    scrollToBottom(true);
    const pill = document.getElementById('scrollPill');
    if (pill) pill.classList.remove('is-visible');
}

/** "2026-11-10 23:12" → "23:12"；拿不到就用此刻 */
function clockOf(stamp) {
    if (!stamp) return '';
    const m = String(stamp).match(/(\d{1,2}):(\d{2})/);
    return m ? `${m[1].padStart(2, '0')}:${m[2]}` : '';
}

/**
 * 清空聊天内容
 */
function clearChat() {
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) chatMessages.innerHTML = '';
    updateWelcome();
}

/**
 * 把某条消息及其之后的所有气泡从界面上摘掉（「改一下重发」用）。
 *
 * 一轮回复会拆成好几个气泡，它们带着同一个 msgId，所以从目标那条开始
 * 一直删到底即可。返回是否找到了目标——找不到就让调用方退回整段重载。
 */
function removeMessagesFrom(msgId) {
    const box = document.getElementById('chatMessages');
    if (!box) return false;
    const target = String(msgId);
    const nodes = Array.from(box.children);
    const start = nodes.findIndex(n => n.dataset && n.dataset.msgId === target);
    if (start < 0) return false;
    for (let i = nodes.length - 1; i >= start; i--) nodes[i].remove();
    updateWelcome();
    return true;
}

/**
 * 加载当前对话
 */
async function loadCurrentConversation() {
    try {
        const conversation = await eel.get_current_conversation()();

        const sessionEl = document.getElementById('titlebarSession');
        if (sessionEl) {
            const label = (conversation && conversation.title) || '';
            sessionEl.textContent = label;
            sessionEl.title = label;
        }

        if (conversation && conversation.messages) {
            clearChat();
            // 历史是一次性画的，别让每条都播一遍入场动画
            const box = document.getElementById('chatMessages');
            if (box) box.classList.add('is-restoring');
            let idx = 0;
            for (const msg of conversation.messages) {
                const role = msg.role === 'user' ? 'user' : (msg.role === 'assistant' ? 'ai' : 'system');
                if (!msg.content || !msg.content.trim()) continue;
                const clock = clockOf(msg.created_at);
                // 存档里的 \n 就是当时那一泡一泡的分界，重开要还原成同样的节奏
                const parts = role === 'ai'
                    ? msg.content.split('\n').map(x => x.trim()).filter(Boolean)
                    : [msg.content];
                parts.forEach((part, j) => {
                    const node = buildMessageNode(role, part, idx++, j > 0, clock, msg.id);
                    // 只有一轮的第一泡带时间和落款
                    if (j > 0) {
                        const meta = node.querySelector('.msg-meta');
                        if (meta) meta.remove();
                    }
                    // 主动消息的标记存在库里，重开对话还在
                    if (msg.kind === 'proactive' && j === 0) flagProactive(node);
                    document.getElementById('chatMessages').appendChild(node);
                });
            }
            updateWelcome();
            scrollToBottom(false);
            // 字体、代码块、图片会把高度再撑一点，下一帧补一次，
            // 否则会看到「停在一半」再补上的动作。
            // 动画开关也在这一帧恢复：几何已经算好了，恢复不会引起跳动。
            requestAnimationFrame(() => {
                scrollToBottom(false);
                if (box) box.classList.remove('is-restoring');
            });
        } else {
            updateWelcome();
        }
    } catch (e) {
        console.error('Load conversation error:', e);
        // 出错时别把这个类留下来，否则之后的新消息也不播入场动画了
        const box = document.getElementById('chatMessages');
        if (box) box.classList.remove('is-restoring');
        updateWelcome();
    }
}

/**
 * 新建对话：先问一句要不要带上之前的一切
 */
function newConversation() {
    const content = `
        <div class="continuity-picker">
            <p class="continuity-lead">开一段新的对话。要带上之前的一切吗？</p>
            <label class="continuity-option is-selected" data-value="1">
                <input type="radio" name="continuity" value="1" checked>
                <span class="continuity-mark" aria-hidden="true"></span>
                <span class="continuity-body">
                    <span class="continuity-title">继续聊<span class="continuity-tag">推荐</span></span>
                    <span class="continuity-desc">她记得你说过的事，关系也从上次接着。只是换个话题。</span>
                </span>
            </label>
            <label class="continuity-option" data-value="0">
                <input type="radio" name="continuity" value="0">
                <span class="continuity-mark" aria-hidden="true"></span>
                <span class="continuity-body">
                    <span class="continuity-title">重新认识</span>
                    <span class="continuity-desc">关系回到最初，也读不到之前跨对话的记忆。像第一次见面。</span>
                </span>
            </label>
            <p class="continuity-foot">两种都不会删掉已有的对话和记忆，随时能回到之前那段。</p>
        </div>`;

    const overlay = createModal('新的对话', content, [
        { text: '取消', style: 'btn-ghost', onClick: () => {} },
        {
            text: '开始', style: 'btn-primary', onClick: () => {
                const picked = overlay.querySelector('input[name="continuity"]:checked');
                createNewConversation(!(picked && picked.value === '0'));
            }
        }
    ]);
    if (!overlay) return;

    overlay.addEventListener('change', (e) => {
        if (!e.target || e.target.name !== 'continuity') return;
        overlay.querySelectorAll('.continuity-option').forEach(el => {
            el.classList.toggle('is-selected', el.dataset.value === e.target.value);
        });
    });
}

async function createNewConversation(continuity) {
    try {
        const result = await eel.new_conversation_from_web(continuity)();
        if (result && result.success === false) {
            showNotification('创建失败', 'error');
            return;
        }
        clearChat();
        updateWelcome();
        const sessionEl = document.getElementById('titlebarSession');
        if (sessionEl) {
            sessionEl.textContent = '';
            sessionEl.title = '';
        }
        closeModal(document.querySelector('.modal-overlay[data-modal="history"]'));
        await loadResumeHint();
        showNotification(continuity ? '新的夜晚，接着聊' : '重新开始，她不记得之前了',
            'success', 2200);
        const input = document.getElementById('messageInput');
        if (input) input.focus();
    } catch (e) {
        console.error('New conversation error:', e);
        showNotification('创建失败', 'error');
    }
}

/**
 * 历史列表条目
 * @param {Array} conversations
 */
function conversationItemsHtml(conversations) {
    return conversations.map(conv => `
        <div class="conversation-item ${conv.is_current ? 'active' : ''}"
             data-id="${conv.id}"
             onclick="loadConversation('${conv.id}')">
            <div class="conversation-info">
                <div class="conversation-title">${escapeHtml(conv.title || '未命名对话')}</div>
                <div class="conversation-meta">
                    <span>${formatTime(conv.timestamp)}</span>
                    <span class="conversation-meta__dot">·</span>
                    <span>${conv.message_count} 则</span>
                    ${conv.continuity === false ? '<span class="conversation-meta__break">重新认识</span>' : ''}
                    ${conv.is_current ? '<span class="conversation-meta__now">停留中</span>' : ''}
                </div>
            </div>
            <div class="conversation-actions">
                <button class="conversation-action-btn" type="button" aria-label="删除这段对话"
                        onclick="event.stopPropagation(); deleteConversation('${conv.id}', this)">
                    <svg class="icon icon-sm" viewBox="0 0 24 24"><use href="#i-trash"></use></svg>
                </button>
            </div>
        </div>
    `).join('');
}

/**
 * 就地刷新已打开的历史面板
 * @param {Array} conversations
 */
function refreshHistoryModal(conversations) {
    const overlay = document.querySelector('.modal-overlay[data-modal="history"]');
    if (!overlay) return;

    if (!conversations || conversations.length === 0) {
        closeModal(overlay);
        return;
    }

    const list = overlay.querySelector('.conversation-list');
    if (list) list.innerHTML = conversationItemsHtml(conversations);

    const title = overlay.querySelector('.modal-title');
    if (title) title.textContent = `历史对话 · ${conversations.length}`;
}

/**
 * 显示对话列表
 */
async function showConversationList() {
    try {
        const conversations = await eel.get_conversations_list()();

        if (!conversations || conversations.length === 0) {
            showNotification('还没有留下过对话', 'info', 2000);
            return;
        }

        const overlay = createModal(
            `历史对话 · ${conversations.length}`,
            `<div class="conversation-list">${conversationItemsHtml(conversations)}</div>`,
            [
                { text: '关闭', style: 'btn-ghost', onClick: () => {} }
            ]
        );
        if (overlay) overlay.setAttribute('data-modal', 'history');
    } catch (e) {
        console.error('Get conversations error:', e);
        showNotification('加载失败', 'error');
    }
}

/**
 * 加载指定对话
 * @param {string} convId - 对话ID
 */
async function loadConversation(convId) {
    try {
        const ok = await eel.load_conversation_from_web(convId)();
        if (!ok) {
            showNotification('这段对话已经找不到了', 'error');
            await refreshConversationState();
            return;
        }
        await loadCurrentConversation();
        closeModal(document.querySelector('.modal-overlay[data-modal="history"]'));
        showNotification('已回到那段对话', 'success', 2000);
    } catch (e) {
        console.error('Load conversation error:', e);
        showNotification('加载失败', 'error');
    }
}

/**
 * 删除对话
 * @param {string} convId - 对话ID
 * @param {HTMLElement} trigger
 */
async function deleteConversation(convId, trigger) {
    const item = (trigger && trigger.closest)
        ? trigger.closest('.conversation-item')
        : document.querySelector(`.conversation-item[data-id="${convId}"]`);
    const titleEl = item ? item.querySelector('.conversation-title') : null;
    const title = titleEl ? titleEl.textContent.trim() : '这段对话';

    const confirmed = await confirmDialog({
        title: '要烧掉这一页吗？',
        text: `「${escapeHtml(title)}」连同里面的每一句都会消失，事后找不回来。`,
        confirmText: '删除这一段',
        cancelText: '留着吧',
        danger: true
    });
    if (!confirmed) return;

    const res = await eel.delete_conversation_from_web(convId)();

    if (!res || !res.success) {
        showNotification((res && res.message) || '删除失败', 'error', 2600);
        return;
    }

    // 先让列表条目收走，再做数据刷新（后端删除后 ID 会重排，旧的 DOM 不能复用）
    if (item) {
        item.classList.add('is-removing');
        await new Promise(r => setTimeout(r, 240));
    }

    let conversations = [];
    try {
        conversations = await eel.get_conversations_list()() || [];
    } catch (e) {
        console.error('Refresh conversations error:', e);
    }
    refreshHistoryModal(conversations);

    // 删掉的正是当前这段：主对话区必须跟着换掉
    if (res.wasCurrent) {
        await loadCurrentConversation();
        showNotification('已删除，停在最近的一段对话', 'success', 2600);
    } else {
        showNotification('对话已删除', 'success', 1800);
    }

    await loadResumeHint();
}

/**
 * 对话被外部改动后，重新对齐整个界面
 */
async function refreshConversationState() {
    await loadCurrentConversation();
    let conversations = [];
    try {
        conversations = await eel.get_conversations_list()() || [];
    } catch (e) { }
    refreshHistoryModal(conversations);
    await loadResumeHint();
}

/**
 * 附件的一行摘要：类型 · 字数 · 截断提示
 */
function describeAttachment(result) {
    const parts = [result.filename];
    if (result.kind) parts.push(result.kind);
    parts.push(`${result.char_count} 字符`);
    if (result.truncated) parts.push(`已截断（原文 ${result.original_chars} 字）`);
    return parts.join(' · ');
}

/**
 * 上传文件
 */
async function uploadFile() {
    try {
        const result = await eel.upload_file_from_web()();

        if (result && result.success) {
            uploadedFileContent = result.content;
            uploadedFileName = result.filename;

            const fileIndicator = document.getElementById('fileIndicator');
            const fileInfo = document.getElementById('fileInfo');
            if (fileInfo) {
                fileInfo.textContent = describeAttachment(result);
                fileInfo.title = describeAttachment(result);
            }
            if (fileIndicator) fileIndicator.style.display = 'flex';

            // 截断 / 页眉页脚这类提醒值得单独说一句，别让它只躺在 title 里
            if (result.warning) {
                showNotification(result.warning, 'info', 3200);
            } else {
                showNotification('文件已附上', 'success', 2000);
            }
        } else if (result && result.cancelled) {
            console.log('用户取消了文件选择');
        } else {
            const errorMsg = result && result.error ? result.error : '未知错误';
            showNotification(`文件读取失败：${errorMsg}`, 'error', 3000);
        }
    } catch (e) {
        console.error('Upload file error:', e);
        showNotification(`文件上传异常：${e.message || e}`, 'error', 3000);
    }
}

/**
 * 清除已上传文件
 */
function clearFile() {
    uploadedFileContent = null;
    uploadedFileName = null;

    const fileIndicator = document.getElementById('fileIndicator');
    if (fileIndicator) fileIndicator.style.display = 'none';
}

// 导出
window.chatManager = {
    init: initChat,
    send: sendMessage,
    display: displayMessage,
    clear: clearChat,
    scrollToBottom,
    scrollToTop,
    newConversation,
    showConversationList,
    uploadFile,
    clearFile
};
