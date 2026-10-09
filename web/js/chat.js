// ===== 聊天功能 - 星织AI助手 =====

// 全局变量
let isWaitingForResponse = false;
let uploadedFileContent = null;
let uploadedFileName = null;

/**
 * 初始化聊天功能
 */
function initChat() {
    const messageInput = document.getElementById('messageInput');

    // 回车发送消息
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // 加载历史消息
    loadCurrentConversation();
}

/**
 * 发送消息
 */
async function sendMessage() {
    const input = document.getElementById('messageInput');
    let message = input.value.trim();

    if (!message && !uploadedFileContent) {
        showNotification('请输入消息', 'error', 2000);
        return;
    }

    if (isWaitingForResponse) {
        showNotification('请等待AI回复', 'error', 2000);
        return;
    }

    // 如果有文件，添加文件内容
    if (uploadedFileContent) {
        message = `${message}\n\n--- 文件内容 (${uploadedFileName}) ---\n${uploadedFileContent}`;
    }

    // 显示用户消息
    displayMessage('user', message);

    // 清空输入
    input.value = '';
    clearFile();

    // 滚动到底部
    scrollToBottom();

    // 设置等待状态
    isWaitingForResponse = true;

    // 显示typing指示器
    showTypingIndicator();
    
    // 添加思考动画
    if (window.avatarAnimationManager) {
        const avatarImage = document.getElementById('avatarImage');
        if (avatarImage) {
            avatarImage.classList.add('thinking');
        }
    }

    try {
        // 调用Python发送消息
        await eel.send_message_from_web(message)();
    } catch (e) {
        console.error('Send message error:', e);
        removeTypingIndicator();
        
        // 移除思考动画
        if (window.avatarAnimationManager) {
            const avatarImage = document.getElementById('avatarImage');
            if (avatarImage) {
                avatarImage.classList.remove('thinking');
            }
        }
        
        showNotification('发送失败，请重试', 'error');
        isWaitingForResponse = false;
    }
}

/**
 * 显示消息气泡
 * @param {string} role - 角色: user, ai, system
 * @param {string} content - 消息内容
 */
function displayMessage(role, content) {
    const chatMessages = document.getElementById('chatMessages');

    const bubble = document.createElement('div');
    bubble.className = `message-bubble ${role}`;
    bubble.textContent = content;

    chatMessages.appendChild(bubble);

    // 滚动到底部
    setTimeout(() => scrollToBottom(), 100);
}

/**
 * 从Python接收AI回复
 * @param {string} content - AI回复内容
 */
eel.expose(receiveAIResponse);
function receiveAIResponse(content) {
    removeTypingIndicator();
    
    // 移除思考动画
    const avatarImage = document.getElementById('avatarImage');
    if (avatarImage) {
        avatarImage.classList.remove('thinking');
    }
    
    // 添加说话动画
    if (window.avatarAnimationManager && avatarImage) {
        avatarImage.classList.add('talking');
        
        // 根据内容长度决定说话动画持续时间
        const duration = Math.min(content.length * 50, 5000); // 最多5秒
        setTimeout(() => {
            avatarImage.classList.remove('talking');
        }, duration);
    }
    
    displayMessage('ai', content);
    isWaitingForResponse = false;
}

/**
 * 显示打字指示器
 */
function showTypingIndicator() {
    const chatMessages = document.getElementById('chatMessages');

    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'message-bubble ai';
    indicator.innerHTML = `
        <div class="loading-dots">
            <span></span>
            <span></span>
            <span></span>
        </div>
    `;

    chatMessages.appendChild(indicator);
    scrollToBottom();
}

/**
 * 移除打字指示器
 */
function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

/**
 * 滚动到底部
 */
function scrollToBottom() {
    const container = document.getElementById('chatContainer');
    container.scrollTop = container.scrollHeight;
}

/**
 * 滚动到顶部
 */
function scrollToTop() {
    const container = document.getElementById('chatContainer');
    container.scrollTop = 0;
}

/**
 * 清空聊天内容
 */
function clearChat() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.innerHTML = '';
}

/**
 * 加载当前对话
 */
async function loadCurrentConversation() {
    try {
        const conversation = await eel.get_current_conversation()();
        if (conversation && conversation.messages) {
            clearChat();
            conversation.messages.forEach(msg => {
                // 映射角色：assistant -> ai, user -> user
                const role = msg.role === 'user' ? 'user' : (msg.role === 'assistant' ? 'ai' : 'system');
                // 只显示非空内容
                if (msg.content && msg.content.trim()) {
                    displayMessage(role, msg.content);
                }
            });
        }
    } catch (e) {
        console.error('Load conversation error:', e);
    }
}

/**
 * 新建对话
 */
async function newConversation() {
    try {
        await eel.new_conversation_from_web()();
        clearChat();
        showNotification('已创建新对话', 'success', 2000);
    } catch (e) {
        console.error('New conversation error:', e);
        showNotification('创建失败', 'error');
    }
}

/**
 * 显示对话列表
 */
async function showConversationList() {
    try {
        const conversations = await eel.get_conversations_list()();

        if (!conversations || conversations.length === 0) {
            showNotification('暂无历史对话', 'info', 2000);
            return;
        }

        const listHtml = conversations.map(conv => `
            <div class="conversation-item ${conv.is_current ? 'active' : ''}" 
                 onclick="loadConversation('${conv.id}')">
                <div class="conversation-info">
                    <div class="conversation-title">${escapeHtml(conv.title || '新对话')}</div>
                    <div class="conversation-meta">${formatTime(conv.timestamp)} · ${conv.message_count} 条消息</div>
                </div>
                <div class="conversation-actions">
                    <button class="conversation-action-btn" 
                            onclick="event.stopPropagation(); deleteConversation('${conv.id}')">
                        🗑
                    </button>
                </div>
            </div>
        `).join('');

        createModal(
            '📋 历史对话',
            `<div class="conversation-list">${listHtml}</div>`,
            [
                {
                    text: '关闭',
                    style: 'btn-ghost',
                    onClick: () => { }
                }
            ]
        );
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
        await eel.load_conversation_from_web(convId)();
        await loadCurrentConversation();
        closeModal(event.target);
        showNotification('已加载对话', 'success', 2000);
    } catch (e) {
        console.error('Load conversation error:', e);
        showNotification('加载失败', 'error');
    }
}

/**
 * 删除对话
 * @param {string} convId - 对话ID
 */
async function deleteConversation(convId) {
    if (!confirm('确定要删除这个对话吗？')) {
        return;
    }

    try {
        const success = await eel.delete_conversation_from_web(convId)();
        if (success) {
            showNotification('已删除对话', 'success', 2000);
            // 移除对话项元素
            const item = event.target.closest('.conversation-item');
            if (item) {
                item.style.animation = 'fadeOut 0.3s ease';
                setTimeout(() => item.remove(), 300);
            }
        } else {
            showNotification('删除失败', 'error');
        }
    } catch (e) {
        console.error('Delete conversation error:', e);
        showNotification('删除失败', 'error');
    }
}

/**
 * 上传文件
 */
async function uploadFile() {
    console.log('📎 点击上传按钮');
    try {
        console.log('🔄 调用后端上传函数...');
        const result = await eel.upload_file_from_web()();
        console.log('📦 收到后端响应:', result);
        
        if (result && result.success) {
            uploadedFileContent = result.content;
            uploadedFileName = result.filename;

            const fileIndicator = document.getElementById('fileIndicator');
            const fileInfo = document.getElementById('fileInfo');
            fileInfo.textContent = `📄 ${result.filename} (${result.char_count} 字符)`;
            fileIndicator.style.display = 'flex';

            showNotification('文件上传成功', 'success', 2000);
        } else if (result && result.cancelled) {
            console.log('⚠️ 用户取消了文件选择');
            // 用户取消，不显示错误
        } else {
            const errorMsg = result && result.error ? result.error : '未知错误';
            console.error('❌ 上传失败:', errorMsg);
            showNotification(`文件上传失败: ${errorMsg}`, 'error', 3000);
        }
    } catch (e) {
        console.error('❌ Upload file error:', e);
        showNotification(`文件上传异常: ${e.message || e}`, 'error', 3000);
    }
}

/**
 * 清除已上传文件
 */
function clearFile() {
    uploadedFileContent = null;
    uploadedFileName = null;

    const fileIndicator = document.getElementById('fileIndicator');
    fileIndicator.style.display = 'none';
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
