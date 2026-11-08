// ===== 工具函数 - 星织AI助手 =====

/* ---------- 模态栈 ---------- */
const modalStack = [];

/**
 * 创建并显示模态窗口
 * @param {string} title - 窗口标题
 * @param {string} content - 窗口内容(HTML)
 * @param {Array} buttons - 按钮配置数组
 * @returns {HTMLElement} 模态窗口元素
 */
function createModal(title, content, buttons = []) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.setAttribute('data-modal-id', Date.now());
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);

    const modal = document.createElement('div');
    modal.className = 'modal-content';

    // 头部
    const header = document.createElement('div');
    header.className = 'modal-header';
    header.innerHTML = `
        <h2 class="modal-title">${title}</h2>
        <button class="modal-close" type="button" aria-label="关闭" onclick="closeModal(this)">
            <svg class="icon" viewBox="0 0 24 24" style="width:15px;height:15px">
                <use href="#i-close"></use>
            </svg>
        </button>
    `;

    // 内容
    const body = document.createElement('div');
    body.className = 'modal-body';
    body.innerHTML = content;

    // 底部按钮
    const footer = document.createElement('div');
    footer.className = 'modal-footer';
    buttons.forEach(btn => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn ${btn.style || 'btn-ghost'}`;
        button.textContent = btn.text;
        button.onclick = () => {
            if (btn.onClick) btn.onClick();
            closeModal(overlay);
        };
        footer.appendChild(button);
    });

    modal.appendChild(header);
    modal.appendChild(body);
    if (buttons.length > 0) modal.appendChild(footer);

    overlay.appendChild(modal);
    document.getElementById('modalContainer').appendChild(overlay);

    // 点击遮罩关闭（但不影响内容区域）
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal(overlay);
    });

    modal.addEventListener('click', (e) => e.stopPropagation());

    modalStack.push(overlay);

    // 焦点进入弹窗
    requestAnimationFrame(() => {
        const focusTarget = body.querySelector(
            'input:not([type=hidden]):not([disabled]), textarea, select, button.btn-primary'
        ) || header.querySelector('.modal-close');
        if (focusTarget) focusTarget.focus({ preventScroll: true });
    });

    return overlay;
}

/**
 * 关闭模态窗口
 * @param {HTMLElement} element - 模态窗口或触发元素
 */
function closeModal(element) {
    if (!element) {
        document.querySelectorAll('.modal-overlay').forEach(modal => closeModal(modal));
        return;
    }

    const overlay = element.closest ? (element.closest('.modal-overlay') || element) : element;
    if (!overlay || !overlay.parentNode || overlay.classList.contains('is-closing')) return;

    overlay.classList.add('is-closing');

    const index = modalStack.indexOf(overlay);
    if (index > -1) modalStack.splice(index, 1);

    setTimeout(() => {
        if (overlay.parentNode) overlay.remove();
    }, 200);
}

// Esc 关闭最上层弹窗
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modalStack.length) {
        e.preventDefault();
        closeModal(modalStack[modalStack.length - 1]);
    }
});

/**
 * 应用内确认框（替代浏览器原生 confirm）
 * @param {Object} options
 * @param {string} options.title - 标题
 * @param {string} options.text - 说明文字
 * @param {string} [options.confirmText] - 确认按钮文案
 * @param {string} [options.cancelText] - 取消按钮文案
 * @param {boolean} [options.danger] - 是否使用警示色
 * @param {string} [options.note] - 次要备注
 * @returns {Promise<boolean>}
 */
function confirmDialog(options = {}) {
    const {
        title = '确认一下',
        text = '',
        confirmText = '确定',
        cancelText = '再想想',
        danger = false,
        note = ''
    } = options;

    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay confirm-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', title);

        overlay.innerHTML = `
            <div class="modal-content confirm-dialog">
                <div class="confirm-dialog__body">
                    <span class="confirm-dialog__mark" aria-hidden="true">
                        <svg class="icon"><use href="#i-star"></use></svg>
                    </span>
                    <h2 class="confirm-dialog__title">${title}</h2>
                    <p class="confirm-dialog__text">${text}</p>
                    ${note ? `<p class="confirm-dialog__note">${note}</p>` : ''}
                </div>
                <div class="confirm-dialog__actions">
                    <button type="button" class="btn btn-ghost confirm-dialog__cancel">${cancelText}</button>
                    <button type="button" class="btn ${danger ? 'btn-danger' : 'btn-primary'} confirm-dialog__ok">${confirmText}</button>
                </div>
            </div>
        `;

        let settled = false;
        const finish = (value) => {
            if (settled) return;
            settled = true;
            document.removeEventListener('keydown', onKey, true);
            closeModal(overlay);
            resolve(value);
        };

        // Esc 关闭时也要给出结果，否则 await 会一直挂着
        const onKey = (e) => {
            if (e.key === 'Escape') finish(false);
        };
        document.addEventListener('keydown', onKey, true);

        overlay.querySelector('.confirm-dialog__ok').addEventListener('click', () => finish(true));
        overlay.querySelector('.confirm-dialog__cancel').addEventListener('click', () => finish(false));
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) finish(false);
        });

        document.getElementById('modalContainer').appendChild(overlay);
        modalStack.push(overlay);

        requestAnimationFrame(() => {
            const ok = overlay.querySelector('.confirm-dialog__ok');
            if (ok) ok.focus({ preventScroll: true });
        });
    });
}

/**
 * 显示通知消息
 * @param {string} message - 消息内容
 * @param {string} type - 消息类型: success, error, info
 * @param {number} duration - 显示时长(毫秒)
 */
function showNotification(message, type = 'info', duration = 3000) {
    let layer = document.getElementById('toastLayer');
    if (!layer) {
        layer = document.createElement('div');
        layer.id = 'toastLayer';
        layer.className = 'toast-layer';
        layer.setAttribute('aria-live', 'polite');
        document.body.appendChild(layer);
    }

    // 同时最多保留三条
    while (layer.children.length >= 3) {
        layer.removeChild(layer.firstElementChild);
    }

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.setAttribute('role', 'status');
    notification.textContent = message;

    layer.appendChild(notification);

    setTimeout(() => {
        notification.classList.add('is-closing');
        setTimeout(() => notification.remove(), 240);
    }, duration);
}

/**
 * 格式化时间戳
 * @param {number} timestamp - Unix时间戳
 * @returns {string} 格式化的时间字符串
 */
function formatTime(timestamp) {
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diff = now - date;

    // 今天
    if (diff < 86400000 && date.getDate() === now.getDate()) {
        return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }

    // 昨天
    if (diff < 172800000 && date.getDate() === now.getDate() - 1) {
        return '昨天 ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }

    // 更早
    const clock = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    return `${date.getMonth() + 1}月${date.getDate()}日 ${clock}`;
}

/**
 * 当前时间的「时:分」
 */
function nowClock() {
    return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

/**
 * 转义HTML特殊字符
 * @param {string} text - 原始文本
 * @returns {string} 转义后的文本
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

/**
 * 滚动到元素
 * @param {HTMLElement} element - 目标元素
 * @param {boolean} smooth - 是否平滑滚动
 */
function scrollToElement(element, smooth = true) {
    element.scrollIntoView({
        behavior: smooth ? 'smooth' : 'auto',
        block: 'end'
    });
}

/**
 * 防抖函数
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 节流函数
 */
function throttle(func, limit) {
    let inThrottle;
    return function executedFunction(...args) {
        if (!inThrottle) {
            func(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * 深拷贝对象
 */
function deepClone(obj) {
    if (obj === null || typeof obj !== 'object') return obj;
    if (obj instanceof Date) return new Date(obj);
    if (obj instanceof Array) return obj.map(item => deepClone(item));

    const clonedObj = {};
    for (let key in obj) {
        if (obj.hasOwnProperty(key)) {
            clonedObj[key] = deepClone(obj[key]);
        }
    }
    return clonedObj;
}

/**
 * 本地存储操作
 */
const storage = {
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.error('Storage set error:', e);
            return false;
        }
    },

    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (e) {
            console.error('Storage get error:', e);
            return defaultValue;
        }
    },

    remove(key) {
        try {
            localStorage.removeItem(key);
            return true;
        } catch (e) {
            console.error('Storage remove error:', e);
            return false;
        }
    },

    clear() {
        try {
            localStorage.clear();
            return true;
        } catch (e) {
            console.error('Storage clear error:', e);
            return false;
        }
    }
};

/**
 * 获取资源路径(兼容开发/打包环境)
 */
function getResourcePath(path) {
    return path;
}

/**
 * 等待元素出现
 */
function waitForElement(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
        const element = document.querySelector(selector);
        if (element) {
            resolve(element);
            return;
        }

        const observer = new MutationObserver(() => {
            const found = document.querySelector(selector);
            if (found) {
                observer.disconnect();
                resolve(found);
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        setTimeout(() => {
            observer.disconnect();
            reject(new Error(`Element ${selector} not found within ${timeout}ms`));
        }, timeout);
    });
}

/**
 * 复制文本到剪贴板
 */
async function copyToClipboard(text, silent = false) {
    try {
        await navigator.clipboard.writeText(text);
        if (!silent) showNotification('已复制到剪贴板', 'success', 2000);
        return true;
    } catch (e) {
        console.error('Copy failed:', e);
        if (!silent) showNotification('复制失败', 'error', 2000);
        return false;
    }
}

// 导出全局使用
window.utils = {
    createModal,
    closeModal,
    confirmDialog,
    showNotification,
    formatTime,
    nowClock,
    escapeHtml,
    scrollToElement,
    debounce,
    throttle,
    deepClone,
    storage,
    getResourcePath,
    waitForElement,
    copyToClipboard
};
