// ===== 启动画面 - 星织 =====
// 目标：从窗口出现到页面可用之间的这段等待，要有东西可看，而且看得出进度。
// 进度不是假的：initApp 里每过一关就往前推一截，没到的地方由 creep 慢慢爬。

(function () {
    'use strict';

    var el = document.getElementById('bootScreen');
    if (!el) return;

    var fill = document.getElementById('bootFill');
    var statusEl = document.getElementById('bootStatus');

    var progress = 8;
    var done = false;
    var creepTimer = null;
    var statusTimer = null;

    var LABELS = {
        start: '正在点亮灯…'
    };

    function paint() {
        if (!fill) return;
        var value = Math.max(0, Math.min(100, progress));
        fill.style.width = value.toFixed(1) + '%';
    }

    /**
     * 推进启动进度
     * @param {number} value 目标百分比（只会前进不会后退）
     * @param {string} [label] 状态文案
     */
    function step(value, label) {
        if (done) return;
        if (typeof value === 'number' && value > progress) {
            progress = value;
            paint();
        }
        if (label && statusEl && statusEl.textContent !== label) {
            statusEl.classList.add('is-swapping');
            clearTimeout(statusTimer);
            statusTimer = setTimeout(function () {
                statusEl.textContent = label;
                statusEl.classList.remove('is-swapping');
            }, 130);
        }
    }

    // 没有里程碑的时候自己往前爬，最多爬到 88%，永远不会假装完成
    function creep() {
        if (done) return;
        progress = Math.min(88, progress + Math.max(0.35, (88 - progress) * 0.05));
        paint();
    }

    /**
     * 收尾：填满进度条，淡出，然后告诉后端“前端已经能用了”
     */
    function finish() {
        if (done) return;
        done = true;
        clearInterval(creepTimer);
        clearTimeout(statusTimer);

        progress = 100;
        paint();
        if (statusEl) statusEl.textContent = '好了';

        try {
            if (typeof eel !== 'undefined' && eel.app_ready_from_web) {
                eel.app_ready_from_web()();
            }
        } catch (err) { /* 后端不在也无所谓，画面照样要收 */ }

        setTimeout(function () {
            el.classList.add('is-done');
            setTimeout(function () {
                if (el.parentNode) el.parentNode.removeChild(el);
            }, 720);
        }, 300);
    }

    window.BootScreen = {
        step: step,
        finish: finish,
        isDone: function () { return done; }
    };

    paint();
    if (statusEl && !statusEl.textContent.trim()) statusEl.textContent = LABELS.start;
    creepTimer = setInterval(creep, 240);

    // 兜底：真的卡住了也别让启动画面永远挡在前面
    setTimeout(function () {
        if (!done) finish();
    }, 20000);
})();
