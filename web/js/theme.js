// ===== 主题管理 - 星织AI助手 =====

// 主题配置
const THEMES = {
    glass: {
        name: 'glass',
        displayName: '🔮 幻境玻璃',
        icon: '🔮',
        description: '科幻透明光影'
    },
    clay: {
        name: 'clay',
        displayName: '☁️ 软萌黏土',
        icon: '☁️',
        description: '新拟态3D质感'
    },
    fresh: {
        name: 'fresh',
        displayName: '🍃 清新日系',
        icon: '🍃',
        description: '极简留白纸质'
    },
    dark: {
        name: 'dark',
        displayName: '🌙 深邃暗夜',
        icon: '🌙',
        description: '赛博朋克霓虹'
    }
};

// 当前主题
let currentTheme = 'glass';

/**
 * 初始化主题系统
 */
async function initTheme() {
    // 从Python获取当前主题
    try {
        const savedTheme = await eel.get_current_theme()();
        if (savedTheme && THEMES[savedTheme]) {
            currentTheme = savedTheme;
        }
    } catch (e) {
        console.log('Using default theme');
    }

    applyTheme(currentTheme);
}

/**
 * 应用主题
 * @param {string} themeName - 主题名称
 */
function applyTheme(themeName) {
    if (!THEMES[themeName]) {
        console.error('Unknown theme:', themeName);
        return;
    }

    currentTheme = themeName;
    document.body.setAttribute('data-theme', themeName);

    // 添加主题切换过渡效果
    document.body.classList.add('theme-transition');
    setTimeout(() => {
        document.body.classList.remove('theme-transition');
    }, 800);

    // 保存到Python
    if (typeof eel !== 'undefined') {
        eel.save_theme(themeName);
    }

    console.log(`Theme changed to: ${THEMES[themeName].displayName}`);
}

/**
 * 打开主题选择器
 */
function openThemeSelector() {
    const themesHtml = Object.values(THEMES).map(theme => `
        <div class="theme-card ${currentTheme === theme.name ? 'active' : ''}" 
             onclick="selectTheme('${theme.name}')">
            <div class="theme-icon">${theme.icon}</div>
            <div class="theme-name">${theme.displayName}</div>
            <div class="theme-description">${theme.description}</div>
        </div>
    `).join('');

    createModal(
        '🎨 主题选择',
        `<div class="theme-grid">${themesHtml}</div>`,
        [
            {
                text: '关闭',
                style: 'btn-ghost',
                onClick: () => { }
            }
        ]
    );
}

/**
 * 选择主题
 * @param {string} themeName - 主题名称
 */
function selectTheme(themeName) {
    applyTheme(themeName);

    // 更新主题卡片active状态
    document.querySelectorAll('.theme-card').forEach(card => {
        card.classList.remove('active');
    });
    event.currentTarget.classList.add('active');

    showNotification(`已切换到 ${THEMES[themeName].displayName}`, 'success', 2000);
}

/**
 * 获取当前主题
 * @returns {string} 当前主题名称
 */
function getCurrentTheme() {
    return currentTheme;
}

/**
 * 从Python接收主题更新
 * @param {string} themeName - 主题名称
 */
eel.expose(applyThemeFromPython);
function applyThemeFromPython(themeName) {
    applyTheme(themeName);
}

// 导出
window.themeManager = {
    init: initTheme,
    apply: applyTheme,
    getCurrent: getCurrentTheme,
    openSelector: openThemeSelector
};
