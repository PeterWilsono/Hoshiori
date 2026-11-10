// ===== 主题管理 - 星织AI助手 =====

// 主题配置：四套印刷品气质
const THEMES = {
    glass: {
        name: 'glass',
        displayName: '夜航',
        latin: 'Nocturne',
        description: '墨蓝夜空 · 月光石',
        swatches: ['#0a0d14', '#a9bdf0', '#e6c39b']
    },
    clay: {
        name: 'clay',
        displayName: '朝霧',
        latin: 'Asagiri',
        description: '苔原晨雾 · 暖陶',
        swatches: ['#e9ede3', '#3f7358', '#a86a4c']
    },
    fresh: {
        name: 'fresh',
        displayName: '纸白',
        latin: 'Paper',
        description: '象牙纸 · 墨蓝字',
        swatches: ['#f7f4ec', '#2e4b76', '#a3653a']
    },
    dark: {
        name: 'dark',
        displayName: '曜石',
        latin: 'Obsidian',
        description: '曜石黑 · 暖金',
        swatches: ['#0a0a0b', '#d7b689', '#f0ede7']
    }
};

// 当前主题
let currentTheme = 'glass';

/**
 * 初始化主题系统
 */
async function initTheme() {
    try {
        const savedTheme = await eel.get_current_theme()();
        if (savedTheme && THEMES[savedTheme]) {
            currentTheme = savedTheme;
        }
    } catch (e) {
        console.log('Using default theme');
    }

    applyTheme(currentTheme, true);
}

/**
 * 应用主题
 * @param {string} themeName - 主题名称
 * @param {boolean} silent - 是否跳过过渡动效
 */
function applyTheme(themeName, silent = false) {
    if (!THEMES[themeName]) {
        console.error('Unknown theme:', themeName);
        return;
    }

    currentTheme = themeName;
    document.body.setAttribute('data-theme', themeName);

    if (!silent) {
        document.body.classList.add('theme-transition');
        setTimeout(() => {
            document.body.classList.remove('theme-transition');
        }, 560);
    }

    if (typeof eel !== 'undefined') {
        eel.save_theme(themeName);
    }

    console.log(`Theme → ${THEMES[themeName].displayName}`);
}

/**
 * 打开主题选择器
 */
function openThemeSelector() {
    const themesHtml = Object.values(THEMES).map(theme => `
        <div class="theme-card ${currentTheme === theme.name ? 'active' : ''}"
             data-theme-name="${theme.name}"
             onclick="selectTheme('${theme.name}', this)">
            <div class="theme-icon">
                ${theme.swatches.map(c => `<span style="background:${c}"></span>`).join('')}
            </div>
            <div class="theme-name">${theme.displayName} <em>${theme.latin}</em></div>
            <div class="theme-description">${theme.description}</div>
        </div>
    `).join('');

    createModal(
        '选择气质',
        `<div class="theme-grid">${themesHtml}</div>`,
        [
            { text: '完成', style: 'btn-ghost', onClick: () => {} }
        ]
    );
}

/**
 * 选择主题
 * @param {string} themeName
 * @param {HTMLElement} el
 */
function selectTheme(themeName, el) {
    applyTheme(themeName);

    document.querySelectorAll('.theme-card').forEach(card => card.classList.remove('active'));
    if (el) el.classList.add('active');

    showNotification(`已换成「${THEMES[themeName].displayName}」`, 'success', 1800);
}

/**
 * 获取当前主题
 */
function getCurrentTheme() {
    return currentTheme;
}

/**
 * 从Python接收主题更新
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
