// ===== 星织 · 情绪表情系统 =====
//
// 为什么不用 expression 文件：
//   本项目的模型（yumi / nahida / murasame）要么在 model3.json 里根本没注册
//   Expressions，要么 exp3 里只有一条自定义参数（星星眼、泪汪汪…）。
//   所以 model.expression('sad') 一直是静默失败的——这就是"看不出高兴和伤心"的原因。
//
// 这里的做法：把情绪翻译成 Cubism 的**核心参数**偏移，逐帧写进去。
//   嘴型 ParamMouthForm / 张嘴 ParamMouthOpenY / 眉毛 ParamBrowLY+RX+Angle
//   / 眼睛微笑 ParamEyeSmile / 眼睛开合 ParamEyeOpen / 脸颊 ParamCheek
//   / 头部倾斜 ParamAngleZ / 身体倾斜 ParamBodyAngleZ
// 参数名在各模型间不统一（ParamEyeLSmile vs ParamEyeSmileL），所以每个语义给一组
// 候选名，取模型里真实存在的那个；范围也直接问模型要，不写死。
//
// 眨眼由本模块接管：内置眨眼每帧会把眼睛开合写回 1，情绪做不出"眼皮耷拉"，
// 所以关掉它，自己按情绪的睁眼度重做一套（含偶尔的连眨）。

var EmotionRig = (function () {
    'use strict';

    // 语义 → 候选参数名（按优先级）
    var PARAM_ALIASES = {
        mouthForm: ['ParamMouthForm'],
        mouthOpen: ['ParamMouthOpenY', 'ParamJawOpen'],
        mouthShrug: ['ParamMouthShrug'],
        eyeSmileL: ['ParamEyeLSmile', 'ParamEyeSmileL'],
        eyeSmileR: ['ParamEyeRSmile', 'ParamEyeSmileR'],
        eyeOpenL: ['ParamEyeLOpen', 'ParamEyeOpenL'],
        eyeOpenR: ['ParamEyeROpen', 'ParamEyeOpenR'],
        browYL: ['ParamBrowLY', 'ParamBrowYL'],
        browYR: ['ParamBrowRY', 'ParamBrowYR'],
        browAngleL: ['ParamBrowLAngle', 'ParamBrowAngleL'],
        browAngleR: ['ParamBrowRAngle', 'ParamBrowAngleR'],
        blush: ['ParamCheek', 'Paramsmileshy', 'ParamCheekpuff'],
        angleZ: ['ParamAngleZ'],
        bodyZ: ['ParamBodyAngleZ'],
        // 模型自带的"贴脸效果"参数，有就顺手用上
        fxStar: ['Paramxingxing', 'Paramxingxingyan'],
        fxTear: ['Paramleiwangwang', 'Paramtear'],
        fxDark: ['Paramheilian'],
        fxHeart: ['Paramheart'],
        fxDizzy: ['Paramwenxiang']
    };

    // 情绪 → 参数偏移（face 为叠加量，eye 为睁眼系数）
    // 数值参考 Cubism 标准参数区间：MouthForm/Brow 为 -1~1，EyeSmile 0~1，角度为度。
    var MOODS = {
        neutral: {
            label: '平静', eye: 1.0,
            face: {}
        },
        happy: {
            label: '愉悦', eye: 1.0, bob: { amp: 0.6, freq: 3.0 },
            face: {
                mouthForm: 0.95, mouthOpen: 0.18, eyeSmileL: 0.86, eyeSmileR: 0.86,
                browYL: 0.5, browYR: 0.5, browAngleL: 0.18, browAngleR: 0.18,
                blush: 0.22, angleZ: 3.6, bodyZ: 1.6, fxStar: 1
            }
        },
        sad: {
            label: '低落', eye: 0.55, bob: { amp: 0.16, freq: 1.1 },
            face: {
                mouthForm: -0.9, mouthOpen: 0.02, mouthShrug: 0.35,
                browYL: -0.62, browYR: -0.62, browAngleL: -0.8, browAngleR: -0.8,
                eyeSmileL: 0, eyeSmileR: 0,
                blush: 0, angleZ: -4.2, bodyZ: -1.6, fxTear: 1
            }
        },
        angry: {
            label: '愠怒', eye: 0.78, bob: { amp: 0.24, freq: 2.4 },
            face: {
                mouthForm: -0.7, mouthOpen: 0.1, mouthShrug: 0.45,
                browYL: -0.8, browYR: -0.8, browAngleL: 0.85, browAngleR: 0.85,
                blush: 0.12, angleZ: -2, bodyZ: -1.1, fxDark: 1
            }
        },
        shy: {
            label: '羞怯', eye: 0.7, bob: { amp: 0.32, freq: 1.7 },
            face: {
                mouthForm: 0.6, mouthOpen: 0.02, mouthShrug: 0.35,
                eyeSmileL: 0.65, eyeSmileR: 0.65,
                browYL: 0.18, browYR: 0.18, browAngleL: -0.3, browAngleR: -0.3,
                blush: 1, angleZ: 6, bodyZ: 2.6
            }
        },
        surprised: {
            label: '惊讶', eye: 1.16, bob: { amp: 0.1, freq: 2.0 },
            face: {
                mouthOpen: 0.8, mouthForm: -0.12,
                browYL: 0.8, browYR: 0.8, browAngleL: 0.15, browAngleR: 0.15,
                blush: 0.1, fxStar: 0.7
            }
        },
        love: {
            label: '心动', eye: 0.95, bob: { amp: 0.4, freq: 1.9 },
            face: {
                mouthForm: 0.66, mouthOpen: 0.05, eyeSmileL: 0.7, eyeSmileR: 0.7,
                browYL: 0.3, browYR: 0.3, blush: 1, angleZ: 4.2, bodyZ: 1.8, fxHeart: 1
            }
        },
        sleepy: {
            label: '困倦', eye: 0.3, bob: { amp: 0.15, freq: 0.9 },
            face: { mouthForm: -0.15, mouthOpen: 0.16, browYL: -0.1, browYR: -0.1, angleZ: -2 }
        }
    };

    // 后端可能送来 joy / sadness / love 这类词，统一成上面几种
    var ALIAS = {
        joy: 'happy', joyful: 'happy', happiness: 'happy', excited: 'happy', delight: 'happy',
        glad: 'happy', cheerful: 'happy', amused: 'happy', playful: 'happy',
        sadness: 'sad', sorrow: 'sad', gloomy: 'sad', lonely: 'sad', down: 'sad',
        crying: 'sad', melancholy: 'sad',
        anger: 'angry', rage: 'angry', annoyed: 'angry', irritated: 'angry',
        disgust: 'angry', frustrated: 'angry',
        fear: 'surprised', surprise: 'surprised', shocked: 'surprised', nervous: 'surprised',
        anxious: 'surprised', confused: 'surprised', awe: 'surprised',
        shyness: 'shy', embarrassed: 'shy', bashful: 'shy', timid: 'shy', flustered: 'shy',
        trust: 'neutral', anticipation: 'neutral', calm: 'neutral', peaceful: 'neutral',
        tired: 'sleepy', exhausted: 'sleepy', bored: 'sleepy'
    };

    function clamp(v, lo, hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    function normalize(mood) {
        if (!mood) return 'neutral';
        var key = String(mood).trim().toLowerCase();
        if (MOODS[key]) return key;
        if (ALIAS[key]) return ALIAS[key];
        return 'neutral';
    }

    /**
     * 情绪骨架：绑定一个已加载的模型
     * @param {object} model - PIXI.live2d.Live2DModel
     */
    function Rig(model) {
        this.model = model;
        this.internal = model && model.internalModel;
        this.core = this.internal && this.internal.coreModel;

        this.mood = 'neutral';
        this.strength = 1;
        this.target = {};
        this.cur = {};
        this.eyeTarget = 1;
        this.eyeCur = 1;
        this.writes = [];
        this.applied = {};      // 上一帧我往这个参数里加了多少（用来扣掉自己，避免累加漂移）
        this.clock = 0;
        this.talking = false;   // 是否正在说话（嘴型交给这里，别的代码别再抢）
        this.talkPhase = 0;
        this.talkLevel = 0;
        this.lastAt = 0;
        this.born = performance.now();

        // 眨眼状态
        this.blink = {
            phase: 'idle',       // idle | closing | hold | opening
            value: 1,
            t: 0,
            hold: 0,
            next: 2.2 + Math.random() * 3,
            again: false
        };

        this._resolve();
        this._takeOverBlink();
        this._bind();
    }

    Rig.prototype._resolve = function () {
        var core = this.core;
        if (!core) return;

        var self = this;
        Object.keys(PARAM_ALIASES).forEach(function (key) {
            var names = PARAM_ALIASES[key];
            for (var i = 0; i < names.length; i++) {
                var id = names[i];
                var index = -1;
                try { index = core.getParameterIndex(id); } catch (e) { index = -1; }
                if (index < 0) continue;

                // 有些模型同时有两套（ParamCheek 和 Paramsmileshy），全都写上效果更明显
                var min = -1, max = 1;
                try {
                    var lo = core.getParameterMinimumValue(id);
                    var hi = core.getParameterMaximumValue(id);
                    if (typeof lo === 'number') min = lo;
                    if (typeof hi === 'number') max = hi;
                } catch (e) { }
                self.writes.push({ key: key, id: id, min: min, max: max });
                self.cur[key] = 0;
            }
        });

        // 一个情绪参数都没找到就说明这个模型不适合这套骨架，直接标记停用
        this.enabled = this.writes.length > 0;
        if (!this.enabled) console.warn('[情绪] 模型没有可用的表情参数，跳过');
    };

    /** 内置眨眼会每帧把眼睛写回 1，接管前先关掉它 */
    Rig.prototype._takeOverBlink = function () {
        try {
            if (this.internal && this.internal.eyeBlink) this.internal.eyeBlink = null;
        } catch (e) { }
    };

    Rig.prototype._bind = function () {
        if (!this.internal || !this.internal.on) return;
        var self = this;
        // 动作和表情都算完之后再叠加情绪，这样不会被打回去
        this.internal.on('afterMotionUpdate', function () {
            try { self._frame(); } catch (e) { }
        });
    };

    /**
     * 设定情绪
     * @param {string} mood
     * @param {number} [strength] - 0~1，情绪浓度
     */
    Rig.prototype.setMood = function (mood, strength) {
        var key = normalize(mood);
        this.mood = key;
        this.strength = typeof strength === 'number' ? clamp(strength, 0, 1) : 1;

        var cfg = MOODS[key] || MOODS.neutral;
        var target = {};
        var self = this;

        Object.keys(this.cur).forEach(function (k) { target[k] = 0; });
        Object.keys(cfg.face || {}).forEach(function (k) {
            if (self.cur[k] !== undefined) target[k] = cfg.face[k] * self.strength;
        });

        this.target = target;
        this.eyeTarget = 1 + ((cfg.eye || 1) - 1) * this.strength;
        this.bob = cfg.bob || null;
    };

    /**
     * 说话开关。开启后嘴型由这里逐帧驱动，情绪只负责嘴角的弧度。
     * 之所以要接管：如果外面用 setInterval 直接写 ParamMouthOpenY，
     * 会和这里的"扣掉自己上一帧"记账打架，嘴会抽。
     */
    Rig.prototype.setTalking = function (on) {
        this.talking = !!on;
        if (on) this.talkPhase = 0;
    };

    /** 只调浓度，不换情绪（PAD 用） */
    Rig.prototype.setStrength = function (strength) {
        if (typeof strength !== 'number') return;
        if (Math.abs(strength - this.strength) < 0.02) return;
        this.setMood(this.mood, strength);
    };

    Rig.prototype._tickBlink = function (dt) {
        var b = this.blink;

        if (b.phase === 'idle') {
            b.next -= dt;
            if (b.next <= 0) {
                b.phase = 'closing';
                b.t = 0;
                b.again = Math.random() < 0.18;
            }
        } else if (b.phase === 'closing') {
            b.t += dt / 0.055;
            if (b.t >= 1) { b.t = 1; b.phase = 'hold'; b.hold = 0.035; }
        } else if (b.phase === 'hold') {
            b.hold -= dt;
            if (b.hold <= 0) { b.phase = 'opening'; b.t = 1; }
        } else if (b.phase === 'opening') {
            b.t -= dt / 0.11;
            if (b.t <= 0) {
                b.t = 0;
                if (b.again) {
                    b.again = false;
                    b.phase = 'closing';
                } else {
                    b.phase = 'idle';
                    b.next = 2.4 + Math.random() * 3.6;
                }
            }
        }

        var closed = (b.phase === 'closing' || b.phase === 'opening') ? b.t
            : (b.phase === 'hold' ? 1 : 0);
        b.value = 1 - closed * 0.97;
    };

    Rig.prototype._frame = function () {
        if (!this.enabled || !this.core) return;

        var now = performance.now();
        if (!this.lastAt) this.lastAt = now;
        var dt = (now - this.lastAt) / 1000;
        this.lastAt = now;
        if (dt > 0.12) dt = 0.12;   // 窗口卡了一下时不要瞬移
        this.clock += dt;

        this._tickBlink(dt);

        // 情绪过渡：约 260ms 到位，短于这个会显得生硬
        var k = 1 - Math.pow(0.0016, dt);
        var self = this;
        Object.keys(this.target).forEach(function (key) {
            var cur = self.cur[key] || 0;
            self.cur[key] = cur + (self.target[key] - cur) * k;
        });
        this.eyeCur += (this.eyeTarget - this.eyeCur) * k;

        // 说话时嘴的开合：两个不同频率叠在一起，比纯正弦像人在讲话
        if (this.talking) {
            this.talkPhase += dt * 11.5;
            var a1 = Math.abs(Math.sin(this.talkPhase));
            var a2 = Math.abs(Math.sin(this.talkPhase * 0.43 + 1.7));
            var target = 0.16 + (a1 * 0.72 + a2 * 0.28) * 0.62;
            this.talkLevel += (target - this.talkLevel) * 0.45;
        } else if (this.talkLevel > 0.001) {
            this.talkLevel *= 0.72;           // 收尾时把嘴合上，别硬切
        }

        // 轻微的身体晃动，让"高兴"真的有起伏
        var bob = 0;
        if (this.bob) {
            bob = Math.sin(this.clock * this.bob.freq) * (this.bob.amp || 0) * this.strength;
        }

        var core = this.core;
        for (var i = 0; i < this.writes.length; i++) {
            var w = this.writes[i];
            var value;

            if (w.key === 'eyeOpenL' || w.key === 'eyeOpenR') {
                value = clamp(this.eyeCur * this.blink.value, w.min, w.max);
                core.setParameterValueById(w.id, value);
                continue;
            }

            var offset = this.cur[w.key] || 0;
            if (w.key === 'angleZ' || w.key === 'bodyZ') offset += bob;
            if (w.key === 'mouthOpen' && this.talkLevel > 0.001) {
                offset = Math.max(offset, this.talkLevel);
            }
            if (w.key === 'mouthForm' && this.talkLevel > 0.001) {
                // 说话时嘴角别太夸张，不然像在咧嘴
                offset = offset * 0.6 + 0.18 * this.talkLevel;
            }

            // 关键：参数每帧都被动作重置时，读到的是干净值；
            // 没被重置时读到的是"上一帧我写进去的值"，必须先把自己的份额扣掉，
            // 否则同一份偏移会一帧帧累加，最后全部顶到上限。
            var mine = this.applied[w.id] || 0;
            if (Math.abs(offset) < 0.0008 && Math.abs(mine) < 0.0008) {
                this.applied[w.id] = 0;
                continue;
            }

            var raw = core.getParameterValueById(w.id);
            var clean = raw - mine;
            var next = clamp(clean + offset, w.min, w.max);
            core.setParameterValueById(w.id, next);
            this.applied[w.id] = next - clean;
        }
    };

    Rig.prototype.destroy = function () {
        this.enabled = false;
        this.core = null;
        this.model = null;
    };

    return {
        create: function (model) { return new Rig(model); },
        normalize: normalize,
        moods: MOODS
    };
})();
