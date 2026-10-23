// ===== 主程序 - 星织AI助手 =====
console.log('🎮 Main.js 加载 v16');

// ===== 🔥 防止刷新保护 =====
(function() {
    // 禁用右键菜单（防止右键刷新）
    document.addEventListener('contextmenu', function(e) {
        e.preventDefault();
        console.log('⚠️ 右键菜单已禁用（防止意外刷新）');
        return false;
    });
    
    // 禁用F5和Ctrl+R刷新
    document.addEventListener('keydown', function(e) {
        // F5
        if (e.key === 'F5' || e.keyCode === 116) {
            e.preventDefault();
            console.log('⚠️ F5刷新已禁用（防止断开连接）');
            showNotification('⚠️ 请勿刷新页面，这会断开与程序的连接', 'error', 3000);
            return false;
        }
        // Ctrl+R 或 Cmd+R
        if ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.keyCode === 82)) {
            e.preventDefault();
            console.log('⚠️ Ctrl+R刷新已禁用（防止断开连接）');
            showNotification('⚠️ 请勿刷新页面，这会断开与程序的连接', 'error', 3000);
            return false;
        }
    });
    
    // 警告用户不要关闭窗口
    window.addEventListener('beforeunload', function(e) {
        // 注意：现代浏览器会忽略自定义消息，只显示默认提示
        const message = '确定要关闭星织吗？';
        e.returnValue = message;
        return message;
    });
    
    console.log('✅ 防刷新保护已启用');
})();

// ===== 🔥 缓存破坏系统 - 防止浏览器加载旧版本 =====
(function() {
    const STORAGE_KEY = 'hoshiori_app_version';
    const currentVersion = new URLSearchParams(window.location.search).get('v') || 
                          document.querySelector('script[src*="main.js"]')?.src.match(/v=(\d+)/)?.[1] || 
                          Date.now().toString();
    
    const storedVersion = localStorage.getItem(STORAGE_KEY);
    
    console.log(`📦 版本检查: 当前=${currentVersion}, 缓存=${storedVersion}`);
    
    // 如果版本不匹配，强制刷新
    if (storedVersion && storedVersion !== currentVersion) {
        console.warn('⚠️ 检测到版本更新，清除缓存并刷新...');
        localStorage.setItem(STORAGE_KEY, currentVersion);
        
        // 清除所有缓存
        if ('caches' in window) {
            caches.keys().then(names => {
                names.forEach(name => caches.delete(name));
            });
        }
        
        // 强制刷新（绕过缓存）
        window.location.reload(true);
        return;
    }
    
    // 保存当前版本
    localStorage.setItem(STORAGE_KEY, currentVersion);
    console.log('✅ 版本验证通过');
})();

// ===== 🔥 SDK 加载检测增强 =====
window.sdkLoadStatus = {
    pixi: false,
    cubism: false,
    core: false
};

// 检测 PIXI 加载
if (typeof PIXI !== 'undefined') {
    window.sdkLoadStatus.pixi = true;
    console.log('✅ PIXI 已加载');
} else {
    console.error('❌ PIXI 未加载 - 检查网络连接或CDN可用性');
}

// 延迟检测其他SDK
setTimeout(() => {
    if (typeof PIXI !== 'undefined' && PIXI.live2d) {
        window.sdkLoadStatus.cubism = true;
        console.log('✅ Cubism SDK 已加载');
    } else {
        console.error('❌ Cubism SDK 未加载');
    }
    
    if (typeof Live2DCubismCore !== 'undefined') {
        window.sdkLoadStatus.core = true;
        console.log('✅ Cubism Core 已加载');
    } else {
        console.error('❌ Cubism Core 未加载');
    }
}, 1000);

// ===== Live2D 动态立绘系统 =====
const Live2DManager = {
    model: null,
    app: null,
    canvas: null,
    isInitialized: false,
    currentMood: 'neutral',
    container: null,
    currentModelId: 'yumi',
    modelBasePath: 'assets/live2d/live2d_modules-master/',
    lookTarget: { x: 0, y: 0 },
    currentLook: { x: 0, y: 0 },
    timers: [],
    
    // 可用模型配置 - Cubism 4 格式
    availableModels: {
        'yumi': { 
            name: '优米 (Yumi)', 
            path: 'yumi/yumi.model3.json',
            expressions: { neutral: null, happy: '星星眼.exp3.json', sad: '泪汪汪.exp3.json', angry: '黑脸.exp3.json', shy: '猫猫嘴.exp3.json', surprised: '爱心眼.exp3.json' }
        },
        'nahida': { 
            name: '纳西妲 (Nahida)', 
            path: 'nahida/nahida.model3.json',
            expressions: { neutral: null, happy: '发光.exp3.json', sad: '泪.exp3.json', angry: '生气.exp3.json', shy: '脸红.exp3.json', surprised: '星星.exp3.json' }
        },
        'murasame': { 
            name: '村雨浴衣 (Murasame)', 
            path: 'Murasame_Yukata/Murasame_Yukata.model3.json',
            expressions: { neutral: null, happy: '03_GaoGuang.exp3.json', sad: '01_LianHei.exp3.json', angry: '07_HengYan.exp3.json', shy: '05_LianHong.exp3.json', surprised: '08_qYan.exp3.json' }
        },
    },
    
    getModelPath() { 
        return this.modelBasePath + this.availableModels[this.currentModelId].path; 
    },
    
    getAvailableModels() {
        return Object.entries(this.availableModels).map(([id, cfg]) => ({ 
            id, name: cfg.name, isCurrent: id === this.currentModelId 
        }));
    },
    
    async init() {
        console.log('🎭 Live2D初始化...');
        this.container = document.querySelector('.avatar-container');
        if (!this.container) return false;
        
        const saved = localStorage.getItem('live2d_model');
        if (saved && this.availableModels[saved]) this.currentModelId = saved;
        console.log('🔗 模型:', this.getModelPath());
        
        const sdkOk = await this.waitSDK();
        if (!sdkOk) { 
            console.warn('⚠️ SDK未就绪');
            this.fallback(); 
            return false; 
        }
        
        try {
            const res = await fetch(this.getModelPath());
            if (!res.ok) { 
                console.warn('⚠️ 模型文件不存在'); 
                this.fallback(); 
                return false; 
            }
        } catch(e) { 
            this.fallback(); 
            return false; 
        }
        
        try {
            await this.initPixi();
            await this.loadModel();
            this.setupInteraction();
            this.startIdleBehavior();
            this.isInitialized = true;
            console.log('✅ Live2D就绪');
            return true;
        } catch(e) { 
            console.error('❌ Live2D加载失败:', e); 
            this.fallback(); 
            return false; 
        }
    },
    
    async waitSDK() {
        console.log('⏳ 等待Live2D SDK...');
        
        // 先检查基础依赖
        if (typeof PIXI === 'undefined') {
            console.error('❌ PIXI未加载 - 可能原因:');
            console.error('  1. CDN连接超时（网络问题）');
            console.error('  2. 浏览器缓存了旧版本');
            console.error('  3. 防火墙/代理阻止了CDN访问');
            console.error('💡 解决方案: 检查网络连接，或使用本地SDK文件');
            return false;
        }
        
        // 等待 Live2D 插件加载
        for (let i = 0; i < 100; i++) {
            if (typeof PIXI !== 'undefined' && PIXI.live2d && PIXI.live2d.Live2DModel) {
                console.log('✅ SDK就绪');
                return true;
            }
            await new Promise(r => setTimeout(r, 100));
        }
        
        console.error('❌ SDK加载超时');
        console.error('当前状态:', {
            PIXI: typeof PIXI !== 'undefined',
            'PIXI.live2d': typeof PIXI !== 'undefined' && !!PIXI.live2d,
            'Live2DModel': typeof PIXI !== 'undefined' && PIXI.live2d && !!PIXI.live2d.Live2DModel
        });
        return false;
    },
    
    async initPixi() {
        const img = document.getElementById('avatarImage');
        if (img) img.style.display = 'none';
        
        const oldCanvas = document.getElementById('live2d-canvas');
        if (oldCanvas) oldCanvas.remove();
        
        this.canvas = document.createElement('canvas');
        this.canvas.id = 'live2d-canvas';
        this.canvas.style.cssText = 'width:100%;height:100%;position:absolute;top:0;left:0;';
        this.container.appendChild(this.canvas);
        
        if (this.app) this.app.destroy(true);
        this.app = new PIXI.Application({ view: this.canvas, backgroundAlpha: 0, resizeTo: this.container });
    },
    
    async loadModel() {
        if (this.model) { 
            this.app.stage.removeChild(this.model); 
            this.model = null;
        }
        
        const modelPath = this.getModelPath();
        console.log('📦 加载模型:', modelPath);
        this.model = await PIXI.live2d.Live2DModel.from(modelPath);
        this.model.anchor.set(0.5, 0.5);
        this.model.position.set(this.app.screen.width/2, this.app.screen.height/2);
        const s = Math.min(this.app.screen.width/this.model.width, this.app.screen.height/this.model.height) * 0.8;
        this.model.scale.set(s);
        this.app.stage.addChild(this.model);
        console.log('✅ 模型加载完成');
    },
    
    async switchModel(id) {
        if (!this.availableModels[id]) {
            console.error('❌ 模型不存在:', id);
            return false;
        }
        
        const modelPath = this.modelBasePath + this.availableModels[id].path;
        
        try {
            const res = await fetch(modelPath);
            if (!res.ok) {
                console.error('❌ 模型文件不存在:', modelPath);
                return false;
            }
        } catch(e) {
            console.error('❌ 无法访问模型文件:', e);
            return false;
        }
        
        this.currentModelId = id;
        localStorage.setItem('live2d_model', id);
        
        try { 
            await this.loadModel(); 
            this.startIdleBehavior();
            console.log('✅ 模型切换成功:', id);
            return true; 
        } catch(e) { 
            console.error('❌ 模型加载失败:', e);
            return false; 
        }
    },

    setupInteraction() {
        this.container.onclick = () => { 
            this.setExpression('happy'); 
            this.showEffect('heart'); 
            setTimeout(() => this.setExpression(this.currentMood), 3000); 
        };
    },
    
    startIdleBehavior() {
        this.timers.forEach(t => clearTimeout(t));
        this.timers = [];
        
        const updateLook = () => {
            if (this.model && this.model.internalModel && this.model.internalModel.coreModel) {
                this.currentLook.x += (this.lookTarget.x - this.currentLook.x) * 0.05;
                this.currentLook.y += (this.lookTarget.y - this.currentLook.y) * 0.05;
                
                try {
                    const c = this.model.internalModel.coreModel;
                    c.setParameterValueById('ParamAngleX', this.currentLook.x * 15);
                    c.setParameterValueById('ParamAngleY', this.currentLook.y * 10);
                    c.setParameterValueById('ParamEyeBallX', this.currentLook.x * 0.5);
                    c.setParameterValueById('ParamEyeBallY', this.currentLook.y * 0.5);
                } catch(e) {}
            }
            requestAnimationFrame(updateLook);
        };
        requestAnimationFrame(updateLook);
        
        const randomLook = () => {
            this.lookTarget.x = (Math.random() - 0.5) * 1.2;
            this.lookTarget.y = (Math.random() - 0.5) * 0.8;
            const delay = 3000 + Math.random() * 5000;
            const timer = setTimeout(randomLook, delay);
            this.timers.push(timer);
        };
        randomLook();
    },
    
    setExpression(name) {
        if (!this.model) return;
        const cfg = this.availableModels[this.currentModelId];
        if (!cfg || !cfg.expressions) return;
        const exp = cfg.expressions[name];
        if (exp) try { this.model.expression(exp); } catch(e) {}
    },
    
    updateByPAD(pad) {
        const p = pad.pleasure, a = pad.arousal, d = pad.dominance;
        let mood = 'neutral';
        if (p > 0.5 && a > 0.3) mood = 'happy';
        else if (p < -0.3 && a < 0) mood = 'sad';
        else if (p < -0.3 && a > 0.5) mood = 'angry';
        else if (p > 0 && d < -0.3) mood = 'shy';
        else if (a > 0.6) mood = 'surprised';
        if (mood !== this.currentMood) { this.currentMood = mood; this.setExpression(mood); }
    },
    
    triggerByContent(text) {
        if (/喜欢|爱/.test(text)) { this.setExpression('happy'); this.showEffect('heart'); }
        else if (/害羞|脸红/.test(text)) { this.setExpression('shy'); this.showEffect('blush'); }
        else if (/生气/.test(text)) { this.setExpression('angry'); }
        else if (/难过|伤心/.test(text)) { this.setExpression('sad'); }
    },
    
    startTalking(dur) {
        if (!this.model) return;
        let open = false;
        const iv = setInterval(() => {
            try { this.model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', open ? 0.8 : 0.2); open = !open; } catch(e) {}
        }, 150);
        setTimeout(() => { clearInterval(iv); try { this.model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', 0); } catch(e) {} }, dur || 3000);
    },
    
    showEffect(name) {
        const emojis = { heart: '❤️', sparkle: '✨', blush: '😳', tears: '😢', anger: '💢' };
        const el = document.createElement('div');
        el.textContent = emojis[name] || '✨';
        el.style.cssText = `position:absolute;font-size:3rem;pointer-events:none;z-index:100;animation:effectFloat 2s forwards;left:${30+Math.random()*40}%;top:${20+Math.random()*30}%;`;
        this.container.appendChild(el);
        setTimeout(() => el.remove(), 2000);
    },
    
    updateMood(mood) { 
        if (mood !== this.currentMood) { 
            this.currentMood = mood; 
            this.setExpression(mood); 
        } 
    },
    
    fallback() {
        console.log('🎨 CSS降级');
        const img = document.getElementById('avatarImage');
        if (img) { img.style.display = 'block'; img.classList.add('breathing'); }
        this.isInitialized = true;
    }
};

// 注入CSS动画
(function() {
    const s = document.createElement('style');
    s.textContent = '@keyframes effectFloat{0%{opacity:1;transform:translateY(0) scale(.5)}50%{transform:translateY(-30px) scale(1.2)}100%{opacity:0;transform:translateY(-60px)}}.breathing{animation:breathing 3s ease-in-out infinite}@keyframes breathing{0%,100%{transform:scale(1)}50%{transform:scale(1.02) translateY(-5px)}}';
    document.head.appendChild(s);
})();

window.avatarAnimationManager = Live2DManager;

// 全局状态
let appState = {
    voiceEnabled: false,
    avatarVisible: true,
    modelMode: 'local',
    affection: 50,
    mood: 'neutral'
};


// 应用初始化
async function initApp() {
    console.log('🚀 星织AI助手启动中...');
    try {
        await themeManager.init();
        chatManager.init();
        await loadAppState();
        await Live2DManager.init();
        console.log('✅ 初始化完成');
    } catch (e) {
        console.error('❌ 初始化失败:', e);
        showNotification('应用初始化失败', 'error');
    }
}

async function loadAppState() {
    try {
        const state = await eel.get_app_state()();
        console.log('📥 从后端获取的状态:', state);
        if (state) {
            appState = { ...appState, ...state };
            console.log('💾 更新后的appState:', appState);
            updateUIFromState();
        }
    } catch (e) {
        console.error('Load state error:', e);
    }
}

function updateUIFromState() {
    const modeButton = document.getElementById('modeButton');
    if (modeButton) {
        const mode = appState.modelMode || 'local';
        modeButton.textContent = mode === 'local' ? '🏠 本地' : '☁️ 在线';
    }

    const voiceButton = document.getElementById('voiceButton');
    if (voiceButton) {
        voiceButton.textContent = appState.voiceEnabled ? '🔊 语音开启' : '🔇 语音关闭';
    }

    const avatarToggle = document.getElementById('avatarToggle');
    if (avatarToggle) {
        avatarToggle.textContent = appState.avatarVisible ? '🖼 显示立绘' : '🖼 隐藏立绘';
    }

    const avatarSection = document.querySelector('.avatar-section');
    if (avatarSection) {
        if (appState.avatarVisible) {
            avatarSection.classList.remove('hidden');
        } else {
            avatarSection.classList.add('hidden');
        }
    }

    updateAffection(appState.affection);
    updateMood(appState.mood);
}

eel.expose(updateAvatarDisplay);
function updateAvatarDisplay(mood) {
    appState.mood = mood;
    if (Live2DManager.isInitialized) {
        Live2DManager.updateMood(mood);
    }
}

eel.expose(updateAffection);
function updateAffection(value) {
    appState.affection = value;
    const affectionValue = document.getElementById('affectionValue');
    const affectionBar = document.getElementById('affectionBar');

    if (affectionValue) {
        affectionValue.textContent = value;
        if (value >= 70) {
            affectionValue.style.color = 'var(--affection-high, #a78bfa)';
        } else if (value >= 40) {
            affectionValue.style.color = 'var(--affection-mid, #f59e0b)';
        } else {
            affectionValue.style.color = 'var(--affection-low, #ef4444)';
        }
    }

    if (affectionBar) {
        affectionBar.style.width = `${value}%`;
        affectionBar.classList.add('progress-animated');
        setTimeout(() => affectionBar.classList.remove('progress-animated'), 1500);
    }
}

eel.expose(updateMood);
function updateMood(mood) {
    appState.mood = mood;
    const moodLabel = document.getElementById('moodLabel');
    if (moodLabel) {
        const moodTexts = {
            'neutral': '情绪 · 平静',
            'happy': '情绪 · 开心',
            'angry': '情绪 · 生气',
            'sad': '情绪 · 悲伤',
            'shy': '情绪 · 害羞'
        };
        moodLabel.textContent = moodTexts[mood] || '情绪 · 平静';
    }
    if (Live2DManager.isInitialized) {
        Live2DManager.updateMood(mood);
    }
}

async function toggleVoice() {
    try {
        const newState = await eel.toggle_voice_from_web()();
        appState.voiceEnabled = newState;

        const voiceButton = document.getElementById('voiceButton');
        if (voiceButton) {
            voiceButton.textContent = newState ? '🔊 语音开启' : '🔇 语音关闭';
        }
        
        const settingVoiceBtn = document.getElementById('settingVoiceBtn');
        if (settingVoiceBtn) {
            settingVoiceBtn.textContent = newState ? '🔊 语音: 开启' : '🔇 语音: 关闭';
        }

        showNotification(newState ? '语音已开启' : '语音已关闭', 'success', 2000);
    } catch (e) {
        console.error('Toggle voice error:', e);
        showNotification('语音切换失败', 'error');
    }
}

async function toggleModelMode() {
    try {
        const result = await eel.toggle_model_mode_from_web()();
        appState.modelMode = result.mode;

        const modeButton = document.getElementById('modeButton');
        if (modeButton) {
            modeButton.textContent = result.mode === 'local' ? '🏠 本地' : '☁️ 在线';
        }

        const currentModeName = result.mode === 'local' ? '🏠 本地模式' : '☁️ 在线模式';
        showNotification(`已切换到 ${currentModeName}\n当前模型: ${result.model}`, 'info', 4000);
    } catch (e) {
        console.error('Toggle model mode error:', e);
        showNotification('切换失败', 'error');
    }
}

function toggleAvatarVisibility() {
    appState.avatarVisible = !appState.avatarVisible;

    const avatarSection = document.querySelector('.avatar-section');
    const avatarToggle = document.getElementById('avatarToggle');

    if (appState.avatarVisible) {
        avatarSection.classList.remove('hidden');
        if (avatarToggle) avatarToggle.textContent = '🖼 显示立绘';
    } else {
        avatarSection.classList.add('hidden');
        if (avatarToggle) avatarToggle.textContent = '🖼 隐藏立绘';
    }

    if (typeof eel !== 'undefined') {
        eel.save_avatar_visibility(appState.avatarVisible);
    }
}


async function openSettings() {
    try {
        // 先关闭已存在的模态框
        const existingModals = document.querySelectorAll('.modal-overlay');
        existingModals.forEach(modal => modal.remove());
        
        const settings = await eel.get_settings()();
        const ttsVoices = await eel.get_tts_voices()();
        const currentVoice = await eel.get_current_tts_voice()();
        const apiPresets = await eel.get_api_presets()();
        
        let voiceOptions = '';
        for (const voice of ttsVoices) {
            const selected = voice.id === currentVoice ? 'selected' : '';
            voiceOptions += `<option value="${voice.id}" ${selected}>${voice.name}</option>`;
        }
        
        // 构建API提供商选项
        let providerOptions = '';
        for (const [key, preset] of Object.entries(apiPresets)) {
            const selected = settings.api_provider === key ? 'selected' : '';
            providerOptions += `<option value="${key}" ${selected}>${preset.name}</option>`;
        }
        
        // 构建模型选项（根据当前提供商）
        const currentProvider = settings.api_provider || 'mimo';
        const currentPreset = apiPresets[currentProvider];
        let modelOptions = '';
        
        if (currentPreset && currentPreset.models && currentPreset.models.length > 0) {
            for (const model of currentPreset.models) {
                const modelValue = typeof model === 'string' ? model : model.value;
                const modelLabel = typeof model === 'string' ? model : model.label;
                const selected = settings.model === modelValue ? 'selected' : '';
                modelOptions += `<option value="${modelValue}" ${selected}>${modelLabel}</option>`;
            }
        }
        
        // 构建思考模式选项
        let thinkingOptions = '';
        if (currentPreset && currentPreset.thinking_modes && currentPreset.thinking_modes.length > 0) {
            for (const mode of currentPreset.thinking_modes) {
                const selected = settings.thinking_mode === mode.value ? 'selected' : '';
                thinkingOptions += `<option value="${mode.value}" ${selected}>${mode.label}</option>`;
            }
        }

        const settingsHtml = `
            <div class="settings-container">
                <div class="settings-section">
                    <h3 class="settings-section-title">✨ 基础功能</h3>
                    <div class="settings-grid">
                        <button class="btn btn-outline" id="settingVoiceBtn" onclick="toggleVoice(); updateSettingsUI();">
                            ${appState.voiceEnabled ? '🔊 语音: 开启' : '🔇 语音: 关闭'}
                        </button>
                        <button class="btn btn-outline" id="settingAvatarBtn" onclick="toggleAvatarVisibility(); updateSettingsUI();">
                            ${appState.avatarVisible ? '🖼 立绘: 显示' : '🖼 立绘: 隐藏'}
                        </button>
                    </div>
                    <div class="form-group" style="margin-top: 10px;">
                        <label class="form-label">🎤 TTS声音 (Edge-TTS)</label>
                        <select class="form-input" id="settingTTSVoice" onchange="changeTTSVoice(this.value)">
                            ${voiceOptions}
                        </select>
                    </div>
                </div>
                <div class="settings-section">
                    <h3 class="settings-section-title">🛠 工具箱</h3>
                    <div class="settings-grid">
                        <button class="btn btn-ghost" onclick="editRole(); closeModal(this);">🎭 角色设定</button>
                        <button class="btn btn-ghost" onclick="openThemeSelector(); closeModal(this);">🌈 主题切换</button>
                    </div>
                </div>
                <div class="settings-section">
                    <h3 class="settings-section-title">🤖 模型配置</h3>
                    <div class="form-group">
                        <label class="form-label">运行模式</label>
                        <div style="display: flex; gap: 10px; margin-bottom: 10px;">
                            <button class="btn ${settings.model_mode === 'local' ? 'btn-primary' : 'btn-outline'}" 
                                onclick="if(appState.modelMode !== 'local') toggleModelMode(); closeModal(this); setTimeout(openSettings, 500);">
                                🏠 本地模式 (LM Studio)
                            </button>
                            <button class="btn ${settings.model_mode === 'online' ? 'btn-primary' : 'btn-outline'}" 
                                onclick="if(appState.modelMode !== 'online') toggleModelMode(); closeModal(this); setTimeout(openSettings, 500);">
                                ☁️ 在线模式 (API)
                            </button>
                        </div>
                        <input type="hidden" id="settingModelMode" value="${settings.model_mode}">
                    </div>
                    
                    ${settings.model_mode === 'online' ? `
                    <div class="form-group">
                        <label class="form-label">🌐 API提供商</label>
                        <select class="form-input" id="settingApiProvider" onchange="handleProviderChange(this.value)">
                            ${providerOptions}
                        </select>
                        <p class="form-hint" style="margin-top: 5px; font-size: 12px; color: var(--text-secondary);">
                            💡 接入地址由系统自动配置，你只需填入下方 API Key 即可
                        </p>
                    </div>
                    ` : ''}
                    
                    <div class="form-group">
                        <label class="form-label">API密钥 (Key)</label>
                        <input type="password" class="form-input" id="settingApiKey" value="${settings.api_key || ''}" placeholder="sk-..." autocomplete="off">
                        <p class="form-hint" style="margin-top: 5px; font-size: 12px; color: var(--text-secondary);">
                            ${settings.model_mode === 'online'
                                ? '🔑 填入你申请的 API Key（DeepSeek 或 MiMo 平台）后保存即可使用'
                                : '本地模式无需真实密钥'}
                        </p>
                    </div>
                    <div class="form-group">
                        <label class="form-label">模型名称 (Model)</label>
                        ${settings.model_mode === 'online' && modelOptions ? `
                        <select class="form-input" id="settingModel">
                            ${modelOptions}
                        </select>
                        ` : `
                        <input type="text" class="form-input" id="settingModel" value="${settings.model || ''}" placeholder="qwen2.5-7b-instruct">
                        `}
                    </div>
                    
                    ${settings.model_mode === 'online' && thinkingOptions ? `
                    <div class="form-group">
                        <label class="form-label">🧠 深度思考模式</label>
                        <select class="form-input" id="settingThinkingMode">
                            ${thinkingOptions}
                        </select>
                        <p class="form-hint" style="margin-top: 5px; font-size: 12px; color: var(--text-secondary);">
                            💡 开启深度思考：回答更准确但速度较慢，费用较高
                        </p>
                    </div>
                    ` : ''}
                    
                    ${settings.model_mode === 'online' && currentPreset && currentPreset.supports_web_search ? `
                    <div class="form-group">
                        <label class="form-label">🌐 联网搜索</label>
                        <select class="form-input" id="settingWebSearch">
                            <option value="false" ${!settings.web_search_enabled ? 'selected' : ''}>关闭联网搜索</option>
                            <option value="true" ${settings.web_search_enabled ? 'selected' : ''}>开启联网搜索</option>
                        </select>
                        <p class="form-hint" style="margin-top: 5px; font-size: 12px; color: var(--text-secondary);">
                            🔍 开启后AI可以搜索最新信息，但会增加响应时间和费用
                        </p>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;

        const modalOverlay = createModal('⚙ 全局设置', settingsHtml, [
            { text: '保存配置', style: 'btn-primary', onClick: saveSettings },
            { text: '关闭', style: 'btn-ghost', onClick: () => {} }
        ]);
        
        // 阻止点击模态框内容时关闭
        const modalContent = modalOverlay.querySelector('.modal-content');
        if (modalContent) {
            modalContent.addEventListener('click', (e) => {
                e.stopPropagation();
            });
        }

        window.updateSettingsUI = () => {
            const voiceBtn = document.getElementById('settingVoiceBtn');
            const avatarBtn = document.getElementById('settingAvatarBtn');
            if (voiceBtn) voiceBtn.textContent = appState.voiceEnabled ? '🔊 语音: 开启' : '🔇 语音: 关闭';
            if (avatarBtn) avatarBtn.textContent = appState.avatarVisible ? '🖼 立绘: 显示' : '🖼 立绘: 隐藏';
            updateUIFromState();
        };
        
        // 处理提供商切换
        window.handleProviderChange = async (provider) => {
            console.log('切换API提供商:', provider);
            const success = await eel.apply_api_preset(provider)();
            if (success) {
                // 重新加载设置以更新界面
                closeModal(modalOverlay);
                setTimeout(openSettings, 300);
                showNotification(`已切换到 ${apiPresets[provider].name}`, 'success', 2000);
            }
        };
    } catch (e) {
        console.error('Open settings error:', e);
        showNotification('加载设置失败', 'error');
    }
}

async function saveSettings() {
    try {
        // 获取模型值（可能是select或input）
        const modelElement = document.getElementById('settingModel');
        const modelValue = modelElement ? (modelElement.value || '') : '';
        
        // 获取思考模式（如果存在）
        const thinkingElement = document.getElementById('settingThinkingMode');
        const thinkingValue = thinkingElement ? thinkingElement.value : 'disabled';
        
        // 获取联网搜索（如果存在）
        const webSearchElement = document.getElementById('settingWebSearch');
        const webSearchValue = webSearchElement ? (webSearchElement.value === 'true') : false;
        
        // 提供商下拉仅在线模式存在；本地模式不覆盖提供商配置
        const providerElement = document.getElementById('settingApiProvider');
        
        const settings = {
            model_mode: document.getElementById('settingModelMode').value,
            api_provider: providerElement ? providerElement.value : undefined,
            api_key: document.getElementById('settingApiKey')?.value || '',
            model: modelValue,
            thinking_mode: thinkingValue,
            web_search_enabled: webSearchValue
        };
        
        console.log('保存设置:', settings);
        await eel.save_settings_from_web(settings)();
        showNotification('设置已保存', 'success', 2000);
    } catch (e) {
        console.error('Save settings error:', e);
        showNotification('保存失败', 'error');
    }
}

async function editRole() {
    try {
        const roleData = await eel.get_role_data()();
        const infoMessage = !roleData.isCustom ?
            `<div class="form-hint" style="background: var(--info); color: white; padding: 12px; border-radius: 8px; margin-bottom: 16px;">
                ℹ️ ${roleData.defaultInfo || '当前使用默认角色设定'}
            </div>` : '';

        const roleHtml = `
            ${infoMessage}
            <div class="form-group">
                <label class="form-label">自定义角色设定</label>
                <textarea class="form-textarea" id="rolePrompt" rows="10" placeholder="输入您的自定义角色设定，留空则使用默认设定">${roleData.prompt || ''}</textarea>
                <p class="form-hint">输入自定义设定后将覆盖当前对话的默认角色设定</p>
            </div>
        `;

        createModal('🎭 编辑角色', roleHtml, [
            { text: '应用', style: 'btn-primary', onClick: saveRole },
            { text: '清空自定义(恢复默认)', style: 'btn-warning', onClick: resetRole },
            { text: '取消', style: 'btn-ghost', onClick: () => {} }
        ]);
    } catch (e) {
        console.error('Get role error:', e);
        showNotification('加载角色数据失败', 'error');
    }
}

async function saveRole() {
    try {
        const prompt = document.getElementById('rolePrompt').value;
        await eel.save_role_from_web(prompt)();
        showNotification('角色设定已更新', 'success', 2000);
    } catch (e) {
        console.error('Save role error:', e);
        showNotification('保存失败', 'error');
    }
}

async function resetRole() {
    if (!confirm('确定要清空自定义设定并恢复为默认角色吗？')) return;
    try {
        document.getElementById('rolePrompt').value = '';
        await eel.save_role_from_web('')();
        showNotification('已恢复默认设定', 'success', 2000);
        closeModal(document.querySelector('.modal-overlay'));
        setTimeout(() => editRole(), 300);
    } catch (e) {
        console.error('Reset role error:', e);
        showNotification('恢复失败', 'error');
    }
}


// PAD情绪值更新
eel.expose(updatePADValues);
function updatePADValues(pad) {
    console.log('📊 收到PAD值:', pad);
    if (Live2DManager.isInitialized) {
        Live2DManager.updateByPAD(pad);
    }
}

// 根据对话内容触发特效
eel.expose(triggerAvatarEffect);
function triggerAvatarEffect(content) {
    if (Live2DManager.isInitialized) {
        Live2DManager.triggerByContent(content);
    }
}

// 开始说话动画
eel.expose(startAvatarTalking);
function startAvatarTalking(duration) {
    if (Live2DManager.isInitialized) {
        Live2DManager.startTalking(duration);
    }
}

// 打开Live2D模型选择器
function openModelSelector() {
    console.log('🎭 打开模型选择器');
    
    const models = Live2DManager.getAvailableModels();
    console.log('📋 模型列表:', models);
    
    if (models.length === 0) {
        showNotification('没有可用的Live2D模型', 'warning');
        return;
    }
    
    let itemsHtml = '';
    for (const model of models) {
        const isCurrentClass = model.isCurrent ? 'btn-primary' : 'btn-outline';
        const currentLabel = model.isCurrent ? ' (当前)' : '';
        itemsHtml += `
            <button class="btn ${isCurrentClass}" style="width: 100%; margin-bottom: 10px; text-align: left;" 
                    onclick="selectLive2DModel('${model.id}')">
                🎭 ${model.name}${currentLabel}
            </button>
        `;
    }
    
    const contentHtml = `
        <div style="padding: 10px;">
            <p class="form-hint" style="margin-bottom: 15px;">选择要使用的Live2D模型：</p>
            ${itemsHtml}
        </div>
    `;
    
    createModal('🎭 切换Live2D模型', contentHtml, [
        { text: '关闭', style: 'btn-ghost', onClick: () => {} }
    ]);
}

async function selectLive2DModel(modelId) {
    showNotification('正在切换模型...', 'info', 2000);
    
    const success = await Live2DManager.switchModel(modelId);
    
    if (success) {
        showNotification('模型切换成功！', 'success', 2000);
        closeModal(document.querySelector('.modal-overlay'));
    } else {
        showNotification('模型切换失败', 'error');
    }
}

async function changeTTSVoice(voiceId) {
    const success = await eel.set_tts_voice(voiceId)();
    if (success) {
        showNotification('声音已切换', 'success', 2000);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

// 导出全局函数
window.toggleVoice = toggleVoice;
window.toggleModelMode = toggleModelMode;
window.toggleAvatarVisibility = toggleAvatarVisibility;
window.openSettings = openSettings;
window.editRole = editRole;
window.newConversation = () => chatManager.newConversation();
window.showConversationList = () => chatManager.showConversationList();
window.sendMessage = () => chatManager.send();
window.uploadFile = () => chatManager.uploadFile ? chatManager.uploadFile() : null;
window.clearFile = () => chatManager.clearFile ? chatManager.clearFile() : null;
window.openThemeSelector = () => themeManager.openSelector();
window.openModelSelector = openModelSelector;
window.selectLive2DModel = selectLive2DModel;
window.changeTTSVoice = changeTTSVoice;
