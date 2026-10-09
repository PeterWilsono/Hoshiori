# -*- coding: utf-8 -*-
"""
主题配置文件 - 空灵科技 (Ethereal Cyber) 设计系统
灵感来源：崩坏星穹铁道 / 蔚蓝档案的清爽质感
"""

# 色彩体系 - 深邃通透的玻璃质感
COLORS = {
    # ===== 背景层次 (三层深度) =====
    "bg_root": "#11111b",         # 最底层 - 深空黑
    "bg_primary": "#1e1e2e",      # 主背景 - 聊天区
    "bg_secondary": "#181825",    # 侧边栏 - 角色视窗
    "bg_surface": "#313244",      # 卡片/输入框 - 磨砂表面
    "bg_hover": "#3d3d54",        # 悬停状态 - 微亮
    
    # ===== 玻璃边框与高光 =====
    "border_glass": "#45475a",    # 玻璃边缘反光
    "border_glow": "#585b70",     # 悬停时的光晕
    "border_accent": "#cba6f7",   # 强调边框（紫色光晕）
    
    # ===== 主题色 (情感色) =====
    "primary": "#89b4fa",         # 清透蓝 - 用户气泡/主按钮
    "primary_hover": "#7aa2f7",   # 蓝色悬停
    "primary_glow": "rgba(137, 180, 250, 0.3)",  # 蓝色光晕
    
    "secondary": "#b4befe",       # 薰衣草紫 - 次要操作
    "secondary_hover": "#a393ed",
    
    "accent": "#f5c2e7",          # 樱花粉 - 好感度/爱意
    "accent_hover": "#f2cdcd",
    "accent_glow": "rgba(245, 194, 231, 0.3)",  # 粉色光晕
    
    # ===== 功能色 =====
    "success": "#a6e3a1",         # 生命绿
    "success_hover": "#94d890",
    
    "warning": "#f9e2af",         # 温暖黄
    "warning_hover": "#f7d89e",
    
    "error": "#f38ba8",           # 警示红
    "error_hover": "#f17a97",
    
    "info": "#89dceb",            # 信息青
    "info_hover": "#7dd3fc",
    
    # ===== 文字色 (高对比度) =====
    "text_primary": "#cdd6f4",    # 主文字 - 亮白
    "text_secondary": "#a6adc8",  # 次要文字 - 蓝灰
    "text_muted": "#6c7086",      # 静音文字 - 深灰
    "text_ghost": "#585b70",      # 幽灵文字 - 极淡
    
    # ===== AI气泡 (磨砂深色) =====
    "ai_bubble": "#262637",       # AI消息背景 - 带紫调的深灰
    "ai_bubble_border": "#45475a", # AI气泡边框
    "ai_text": "#cdd6f4",         # AI文字 - 亮白
    
    # ===== 用户气泡 (渐变蓝) =====
    "user_bubble": "#89b4fa",     # 用户消息背景 - 清透蓝
    "user_bubble_alt": "#7aa2f7", # 用户气泡渐变色
    "user_text": "#ffffff",       # 用户文字 - 纯白
    
    # ===== 系统消息 =====
    "system_bubble": "#313244",
    "system_bubble_border": "#45475a",
    "system_text": "#a6adc8",
    
    # ===== 好感度颜色渐变 (光带效果) =====
    "affection_low": "#89b4fa",    # 蓝色 (0-40) - 初识
    "affection_mid": "#b4befe",    # 紫色 (40-70) - 熟悉
    "affection_high": "#f5c2e7",   # 粉色 (70-100) - 亲密
    "affection_glow": "rgba(245, 194, 231, 0.5)",  # 好感度光晕
}

# 情绪氛围色 (侧边栏背景 - 微妙的色调变化)
MOOD_COLORS = {
    "neutral": "#181825",   # 中性 - 标准深蓝
    "happy": "#1e2030",     # 开心 - 偏蓝
    "angry": "#2d1e1e",     # 生气 - 偏红
    "sad": "#1e1e2d",       # 悲伤 - 偏紫
    "shy": "#2d1e28"        # 害羞 - 偏粉
}

# 字体配置 (优化字号和间距)
FONTS = {
    "h1": ("Microsoft YaHei UI", 26, "bold"),      # 主标题 - 加大
    "h2": ("Microsoft YaHei UI", 20, "bold"),      # 二级标题
    "h3": ("Microsoft YaHei UI", 16, "bold"),      # 三级标题
    "body": ("Microsoft YaHei UI", 14),            # 正文
    "body_bold": ("Microsoft YaHei UI", 14, "bold"),
    "caption": ("Microsoft YaHei UI", 12),         # 说明文字
    "small": ("Microsoft YaHei UI", 10),           # 小字
    "metadata": ("Microsoft YaHei UI", 11),        # 元数据（时间戳等）
}

# 尺寸配置 - 玻璃质感设计令牌
DIMENSIONS = {
    # 圆角 (大圆角营造柔和感)
    "corner_radius_small": 8,
    "corner_radius_medium": 15,
    "corner_radius_large": 24,      # 大圆角
    "corner_radius_xlarge": 28,     # 超大圆角
    "corner_radius_capsule": 50,    # 胶囊形状
    
    # 组件尺寸
    "button_height": 45,            # 按钮高度 - 加大
    "input_height": 90,             # 输入框高度 - 加大
    "input_capsule_height": 60,     # 输入胶囊高度
    
    # 间距 (舒适的呼吸感)
    "padding_small": 12,
    "padding_medium": 16,           # 舒适间距
    "padding_large": 24,            # 宽松间距
    "padding_xlarge": 32,
    
    # 边框
    "border_thin": 1,               # 细边框 - 精致
    "border_medium": 2,             # 标准边框
    "border_thick": 3,              # 粗边框 - 强调
    
    # 特殊尺寸
    "affection_bar_height": 8,      # 好感度光带高度 - 细长
    "status_card_height": 120,      # 状态卡片高度
}

# Emoji 图标映射
ICONS = {
    "send": "✈",
    "new": "✨",
    "list": "📋",
    "role": "🎭",
    "settings": "⚙",
    "save": "💾",
    "delete": "🗑",
    "edit": "✏",
    "close": "✖",
    "reset": "🔄",
    "check": "✓",
    "avatar": "🖼",
}

# 情绪文本映射
MOOD_TEXT = {
    "neutral": "平静",
    "happy": "开心",
    "angry": "生气",
    "sad": "悲伤",
    "shy": "害羞"
}

# ===== 设计令牌总结 =====
DESIGN_TOKENS = {
    "style": "glass-morphism-simulated",  # 模拟玻璃形态
    "mode": "dark",                        # 深色模式
    "principle": "ethereal-cyber",         # 空灵科技
    "inspiration": "Honkai Star Rail / Blue Archive"
}