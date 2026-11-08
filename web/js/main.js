// ===== 主程序 - 星织AI助手 =====
console.log('🎮 Main.js 加载 v17');

// ===== 防误触保护 =====
(function () {
    // 禁用右键菜单（输入区内保留，便于粘贴 API Key）
    document.addEventListener('contextmenu', function (e) {
        const tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea') return;
        const selection = window.getSelection();
        if (selection && selection.toString().length > 0) return;
        e.preventDefault();
        return false;
    });

    // 禁用刷新（会断开与 Python 的连接）
    document.addEventListener('keydown', function (e) {
        if (e.key === 'F5' || e.keyCode === 116) {
            e.preventDefault();
            showNotification('刷新页面会断开与程序的连接', 'error', 3000);
            return false;
        }
        if ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.keyCode === 82)) {
            e.preventDefault();
            showNotification('刷新页面会断开与程序的连接', 'error', 3000);
            return false;
        }
    });

    // 拖进来的文件不应该让窗口跳走（桌面应用不会这么干）
    ['dragenter', 'dragover', 'drop'].forEach(function (evt) {
        document.addEventListener(evt, function (e) {
            e.preventDefault();
            e.stopPropagation();
        }, false);
    });

    // 浏览器级的快捷键在应用里没有意义
    document.addEventListener('keydown', function (e) {
        const mod = e.ctrlKey || e.metaKey;
        if (!mod) return;
        const key = (e.key || '').toLowerCase();
        if (key === 'f' || key === 'p' || key === 's' || key === 'o' || key === 'u') {
            e.preventDefault();
        }
    });

    // 禁用 Ctrl + 滚轮的整页缩放
    document.addEventListener('wheel', function (e) {
        if (e.ctrlKey) e.preventDefault();
    }, { passive: false });

    window.addEventListener('beforeunload', function (e) {
        const message = '确定要关闭星织吗？';
        e.returnValue = message;
        return message;
    });
})();

// ===== 版本校验（清理旧缓存） =====
(function () {
    const STORAGE_KEY = 'hoshiori_app_version';
    const currentVersion = new URLSearchParams(window.location.search).get('v') ||
        document.querySelector('script[src*="main.js"]')?.src.match(/v=(\d+)/)?.[1] ||
        Date.now().toString();

    const storedVersion = localStorage.getItem(STORAGE_KEY);

    if (storedVersion && storedVersion !== currentVersion) {
        console.warn('检测到版本更新，清除缓存并刷新…');
        localStorage.setItem(STORAGE_KEY, currentVersion);
        if ('caches' in window) {
            caches.keys().then(names => names.forEach(name => caches.delete(name)));
        }
        window.location.reload(true);
        return;
    }

    localStorage.setItem(STORAGE_KEY, currentVersion);
})();

// ===== SDK 状态 =====
window.sdkLoadStatus = { pixi: false, cubism: false, core: false };

if (typeof PIXI !== 'undefined') {
    window.sdkLoadStatus.pixi = true;
} else {
    console.error('PIXI 未加载');
}

setTimeout(() => {
    if (typeof PIXI !== 'undefined' && PIXI.live2d) window.sdkLoadStatus.cubism = true;
    if (typeof Live2DCubismCore !== 'undefined') window.sdkLoadStatus.core = true;
}, 1000);

// ===== Live2D 动态立绘 =====
const Live2DManager = {
    model: null,
    app: null,
    canvas: null,
    container: null,
    isInitialized: false,
    isVisible: true,
    currentMood: 'neutral',
    currentModelId: 'yumi',
    modelBasePath: 'assets/live2d/live2d_modules-master/',
    lookTarget: { x: 0, y: 0 },
    look: { x: 0, y: 0 },
    clock: 0,
    timers: [],
    expressionTimer: null,
    talkTimer: null,
    talkStopTimer: null,
    tickFn: null,
    resizeObserver: null,
    gesture: null,
    strokeAcc: 0,
    lastPointerAt: 0,
    idleLookAt: 0,

    availableModels: {
        'yumi': {
            name: '优米', latin: 'Yumi',
            path: 'yumi/yumi.model3.json',
            expressions: { neutral: null, happy: '星星眼.exp3.json', sad: '泪汪汪.exp3.json', angry: '黑脸.exp3.json', shy: '猫猫嘴.exp3.json', surprised: '爱心眼.exp3.json' }
        },
        'nahida': {
            name: '纳西妲', latin: 'Nahida',
            path: 'nahida/nahida.model3.json',
            expressions: { neutral: null, happy: '发光.exp3.json', sad: '泪.exp3.json', angry: '生气.exp3.json', shy: '脸红.exp3.json', surprised: '星星.exp3.json' }
        },
        'murasame': {
            name: '村雨', latin: 'Murasame',
            path: 'Murasame_Yukata/Murasame_Yukata.model3.json',
            expressions: { neutral: null, happy: '03_GaoGuang.exp3.json', sad: '01_LianHei.exp3.json', angry: '07_HengYan.exp3.json', shy: '05_LianHong.exp3.json', surprised: '08_qYan.exp3.json' }
        },
    },

    getModelPath() {
        return this.modelBasePath + this.availableModels[this.currentModelId].path;
    },

    getAvailableModels() {
        return Object.entries(this.availableModels).map(([id, cfg]) => ({
            id, name: cfg.name, latin: cfg.latin, isCurrent: id === this.currentModelId
        }));
    },

    async init() {
        this.container = document.querySelector('.avatar-container');
        if (!this.container) return false;

        const saved = localStorage.getItem('live2d_model');
        if (saved && this.availableModels[saved]) this.currentModelId = saved;

        const sdkOk = await this.waitSDK();
        if (!sdkOk) {
            this.fallback();
            return false;
        }

        try {
            const res = await fetch(this.getModelPath());
            if (!res.ok) throw new Error('model not found');
        } catch (e) {
            this.fallback();
            return false;
        }

        try {
            await this.initPixi();
            await this.loadModel();
            this.setupInteraction();
            this.startIdle();
            this.isInitialized = true;
            this.container.classList.add('is-live');
            return true;
        } catch (e) {
            console.error('Live2D 加载失败:', e);
            this.fallback();
            return false;
        }
    },

    async waitSDK() {
        if (typeof PIXI === 'undefined') {
            console.error('PIXI 未加载，Live2D 将降级');
            return false;
        }
        for (let i = 0; i < 100; i++) {
            if (typeof PIXI !== 'undefined' && PIXI.live2d && PIXI.live2d.Live2DModel) {
                return true;
            }
            await new Promise(r => setTimeout(r, 100));
        }
        console.error('Live2D SDK 加载超时');
        return false;
    },

    async initPixi() {
        const img = document.getElementById('avatarImage');
        if (img) img.style.display = 'none';

        const oldCanvas = document.getElementById('live2d-canvas');
        if (oldCanvas) oldCanvas.remove();

        this.canvas = document.createElement('canvas');
        this.canvas.id = 'live2d-canvas';
        this.canvas.style.cssText = 'width:100%;height:100%;position:absolute;top:0;left:0;z-index:2;display:block;';
        this.container.appendChild(this.canvas);
        this.container.classList.remove('is-fallback');

        if (this.app) {
            if (this.tickFn) this.app.ticker.remove(this.tickFn);
            this.app.destroy(true);
            this.app = null;
        }

        const w = this.container.clientWidth || 320;
        const h = this.container.clientHeight || 420;

        this.app = new PIXI.Application({
            view: this.canvas,
            width: w,
            height: h,
            backgroundAlpha: 0,
            antialias: true,
            autoDensity: true,
            resolution: Math.min(window.devicePixelRatio || 1, 2)
        });
        this.app.renderer.resize(w, h);
        this.pinCanvasStyle();

        // 光室收起/展开会让容器尺寸归零再回来，必须自己盯着
        if (this.resizeObserver) this.resizeObserver.disconnect();
        if (typeof ResizeObserver !== 'undefined') {
            this.resizeObserver = new ResizeObserver(() => this.relayout());
            this.resizeObserver.observe(this.container);
        }
    },

    /**
     * 容器尺寸变化后重新对齐渲染器与模型
     */
    relayout() {
        if (!this.app || !this.canvas || !this.container) return;

        // 必须量容器：canvas 的 style 会被 pixi 改写成固定像素
        const w = Math.round(this.container.clientWidth);
        const h = Math.round(this.container.clientHeight);
        if (w < 2 || h < 2) return;

        const sw = Math.round(this.app.screen.width);
        const sh = Math.round(this.app.screen.height);
        if (sw !== w || sh !== h) {
            this.app.renderer.resize(w, h);
            this.pinCanvasStyle();
        }
        this.layout();
    },

    /**
     * pixi 的 resize 会把 canvas 写成固定像素，这里拉回 100%，
     * 让它始终铺满光室
     */
    pinCanvasStyle() {
        if (!this.canvas) return;
        this.canvas.style.width = '100%';
        this.canvas.style.height = '100%';
    },

    /**
     * 把模型摆回画面中央，并按容器比例缩放
     */
    layout() {
        if (!this.model || !this.app) return;
        const sw = this.app.screen.width;
        const sh = this.app.screen.height;
        if (sw < 2 || sh < 2) return;

        const baseW = this.baseWidth || this.model.width || sw;
        const baseH = this.baseHeight || this.model.height || sh;
        // 0.86 给底部的铭牌留出位置，同时不让头顶贴到光室标题
        const s = Math.min(sw / baseW, sh / baseH) * 0.86;

        this.model.scale.set(s);
        this.model.position.set(sw / 2, sh * 0.49);
    },

    async loadModel() {
        if (this.model) {
            try { this.app.stage.removeChild(this.model); this.model.destroy(); } catch (e) { }
            this.model = null;
        }

        const modelPath = this.getModelPath();
        this.model = await PIXI.live2d.Live2DModel.from(modelPath, { autoInteract: false });
        if (typeof this.model.anchor !== 'undefined' && this.model.anchor) {
            this.model.anchor.set(0.5, 0.5);
        }
        this.app.stage.addChild(this.model);

        // 记下 1:1 尺寸：Container.width 会随 scale 变化，不能每帧拿来当基准
        this.model.scale.set(1);
        this.baseWidth = this.model.width || this.app.screen.width;
        this.baseHeight = this.model.height || this.app.screen.height;

        this.relayout();
        this.applyMoodExpression(this.currentMood);
    },

    async switchModel(id) {
        if (!this.availableModels[id]) return false;

        const modelPath = this.modelBasePath + this.availableModels[id].path;
        try {
            const res = await fetch(modelPath);
            if (!res.ok) return false;
        } catch (e) {
            return false;
        }

        this.currentModelId = id;
        localStorage.setItem('live2d_model', id);

        try {
            if (!this.app) {
                await this.init();
                return true;
            }
            await this.loadModel();
            this.startIdle();
            return true;
        } catch (e) {
            console.error('模型加载失败:', e);
            return false;
        }
    },

    /* ---------- 显示 / 隐藏 ---------- */

    suspend() {
        this.isVisible = false;
        if (this.app) this.app.ticker.stop();
    },

    resume() {
        this.isVisible = true;
        if (!this.app) return;

        // 等布局稳定（光室宽度过渡 320ms）后再量尺寸
        requestAnimationFrame(() => {
            setTimeout(() => {
                this.relayout();
                if (this.app) this.app.ticker.start();
                this.applyMoodExpression(this.currentMood);
            }, 60);
        });
    },

    /* ---------- 表情 ---------- */

    resetExpression() {
        const mgr = this.model && this.model.internalModel && this.model.internalModel.motionManager
            ? this.model.internalModel.motionManager.expressionManager
            : null;
        if (mgr && typeof mgr.resetExpression === 'function') {
            try { mgr.resetExpression(); } catch (e) { }
        }
    },

    /**
     * 应用某个表情（先清掉旧表情，避免叠加）
     * @param {string} name - neutral | happy | sad | angry | shy | surprised
     */
    applyExpression(name) {
        if (!this.model) return;
        this.resetExpression();
        const cfg = this.availableModels[this.currentModelId];
        const exp = cfg && cfg.expressions ? cfg.expressions[name] : null;
        if (!exp) return;
        try { this.model.expression(exp); } catch (e) { }
    },

    applyMoodExpression(mood) {
        this.currentMood = mood || 'neutral';
        this.applyExpression(this.currentMood);
    },

    /**
     * 临时情绪反应，过一会儿回落到基础情绪
     * @param {string} name
     * @param {number} holdMs
     */
    feel(name, holdMs = 5200) {
        this.applyExpression(name);
        const fx = { happy: 'heart', shy: 'blush', surprised: 'sparkle', sad: 'tear', angry: 'anger' };
        if (fx[name]) this.showEffect(fx[name]);

        clearTimeout(this.expressionTimer);
        this.expressionTimer = setTimeout(() => {
            this.applyExpression(this.currentMood);
        }, holdMs);
    },

    /* ---------- 交互 ---------- */

    setupInteraction() {
        const el = this.container;
        if (!el || el.dataset.bound === '1') return;
        el.dataset.bound = '1';

        el.addEventListener('pointerdown', e => {
            this.gesture = { x: e.clientX, y: e.clientY, moved: 0, at: Date.now() };
            this.strokeAcc = 0;
            el.classList.add('is-pressed');
            if (el.setPointerCapture) {
                try { el.setPointerCapture(e.pointerId); } catch (err) { }
            }
        });

        el.addEventListener('pointermove', e => {
            this.trackPointer(e);
            if (!this.gesture) return;

            const dx = e.clientX - this.gesture.x;
            const dy = e.clientY - this.gesture.y;
            this.gesture.x = e.clientX;
            this.gesture.y = e.clientY;
            this.gesture.moved += Math.hypot(dx, dy);
            this.strokeAcc += Math.abs(dx);

            // 连续抚摸：每滑过一段就换一次反应
            if (this.gesture.moved > 16 && this.strokeAcc > 64) {
                this.strokeAcc = 0;
                this.feel(Math.random() > 0.4 ? 'shy' : 'happy', 3200);
            }
        });

        el.addEventListener('pointerup', e => {
            const g = this.gesture;
            this.gesture = null;
            el.classList.remove('is-pressed');
            if (!g) return;
            if (g.moved < 8 && Date.now() - g.at < 640) this.tap(e);
        });

        el.addEventListener('pointercancel', () => {
            this.gesture = null;
            el.classList.remove('is-pressed');
        });

        el.addEventListener('dblclick', () => {
            this.feel('surprised', 2800);
            el.classList.add('is-poked');
            setTimeout(() => el.classList.remove('is-poked'), 460);
        });
    },

    /**
     * 点击不同高度有不同的反应：头 → 害羞，肩 → 开心，下方 → 意外
     */
    tap(e) {
        const rect = this.container.getBoundingClientRect();
        if (!rect.height) return;
        const ny = (e.clientY - rect.top) / rect.height;

        if (ny < 0.42) this.feel('shy', 4400);
        else if (ny < 0.74) this.feel('happy', 4400);
        else this.feel('surprised', 2600);

        this.container.classList.add('is-poked');
        setTimeout(() => this.container.classList.remove('is-poked'), 460);
    },

    /**
     * 把鼠标位置换算成「她该往哪看」
     */
    trackPointer(e) {
        const rect = this.container.getBoundingClientRect();
        if (!rect.width || !rect.height) return;

        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height * 0.42;
        const nx = (e.clientX - cx) / (rect.width * 0.85);
        const ny = (e.clientY - cy) / (rect.height * 0.85);

        this.lookTarget.x = Math.max(-1, Math.min(1, nx));
        this.lookTarget.y = Math.max(-1, Math.min(1, ny));
        this.lastPointerAt = Date.now();
    },

    /* ---------- 待机 ---------- */

    startIdle() {
        if (!this.app) return;

        if (this.tickFn) {
            this.app.ticker.remove(this.tickFn);
            this.tickFn = null;
        }
        this.tickFn = () => this.tick();
        try {
            this.app.ticker.add(this.tickFn, undefined, PIXI.UPDATE_PRIORITY.LOW);
        } catch (e) {
            this.app.ticker.add(this.tickFn);
        }

        this.timers.forEach(t => clearTimeout(t));
        this.timers = [];

        const schedule = () => {
            const timer = setTimeout(() => {
                if (this.isVisible && this.model) {
                    if (Math.random() < 0.45) this.nudgeMotion();
                    else this.feel(this.pickIdleExpression(), 3600);
                }
                schedule();
            }, 15000 + Math.random() * 17000);
            this.timers.push(timer);
        };
        schedule();
    },

    pickIdleExpression() {
        const pool = { neutral: [null, null, 'happy'], happy: ['happy', 'shy'], sad: ['sad'], angry: ['angry'], shy: ['shy'], surprised: ['surprised'] };
        const list = pool[this.currentMood] || pool.neutral;
        return list[Math.floor(Math.random() * list.length)];
    },

    nudgeMotion() {
        if (!this.model) return;
        try { this.model.motion('Idle'); } catch (e) { }
    },

    tick() {
        if (!this.model || !this.isVisible) return;

        const dt = (this.app && this.app.ticker.deltaMS) || 16;
        this.clock += dt / 1000;

        // 鼠标停下两秒后，视线自己慢慢游走
        if (!this.lastPointerAt || Date.now() - this.lastPointerAt > 2600) {
            if (Date.now() > this.idleLookAt) {
                this.lookTarget.x = (Math.random() - 0.5) * 0.85;
                this.lookTarget.y = (Math.random() - 0.5) * 0.55;
                this.idleLookAt = Date.now() + 2200 + Math.random() * 3400;
            }
        }

        const k = Math.min(1, dt / 170);
        this.look.x += (this.lookTarget.x - this.look.x) * k;
        this.look.y += (this.lookTarget.y - this.look.y) * k;

        const core = this.model.internalModel && this.model.internalModel.coreModel;
        if (!core || !core.setParameterValueById) return;

        const sway = Math.sin(this.clock * 0.55);

        try {
            core.setParameterValueById('ParamAngleX', this.look.x * 26 + sway * 1.4);
            core.setParameterValueById('ParamAngleY', -this.look.y * 18);
            core.setParameterValueById('ParamAngleZ', this.look.x * -4 + sway * 1.1);
            core.setParameterValueById('ParamBodyAngleX', this.look.x * 7);
            core.setParameterValueById('ParamBodyAngleZ', this.look.x * -2);
            core.setParameterValueById('ParamEyeBallX', this.look.x * 0.9);
            core.setParameterValueById('ParamEyeBallY', -this.look.y * 0.8);
        } catch (e) { }
    },

    startTalking(duration) {
        if (!this.model) return;
        const core = this.model.internalModel && this.model.internalModel.coreModel;
        if (!core) return;

        clearInterval(this.talkTimer);
        clearTimeout(this.talkStopTimer);

        let phase = 0;
        this.talkTimer = setInterval(() => {
            phase += 0.55;
            const open = 0.18 + Math.abs(Math.sin(phase)) * 0.62;
            try {
                core.setParameterValueById('ParamMouthOpenY', open);
                core.setParameterValueById('ParamMouthForm', 0.75);
            } catch (e) { }
        }, 90);

        this.talkStopTimer = setTimeout(() => {
            clearInterval(this.talkTimer);
            this.talkTimer = null;
            try {
                core.setParameterValueById('ParamMouthOpenY', 0);
                core.setParameterValueById('ParamMouthForm', 0);
            } catch (e) { }
        }, duration || 3000);
    },

    updateByPAD(pad) {
        const p = pad.pleasure, a = pad.arousal, d = pad.dominance;
        let mood = 'neutral';
        if (p > 0.5 && a > 0.3) mood = 'happy';
        else if (p < -0.3 && a < 0) mood = 'sad';
        else if (p < -0.3 && a > 0.5) mood = 'angry';
        else if (p > 0 && d < -0.3) mood = 'shy';
        else if (a > 0.6) mood = 'surprised';
        if (mood !== this.currentMood) {
            this.applyMoodExpression(mood);
        }
    },

    triggerByContent(text) {
        if (/喜欢|爱你|想你了/.test(text)) this.feel('happy', 6000);
        else if (/害羞|脸红/.test(text)) this.feel('shy', 5000);
        else if (/生气|讨厌/.test(text)) this.feel('angry', 4200);
        else if (/难过|伤心|对不起/.test(text)) this.feel('sad', 5000);
        else if (/真的假的|居然|竟然/.test(text)) this.feel('surprised', 3200);
    },

    updateMood(mood) {
        if (mood !== this.currentMood) {
            this.applyMoodExpression(mood);
        }
    },

    /* ---------- 光效 ---------- */

    showEffect(name) {
        if (!this.container) return;
        const shapes = {
            heart: { d: 'M12 20.2S4.6 15.4 4.6 10.2A4.2 4.2 0 0 1 12 7.5a4.2 4.2 0 0 1 7.4 2.7c0 5.2-7.4 10-7.4 10z', tone: 'rose' },
            sparkle: { d: 'M12 2.6c.5 5.2 4.2 8.9 9.4 9.4-5.2.5-8.9 4.2-9.4 9.4-.5-5.2-4.2-8.9-9.4-9.4 5.2-.5 8.9-4.2 9.4-9.4z', tone: 'accent' },
            blush: { d: 'M12 2.6c.5 5.2 4.2 8.9 9.4 9.4-5.2.5-8.9 4.2-9.4 9.4-.5-5.2-4.2-8.9-9.4-9.4 5.2-.5 8.9-4.2 9.4-9.4z', tone: 'rose' },
            tear: { d: 'M12 3.4c3.4 4.6 5.6 7.1 5.6 10a5.6 5.6 0 0 1-11.2 0c0-2.9 2.2-5.4 5.6-10z', tone: 'cool' },
            anger: { d: 'M12 2.6c.5 5.2 4.2 8.9 9.4 9.4-5.2.5-8.9 4.2-9.4 9.4-.5-5.2-4.2-8.9-9.4-9.4 5.2-.5 8.9-4.2 9.4-9.4z', tone: 'warm' }
        };
        const shape = shapes[name] || shapes.sparkle;

        const el = document.createElement('span');
        el.className = 'portrait-fx portrait-fx--' + shape.tone;
        el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${shape.d}" fill="currentColor"/></svg>`;
        el.style.left = (34 + Math.random() * 32).toFixed(1) + '%';
        el.style.top = (26 + Math.random() * 24).toFixed(1) + '%';
        this.container.appendChild(el);
        setTimeout(() => el.remove(), 2000);
    },

    fallback() {
        const img = document.getElementById('avatarImage');
        if (img && img.getAttribute('src')) {
            img.style.display = 'block';
            img.classList.add('breathing');
        }
        if (this.container) this.container.classList.add('is-fallback');
        this.isInitialized = true;
    }
};

window.avatarAnimationManager = Live2DManager;

// 全局状态
let appState = {
    voiceEnabled: false,
    avatarVisible: true,
    modelMode: 'local',
    affection: 50,
    mood: 'neutral'
};

const MOOD_WORDS = {
    neutral: '平静',
    happy: '愉悦',
    angry: '愠怒',
    sad: '低落',
    shy: '羞怯',
    surprised: '惊讶'
};

// 应用初始化
async function initApp() {
    try {
        await themeManager.init();
        chatManager.init();
        await loadAppState();
        await Live2DManager.init();
        if (!appState.avatarVisible) Live2DManager.suspend();
        syncChamberModelLabel();

        // 她的视线跟着整块屏幕上的光标走，而不只是立绘区域内
        document.addEventListener('pointermove', (e) => {
            if (Live2DManager.isInitialized && Live2DManager.isVisible) {
                Live2DManager.trackPointer(e);
            }
        }, { passive: true });

        if (typeof syncShellState === 'function') syncShellState();
    } catch (e) {
        console.error('初始化失败:', e);
        showNotification('应用初始化失败', 'error');
    }
}

async function loadAppState() {
    try {
        const state = await eel.get_app_state()();
        if (state) {
            appState = { ...appState, ...state };
            updateUIFromState();
        }
    } catch (e) {
        console.error('Load state error:', e);
    }
}

function updateUIFromState() {
    const avatarSection = document.querySelector('.avatar-section');
    if (avatarSection) {
        avatarSection.classList.toggle('hidden', !appState.avatarVisible);
    }

    // 立绘开关与渲染同步：关掉时停 ticker，打开时重新量尺寸再恢复
    if (Live2DManager.isInitialized) {
        if (appState.avatarVisible) Live2DManager.resume();
        else Live2DManager.suspend();
    }

    updateAffection(appState.affection);
    updateMood(appState.mood);

    if (typeof syncShellState === 'function') syncShellState();
}

eel.expose(updateAvatarDisplay);
function updateAvatarDisplay(mood) {
    updateMood(mood);
}

eel.expose(updateAffection);
function updateAffection(value) {
    appState.affection = value;

    const affectionValue = document.getElementById('affectionValue');
    const affectionBar = document.getElementById('affectionBar');

    if (affectionValue) {
        affectionValue.textContent = value;
        if (value >= 70) {
            affectionValue.style.color = 'var(--accent)';
        } else if (value >= 40) {
            affectionValue.style.color = 'var(--ink-1)';
        } else {
            affectionValue.style.color = 'var(--ink-3)';
        }
    }

    if (affectionBar) {
        affectionBar.style.width = `${value}%`;
        const track = affectionBar.parentElement;
        if (track) {
            track.classList.add('progress-animated');
            setTimeout(() => track.classList.remove('progress-animated'), 1000);
        }
    }
}

eel.expose(updateMood);
function updateMood(mood) {
    appState.mood = mood;

    const word = MOOD_WORDS[mood] || '平静';

    const moodLabel = document.getElementById('moodLabel');
    if (moodLabel) {
        moodLabel.setAttribute('data-mood', mood);
        moodLabel.innerHTML = `<i class="mood__dot"></i>${word}`;
    }

    const threadMeta = document.getElementById('threadMeta');
    if (threadMeta) threadMeta.textContent = `此刻 · ${word}`;

    document.body.setAttribute('data-mood', mood);

    if (Live2DManager.isInitialized) {
        Live2DManager.updateMood(mood);
    }
}

async function toggleVoice() {
    try {
        const newState = await eel.toggle_voice_from_web()();
        appState.voiceEnabled = newState;
        showNotification(newState ? '语音已开启' : '语音已关闭', 'success', 1800);
    } catch (e) {
        console.error('Toggle voice error:', e);
        showNotification('语音切换失败', 'error');
    }
    if (typeof syncShellState === 'function') syncShellState();
    if (typeof window.updateSettingsUI === 'function') window.updateSettingsUI();
}

async function toggleModelMode() {
    try {
        const result = await eel.toggle_model_mode_from_web()();
        appState.modelMode = result.mode;
        showNotification(
            result.mode === 'local' ? `已切换到本地：${result.model}` : `已切换到在线：${result.model}`,
            'info', 3600
        );
    } catch (e) {
        console.error('Toggle model mode error:', e);
        showNotification('切换失败', 'error');
    }
    if (typeof syncShellState === 'function') syncShellState();
}

function toggleAvatarVisibility() {
    appState.avatarVisible = !appState.avatarVisible;

    const avatarSection = document.querySelector('.avatar-section');
    if (avatarSection) {
        avatarSection.classList.toggle('hidden', !appState.avatarVisible);
    }

    if (appState.avatarVisible) Live2DManager.resume();
    else Live2DManager.suspend();

    if (typeof eel !== 'undefined') {
        eel.save_avatar_visibility(appState.avatarVisible);
    }
    if (typeof syncShellState === 'function') syncShellState();
}

// ===== 设置 =====
/**
 * 切换设置分组
 * @param {string} name - daily | model | more
 */
function switchSettingsTab(name) {
    document.querySelectorAll('.settings-tab').forEach(tab => {
        const on = tab.dataset.tab === name;
        tab.classList.toggle('is-active', on);
        tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.settings-panel').forEach(panel => {
        panel.hidden = panel.dataset.panel !== name;
    });
}

async function openSettings() {
    try {
        document.querySelectorAll('.modal-overlay').forEach(m => m.remove());

        const settings = await eel.get_settings()();
        const ttsVoices = await eel.get_tts_voices()();
        const currentVoice = await eel.get_current_tts_voice()();
        const apiPresets = await eel.get_api_presets()();

        let voiceOptions = '';
        for (const voice of ttsVoices) {
            const selected = voice.id === currentVoice ? 'selected' : '';
            voiceOptions += `<option value="${voice.id}" ${selected}>${voice.name}</option>`;
        }

        let providerOptions = '';
        for (const [key, preset] of Object.entries(apiPresets)) {
            const selected = settings.api_provider === key ? 'selected' : '';
            providerOptions += `<option value="${key}" ${selected}>${preset.name}</option>`;
        }

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

        let thinkingOptions = '';
        if (currentPreset && currentPreset.thinking_modes && currentPreset.thinking_modes.length > 0) {
            for (const mode of currentPreset.thinking_modes) {
                const selected = settings.thinking_mode === mode.value ? 'selected' : '';
                thinkingOptions += `<option value="${mode.value}" ${selected}>${mode.label}</option>`;
            }
        }

        const isOnline = settings.model_mode === 'online';

        const settingsHtml = `
            <div class="settings-tabs" role="tablist">
                <button class="settings-tab is-active" data-tab="daily" role="tab"
                        onclick="switchSettingsTab('daily')">日常</button>
                <button class="settings-tab" data-tab="model" role="tab"
                        onclick="switchSettingsTab('model')">模型</button>
                <button class="settings-tab" data-tab="more" role="tab"
                        onclick="switchSettingsTab('more')">更多</button>
            </div>

            <div class="settings-panel" data-panel="daily">
                <div class="switch-row">
                    <div>
                        <div class="switch-label">语音朗读</div>
                        <div class="switch-desc">用 Edge-TTS 把她的回答读出来</div>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="settingVoiceSwitch" ${appState.voiceEnabled ? 'checked' : ''}
                               onchange="toggleVoice()">
                        <span class="switch__thumb"></span>
                    </label>
                </div>

                <div class="switch-row">
                    <div>
                        <div class="switch-label">显示立绘</div>
                        <div class="switch-desc">在左侧光室中呈现 Live2D 角色</div>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="settingAvatarSwitch" ${appState.avatarVisible ? 'checked' : ''}
                               onchange="toggleAvatarVisibility(); updateUIFromState();">
                        <span class="switch__thumb"></span>
                    </label>
                </div>

                <div class="form-group" style="margin-top: 18px;">
                    <label class="form-label">声音</label>
                    <select class="form-select" id="settingTTSVoice" onchange="changeTTSVoice(this.value)">
                        ${voiceOptions}
                    </select>
                    <p class="form-hint">当前声音会用于所有回答的朗读。</p>
                </div>
            </div>

            <div class="settings-panel" data-panel="model" hidden>
                <div class="form-group">
                    <label class="form-label">运行模式</label>
                    <div class="settings-grid">
                        <button class="btn ${!isOnline ? 'btn-primary' : 'btn-outline'}"
                            onclick="if(appState.modelMode !== 'local') toggleModelMode(); closeModal(this); setTimeout(openSettings, 420);">
                            本地 · LM Studio
                        </button>
                        <button class="btn ${isOnline ? 'btn-primary' : 'btn-outline'}"
                            onclick="if(appState.modelMode !== 'online') toggleModelMode(); closeModal(this); setTimeout(openSettings, 420);">
                            在线 · API
                        </button>
                    </div>
                    <input type="hidden" id="settingModelMode" value="${settings.model_mode}">
                </div>

                ${isOnline ? `
                <div class="form-group">
                    <label class="form-label">API 提供商</label>
                    <select class="form-select" id="settingApiProvider" onchange="handleProviderChange(this.value)">
                        ${providerOptions}
                    </select>
                </div>
                ` : ''}

                <div class="form-group">
                    <label class="form-label">API 密钥</label>
                    <input type="password" class="form-input" id="settingApiKey" value="${settings.api_key || ''}"
                           placeholder="sk-…" autocomplete="off">
                    <p class="form-hint">${isOnline
                ? '填入 DeepSeek 或 MiMo 平台申请的 Key，保存后即刻生效。'
                : '本地模式无需真实密钥。'}</p>
                </div>

                <div class="form-group">
                    <label class="form-label">模型名称</label>
                    ${isOnline && modelOptions ? `
                    <select class="form-select" id="settingModel">${modelOptions}</select>
                    ` : `
                    <input type="text" class="form-input" id="settingModel" value="${settings.model || ''}"
                           placeholder="qwen2.5-7b-instruct">
                    `}
                </div>

                ${isOnline && thinkingOptions ? `
                <div class="form-group">
                    <label class="form-label">深度思考</label>
                    <select class="form-select" id="settingThinkingMode">${thinkingOptions}</select>
                    <p class="form-hint">开启后回答更周密，速度更慢、消耗更多。</p>
                </div>
                ` : ''}

                ${isOnline && currentPreset && currentPreset.supports_web_search ? `
                <div class="switch-row" style="border-bottom: 0;">
                    <div>
                        <div class="switch-label">联网搜索</div>
                        <div class="switch-desc">允许她检索最新信息，响应会稍慢</div>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="settingWebSearchSwitch" ${settings.web_search_enabled ? 'checked' : ''}
                               onchange="document.getElementById('settingWebSearch').value = this.checked ? 'true' : 'false'">
                        <span class="switch__thumb"></span>
                    </label>
                    <input type="hidden" id="settingWebSearch" value="${settings.web_search_enabled ? 'true' : 'false'}">
                </div>
                ` : ''}
            </div>

            <div class="settings-panel" data-panel="more" hidden>
                <div class="settings-grid">
                    <button class="btn btn-ghost" onclick="editRole(); closeModal(this);">角色设定</button>
                    <button class="btn btn-ghost" onclick="openThemeSelector(); closeModal(this);">切换气质</button>
                </div>
                <div class="meta-row">
                    <span class="label">版本</span>
                    <span class="meta-row__value">Hoshiori 1.2</span>
                </div>
                <div class="meta-row">
                    <span class="label">数据</span>
                    <span class="meta-row__value">全部保存在本机 baocun 目录</span>
                </div>
            </div>
        `;


        const modalOverlay = createModal('设置', settingsHtml, [
            { text: '保存', style: 'btn-primary', onClick: saveSettings },
            { text: '关闭', style: 'btn-ghost', onClick: () => { } }
        ]);

        const modalContent = modalOverlay.querySelector('.modal-content');
        if (modalContent) {
            modalContent.addEventListener('click', (e) => e.stopPropagation());
        }

        window.updateSettingsUI = () => {
            const voiceSwitch = document.getElementById('settingVoiceSwitch');
            const avatarSwitch = document.getElementById('settingAvatarSwitch');
            if (voiceSwitch) voiceSwitch.checked = !!appState.voiceEnabled;
            if (avatarSwitch) avatarSwitch.checked = !!appState.avatarVisible;
        };

        window.handleProviderChange = async (provider) => {
            const success = await eel.apply_api_preset(provider)();
            if (success) {
                closeModal(modalOverlay);
                setTimeout(openSettings, 420);
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
        const modelElement = document.getElementById('settingModel');
        const modelValue = modelElement ? (modelElement.value || '') : '';

        const thinkingElement = document.getElementById('settingThinkingMode');
        const thinkingValue = thinkingElement ? thinkingElement.value : 'disabled';

        const webSearchElement = document.getElementById('settingWebSearch');
        const webSearchValue = webSearchElement ? (webSearchElement.value === 'true') : false;

        const providerElement = document.getElementById('settingApiProvider');
        const modeElement = document.getElementById('settingModelMode');

        const settings = {
            model_mode: modeElement ? modeElement.value : appState.modelMode,
            api_provider: providerElement ? providerElement.value : undefined,
            api_key: document.getElementById('settingApiKey')?.value || '',
            model: modelValue,
            thinking_mode: thinkingValue,
            web_search_enabled: webSearchValue
        };

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

        const noteHtml = !roleData.isCustom ? `
            <div class="form-note">
                <span>${roleData.defaultInfo || '当前使用默认角色设定，写下自定义设定后将覆盖它。'}</span>
            </div>
        ` : '';

        const roleHtml = `
            ${noteHtml}
            <div class="form-group">
                <label class="form-label">自定义角色设定</label>
                <textarea class="form-textarea" id="rolePrompt" rows="10"
                    placeholder="例如：你是星织，说话温柔而克制，喜欢在句尾留一点余韵…">${roleData.prompt || ''}</textarea>
                <p class="form-hint">留空即恢复默认设定。这段文字会在每次对话开头交给她。</p>
            </div>
        `;

        createModal('角色设定', roleHtml, [
            { text: '应用', style: 'btn-primary', onClick: saveRole },
            { text: '恢复默认', style: 'btn-warning', onClick: resetRole },
            { text: '取消', style: 'btn-ghost', onClick: () => { } }
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
    if (!confirm('确定要清空自定义设定，恢复默认角色吗？')) return;
    try {
        const field = document.getElementById('rolePrompt');
        if (field) field.value = '';
        await eel.save_role_from_web('')();
        showNotification('已恢复默认设定', 'success', 2000);
        closeModal(document.querySelector('.modal-overlay'));
        setTimeout(() => editRole(), 420);
    } catch (e) {
        console.error('Reset role error:', e);
        showNotification('恢复失败', 'error');
    }
}

// PAD 情绪值
eel.expose(updatePADValues);
function updatePADValues(pad) {
    if (Live2DManager.isInitialized) {
        Live2DManager.updateByPAD(pad);
    }
}

// 内容触发特效
eel.expose(triggerAvatarEffect);
function triggerAvatarEffect(content) {
    if (Live2DManager.isInitialized) {
        Live2DManager.triggerByContent(content);
    }
}

// 说话动画
eel.expose(startAvatarTalking);
function startAvatarTalking(duration) {
    if (Live2DManager.isInitialized) {
        Live2DManager.startTalking(duration);
    }
}

// Live2D 模型选择
function openModelSelector() {
    const models = Live2DManager.getAvailableModels();
    if (models.length === 0) {
        showNotification('没有可用的角色模型', 'warning');
        return;
    }

    const itemsHtml = models.map(model => `
        <button class="pick-item ${model.isCurrent ? 'is-active' : ''}"
                onclick="selectLive2DModel('${model.id}')">
            <span class="pick-item__mark">${model.name.slice(0, 1)}</span>
            <span class="pick-item__body">
                <span class="pick-item__title">${model.name}</span>
                <span class="pick-item__desc">${model.latin}${model.isCurrent ? ' · 正在使用' : ''}</span>
            </span>
            <span class="pick-item__flag">${model.isCurrent ? '当前' : ''}</span>
        </button>
    `).join('');

    createModal('选择角色', `<div class="pick-list">${itemsHtml}</div>`, [
        { text: '关闭', style: 'btn-ghost', onClick: () => { } }
    ]);
}

/**
 * 光室左上角的角色铭牌
 */
function syncChamberModelLabel() {
    const cfg = Live2DManager.availableModels[Live2DManager.currentModelId];
    const nameEl = document.getElementById('chamberModelName');
    const latinEl = document.getElementById('chamberModelLatin');
    if (nameEl && cfg) nameEl.textContent = cfg.name;
    if (latinEl && cfg) latinEl.textContent = (cfg.latin || '').toUpperCase();
}

async function selectLive2DModel(modelId) {
    showNotification('正在换装…', 'info', 1600);
    const success = await Live2DManager.switchModel(modelId);

    if (success) {
        syncChamberModelLabel();
        showNotification('她已经换好了', 'success', 1800);
        closeModal(document.querySelector('.modal-overlay'));
    } else {
        showNotification('模型切换失败', 'error');
    }
}

async function changeTTSVoice(voiceId) {
    const success = await eel.set_tts_voice(voiceId)();
    if (success) {
        showNotification('声音已切换', 'success', 1800);
    }
}

/**
 * 窗口栏按下：把拖动交给系统（Chromium 应用窗口没有 app-region，
 * 只能在 Python 侧发 WM_NCLBUTTONDOWN）
 */
function beginWindowDrag(e) {
    if (!e || e.button !== 0) return;
    if (e.target && e.target.closest &&
        e.target.closest('button, a, input, textarea, select, .titlebar__actions')) return;
    try {
        if (typeof eel !== 'undefined' && eel.begin_window_drag) {
            eel.begin_window_drag()();
        }
    } catch (err) { }
}

/**
 * 最小化到任务栏
 */
function minimizeWindow() {
    try {
        if (typeof eel !== 'undefined' && eel.minimize_window) {
            eel.minimize_window()();
        }
    } catch (e) { }
}

/**
 * 关闭应用：先问一句，再退
 */
async function requestQuit() {
    const confirmed = await confirmDialog({
        title: '要合上这一页了吗？',
        text: '你们说过的话都已经收好了，下次打开还在原来的位置。',
        note: '星织会把这段对话存到本机 baocun 目录，不会上传到任何地方。',
        confirmText: '合上吧',
        cancelText: '再坐一会儿'
    });
    if (!confirmed) return;

    document.body.classList.add('is-quitting');

    try {
        if (typeof eel !== 'undefined' && eel.quit_app_from_web) {
            await eel.quit_app_from_web()();
        }
    } catch (e) {
        console.error('Quit error:', e);
    }
}

// 启动
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

// 导出全局
window.toggleVoice = toggleVoice;
window.toggleModelMode = toggleModelMode;
window.toggleAvatarVisibility = toggleAvatarVisibility;
window.openSettings = openSettings;
window.editRole = editRole;
window.newConversation = () => chatManager.newConversation();
window.requestQuit = requestQuit;
window.beginWindowDrag = beginWindowDrag;
window.minimizeWindow = minimizeWindow;
window.syncChamberModelLabel = syncChamberModelLabel;
window.showConversationList = () => chatManager.showConversationList();
window.sendMessage = () => chatManager.send();
window.uploadFile = () => chatManager.uploadFile ? chatManager.uploadFile() : null;
window.clearFile = () => chatManager.clearFile ? chatManager.clearFile() : null;
window.openThemeSelector = () => themeManager.openSelector();
window.openModelSelector = openModelSelector;
window.selectLive2DModel = selectLive2DModel;
window.changeTTSVoice = changeTTSVoice;
window.switchSettingsTab = switchSettingsTab;
