// ===== 界面交互壳 - 星织AI助手 =====
// 负责：光室抽屉、滚动浮标、输入框自适应、快捷键、主题揭示原点

(function () {
    'use strict';

    const MOBILE_QUERY = '(max-width: 960px)';

    function isMobile() {
        return window.matchMedia(MOBILE_QUERY).matches;
    }

    /* ---------- 光室（角色区） ---------- */
    function togglePortrait() {
        const section = document.getElementById('avatarSection');
        if (!section) return;

        if (isMobile()) {
            const open = section.classList.toggle('is-open');
            setScrim(open);
            syncPortraitA11y();
        } else if (typeof window.toggleAvatarVisibility === 'function') {
            window.toggleAvatarVisibility();
            syncPortraitA11y();
        } else {
            section.classList.toggle('hidden');
            syncPortraitA11y();
        }
    }

    function syncPortraitA11y() {
        const section = document.getElementById('avatarSection');
        const toggle = document.getElementById('portraitToggle');
        if (!section || !toggle) return;

        const visible = isMobile()
            ? section.classList.contains('is-open')
            : !section.classList.contains('hidden');

        toggle.setAttribute('aria-expanded', visible ? 'true' : 'false');
        toggle.setAttribute('aria-label', visible ? '收起角色光室' : '展开角色光室');
    }

    let scrim = null;

    function setScrim(show) {
        if (!scrim) {
            scrim = document.createElement('div');
            scrim.className = 'drawer-scrim';
            scrim.addEventListener('click', () => {
                const section = document.getElementById('avatarSection');
                if (section) section.classList.remove('is-open');
                setScrim(false);
                syncPortraitA11y();
            });
            // 必须挂在 app-container 内，才能与抽屉同层级比较 z-index
            const host = document.getElementById('appContainer') || document.body;
            host.appendChild(scrim);
        }
        scrim.classList.toggle('is-visible', !!show);
    }

    /* ---------- 输入框 ---------- */
    function autoGrow() {
        const input = document.getElementById('messageInput');
        const composer = document.getElementById('composer');
        if (!input) return;

        input.style.height = 'auto';
        const next = Math.min(input.scrollHeight, 168);
        input.style.height = next + 'px';
        input.style.overflowY = input.scrollHeight > 168 ? 'auto' : 'hidden';

        if (composer) {
            composer.classList.toggle('is-empty', input.value.trim().length === 0);
        }
    }

    function resetComposer() {
        const input = document.getElementById('messageInput');
        if (!input) return;
        input.value = '';
        input.style.height = 'auto';
        autoGrow();
        input.focus({ preventScroll: true });
    }

    /* ---------- 滚动浮标 ---------- */
    function initScrollPill() {
        const container = document.getElementById('chatContainer');
        const pill = document.getElementById('scrollPill');
        if (!container || !pill) return;

        const update = () => {
            const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
            pill.classList.toggle('is-visible', distance > 220);
        };

        container.addEventListener('scroll', update, { passive: true });
        update();
    }

    /* ---------- 空状态快捷语 ---------- */
    function initWelcomeChips() {
        document.querySelectorAll('.welcome__chips .chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const input = document.getElementById('messageInput');
                if (!input) return;
                input.value = chip.dataset.prompt || chip.textContent.trim();
                autoGrow();
                input.focus({ preventScroll: true });
            });
        });
    }

    /* ---------- 立绘微视差 ---------- */
    function initParallax() {
        const stage = document.getElementById('portraitStage');
        if (!stage) return;

        stage.addEventListener('mousemove', (e) => {
            const rect = stage.getBoundingClientRect();
            const x = (e.clientX - rect.left) / rect.width - 0.5;
            const y = (e.clientY - rect.top) / rect.height - 0.5;
            stage.style.setProperty('--mx', (x * 9).toFixed(2) + 'px');
            stage.style.setProperty('--my', (y * 9).toFixed(2) + 'px');
        });

        stage.addEventListener('mouseleave', () => {
            stage.style.setProperty('--mx', '0px');
            stage.style.setProperty('--my', '0px');
        });
    }

    /* ---------- 主题揭示原点 ---------- */
    function initRevealOrigin() {
        document.addEventListener('pointerdown', (e) => {
            document.body.style.setProperty('--reveal-x', e.clientX + 'px');
            document.body.style.setProperty('--reveal-y', e.clientY + 'px');
        }, { passive: true, capture: true });
    }

    /* ---------- 快捷键 ---------- */
    function initShortcuts() {
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
                e.preventDefault();
                const input = document.getElementById('messageInput');
                if (input) input.focus({ preventScroll: true });
            }

            if (e.key === 'Escape') {
                const section = document.getElementById('avatarSection');
                if (section && section.classList.contains('is-open')) {
                    section.classList.remove('is-open');
                    setScrim(false);
                    syncPortraitA11y();
                }
            }
        });
    }

    /* ---------- 断点切换 ---------- */
    function initBreakpoint() {
        const mq = window.matchMedia(MOBILE_QUERY);
        const onChange = () => {
            const section = document.getElementById('avatarSection');
            if (!section) return;
            if (!mq.matches) {
                section.classList.remove('is-open');
                setScrim(false);
            }
            syncPortraitA11y();
        };
        if (mq.addEventListener) mq.addEventListener('change', onChange);
        else if (mq.addListener) mq.addListener(onChange);
    }

    /* ---------- 顶栏/状态同步 ---------- */
    function syncShellState() {
        if (typeof appState === 'undefined') return;

        const modeChip = document.getElementById('modeChip');
        const modeText = document.getElementById('modeChipText');
        if (modeText) modeText.textContent = appState.modelMode === 'local' ? '本地' : '在线';

        const ttsChip = document.getElementById('ttsChip');
        const ttsText = document.getElementById('ttsChipText');
        if (ttsText) ttsText.textContent = appState.voiceEnabled ? '语音开启' : '语音关闭';
        if (ttsChip) {
            ttsChip.classList.toggle('is-on', !!appState.voiceEnabled);
            const icon = ttsChip.querySelector('use');
            if (icon) icon.setAttribute('href', appState.voiceEnabled ? '#i-voice' : '#i-mute');
        }

        const modeIcon = modeChip ? modeChip.querySelector('use') : null;
        if (modeIcon) {
            modeIcon.setAttribute('href', appState.modelMode === 'local' ? '#i-chip' : '#i-cloud');
        }

        syncPortraitA11y();
    }

    /* ---------- 启动 ---------- */
    function initShell() {
        const input = document.getElementById('messageInput');
        if (input) {
            input.addEventListener('input', autoGrow);
            autoGrow();
        }

        initScrollPill();
        initWelcomeChips();
        initParallax();
        initRevealOrigin();
        initShortcuts();
        initBreakpoint();
        syncPortraitA11y();

        // 入场：让首帧淡入
        requestAnimationFrame(() => document.body.classList.add('is-ready'));
    }

    document.addEventListener('DOMContentLoaded', initShell);

    window.togglePortrait = togglePortrait;
    window.resetComposer = resetComposer;
    window.syncShellState = syncShellState;
})();
