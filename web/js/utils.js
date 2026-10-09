// ===== 工具函数 - 星织AI助手 =====

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
    overlay.setAttribute('data-modal-id', Date.now()); // 添加唯一标识

    const modal = document.createElement('div');
    modal.className = 'modal-content';

    // 头部
    const header = document.createElement('div');
    header.className = 'modal-header';
    header.innerHTML = `
        <h2 class="modal-title">${title}</h2>
        <button class="modal-close" onclick="closeModal(this)">✖</button>
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
        if (e.target === overlay) {
            closeModal(overlay);
        }
    });
    
    // 阻止模态框内容的点击事件冒泡
    modal.addEventListener('click', (e) => {
        e.stopPropagation();
    });

    return overlay;
}

/**
 * 关闭模态窗口
 * @param {HTMLElement} element - 模态窗口或触发元素
 */
function closeModal(element) {
    if (!element) {
        // 如果没有传入元素，关闭所有模态框
        const allModals = document.querySelectorAll('.modal-overlay');
        allModals.forEach(modal => {
            modal.style.animation = 'fadeOut 0.3s ease';
            setTimeout(() => modal.remove(), 300);
        });
        return;
    }
    
    const overlay = element.closest('.modal-overlay') || element;
    if (overlay && overlay.parentNode) {
        overlay.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => {
            if (overlay.parentNode) {
                overlay.remove();
            }
        }, 300);
    }
}

/**
 * 显示通知消息
 * @param {string} message - 消息内容
 * @param {string} type - 消息类型: success, error, info
 * @param {number} duration - 显示时长(毫秒)
 */
function showNotification(message, type = 'info', duration = 3000) {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
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
    return date.toLocaleDateString('zh-CN') + ' ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

/**
 * 转义HTML特殊字符
 * @param {string} text - 原始文本
 * @returns {string} 转义后的文本
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
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
 * @param {Function} func - 要防抖的函数
 * @param {number} wait - 等待时间(毫秒)
 * @returns {Function} 防抖后的函数
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
 * @param {Function} func - 要节流的函数
 * @param {number} limit - 间隔时间(毫秒)
 * @returns {Function} 节流后的函数
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
 * @param {*} obj - 要拷贝的对象
 * @returns {*} 拷贝后的对象
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
 * @param {string} path - 相对路径
 * @returns {string} 绝对路径
 */
function getResourcePath(path) {
    // Eel会自动处理路径
    return path;
}

/**
 * 等待元素出现
 * @param {string} selector - CSS选择器
 * @param {number} timeout - 超时时间(毫秒)
 * @returns {Promise<HTMLElement>}
 */
function waitForElement(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
        const element = document.querySelector(selector);
        if (element) {
            resolve(element);
            return;
        }

        const observer = new MutationObserver(() => {
            const element = document.querySelector(selector);
            if (element) {
                observer.disconnect();
                resolve(element);
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
 * @param {string} text - 要复制的文本
 * @returns {boolean} 是否成功
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('已复制到剪贴板', 'success', 2000);
        return true;
    } catch (e) {
        console.error('Copy failed:', e);
        showNotification('复制失败', 'error', 2000);
        return false;
    }
}

// 导出全局使用
window.utils = {
    createModal,
    closeModal,
    showNotification,
    formatTime,
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
