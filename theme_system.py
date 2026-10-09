# -*- coding: utf-8 -*-
"""
主题系统 - 支持多种视觉风格切换
修复: 移除RGBA颜色,使用纯十六进制颜色
"""
import json
import os
from typing import Dict, List, Callable


class Theme:
    """主题数据结构"""
    def __init__(self, name: str, config: Dict):
        self.name = name
        self.display_name = config["display_name"]
        self.icon = config["icon"]
        
        # 颜色配置
        self.colors = config["colors"]
        
        # 视觉效果
        self.effects = config["effects"]
        
        # 动画配置
        self.animations = config.get("animations", {
            "transition_duration": 300,  # ms
            "easing": "ease-in-out"
        })


# 预设主题库 (修复版 - 移除所有RGBA颜色)
PRESET_THEMES = {
    "glass": {
        "display_name": "🔮 幻境玻璃",
        "icon": "🔮",
        "colors": {
            # 背景层次
            "bg_root": "#0a0b0f",
            "bg_primary": "#141520",
            "bg_secondary": "#1a1b2e",
            "bg_surface": "#1e2030",
            "bg_hover": "#252740",
            
            # 文字颜色
            "text_primary": "#e8e9f0",
            "text_secondary": "#b4b7c9",
            "text_muted": "#6b7089",
            "text_ghost": "#4a4d63",
            
            # 强调色
            "primary": "#6366f1",
            "primary_hover": "#818cf8",
            "accent": "#a78bfa",
            "secondary": "#8b5cf6",
            "secondary_hover": "#a78bfa",
            
            # 功能色
            "success": "#10b981",
            "success_hover": "#34d399",
            "warning": "#f59e0b",
            "warning_hover": "#fbbf24",
            "error": "#ef4444",
            "error_hover": "#f87171",
            "info": "#06b6d4",
            "info_hover": "#22d3ee",
            
            # 边框与玻璃效果 (修复: 使用纯十六进制)
            "border_glass": "#3d3f5c",  # 替代 rgba(139, 92, 246, 0.15)
            "border_accent": "#5a4d8a",  # 替代 rgba(167, 139, 250, 0.3)
            
            # 气泡颜色
            "user_bubble": "#2d2f45",
            "user_text": "#e8e9f0",
            "ai_bubble": "#1a1b2e",
            "ai_text": "#b4b7c9",
            "ai_bubble_border": "#3d3f5c",  # 修复
            "system_bubble": "#1e2030",
            "system_text": "#8b5cf6",
            "system_bubble_border": "#3d3f5c",  # 修复
            
            # 好感度颜色
            "affection_high": "#10b981",
            "affection_mid": "#f59e0b",
            "affection_low": "#ef4444"
        },
        "effects": {
            "blur": 12,
            "opacity": 0.95,
            "corner_radius": {
                "small": 8,
                "medium": 12,
                "large": 16,
                "xlarge": 24
            },
            "border": {
                "thin": 1,
                "medium": 2,
                "thick": 3
            },
            "shadow": {
                "light": "0 2px 8px rgba(0,0,0,0.1)",
                "medium": "0 4px 16px rgba(0,0,0,0.2)",
                "heavy": "0 8px 32px rgba(0,0,0,0.3)"
            }
        }
    },
    
    "clay": {
        "display_name": "☁️ 软萌黏土",
        "icon": "☁️",
        "colors": {
            "bg_root": "#e0e5ec",
            "bg_primary": "#e0e5ec",
            "bg_secondary": "#e0e5ec",
            "bg_surface": "#e0e5ec",
            "bg_hover": "#d1d9e6",
            
            "text_primary": "#2d3748",
            "text_secondary": "#4a5568",
            "text_muted": "#718096",
            "text_ghost": "#a0aec0",
            
            "primary": "#9d8ec9",
            "primary_hover": "#b5a3d9",
            "accent": "#d4a5d4",
            "secondary": "#a0c4e0",
            "secondary_hover": "#b8d4ed",
            
            "success": "#81c995",
            "success_hover": "#9dd9ad",
            "warning": "#f6b93b",
            "warning_hover": "#f8ca6b",
            "error": "#e77f7f",
            "error_hover": "#ee9d9d",
            "info": "#6bb5d4",
            "info_hover": "#8fc7e0",
            
            "border_glass": "#d1d9e6",  # 黏土风格使用实色边框
            "border_accent": "#b5a3d9",
            
            "user_bubble": "#d1d9e6",
            "user_text": "#2d3748",
            "ai_bubble": "#f0f4f8",
            "ai_text": "#2d3748",
            "ai_bubble_border": "#d1d9e6",
            "system_bubble": "#e0e5ec",
            "system_text": "#9d8ec9",
            "system_bubble_border": "#d1d9e6",
            
            "affection_high": "#81c995",
            "affection_mid": "#f6b93b",
            "affection_low": "#e77f7f"
        },
        "effects": {
            "blur": 0,
            "opacity": 1.0,
            "corner_radius": {
                "small": 20,
                "medium": 25,
                "large": 30,
                "xlarge": 40
            },
            "border": {
                "thin": 0,
                "medium": 0,
                "thick": 0
            },
            "shadow": {
                "light": "9px 9px 16px rgba(163,177,198,0.6), -9px -9px 16px rgba(255,255,255,0.5)",
                "medium": "12px 12px 20px rgba(163,177,198,0.6), -12px -12px 20px rgba(255,255,255,0.5)",
                "heavy": "15px 15px 25px rgba(163,177,198,0.6), -15px -15px 25px rgba(255,255,255,0.5)"
            },
            "inset_shadow": "-5px -5px 10px rgba(255,255,255,0.8), 5px 5px 10px rgba(163,177,198,0.4)"
        }
    },
    
    "fresh": {
        "display_name": "🍃 清新日系",
        "icon": "🍃",
        "colors": {
            "bg_root": "#fdfbf7",
            "bg_primary": "#ffffff",
            "bg_secondary": "#f8f9fa",
            "bg_surface": "#ffffff",
            "bg_hover": "#f0f4f8",
            
            "text_primary": "#2c3e50",
            "text_secondary": "#5a6c7d",
            "text_muted": "#95a5a6",
            "text_ghost": "#bdc3c7",
            
            "primary": "#88c999",
            "primary_hover": "#a1d9b0",
            "accent": "#7fb3d5",
            "secondary": "#f7dc6f",
            "secondary_hover": "#f9e79f",
            
            "success": "#52c41a",
            "success_hover": "#73d13d",
            "warning": "#faad14",
            "warning_hover": "#ffc53d",
            "error": "#f5222d",
            "error_hover": "#ff4d4f",
            "info": "#1890ff",
            "info_hover": "#40a9ff",
            
            "border_glass": "#c9e4d4",  # 修复
            "border_accent": "#9ec9dd",  # 修复
            
            "user_bubble": "#e8f5e9",
            "user_text": "#2c3e50",
            "ai_bubble": "#ffffff",
            "ai_text": "#2c3e50",
            "ai_bubble_border": "#c9e4d4",  # 修复
            "system_bubble": "#f0f4f8",
            "system_text": "#7fb3d5",
            "system_bubble_border": "#c9e4d4",  # 修复
            
            "affection_high": "#52c41a",
            "affection_mid": "#faad14",
            "affection_low": "#f5222d"
        },
        "effects": {
            "blur": 4,
            "opacity": 1.0,
            "corner_radius": {
                "small": 8,
                "medium": 10,
                "large": 12,
                "xlarge": 16
            },
            "border": {
                "thin": 1,
                "medium": 2,
                "thick": 3
            },
            "shadow": {
                "light": "0 2px 4px rgba(0,0,0,0.05)",
                "medium": "0 4px 8px rgba(0,0,0,0.08)",
                "heavy": "0 8px 16px rgba(0,0,0,0.12)"
            }
        }
    },
    
    "dark": {
        "display_name": "🌙 深邃暗夜",
        "icon": "🌙",
        "colors": {
            "bg_root": "#000000",
            "bg_primary": "#0d0d0d",
            "bg_secondary": "#161616",
            "bg_surface": "#1a1a1a",
            "bg_hover": "#242424",
            
            "text_primary": "#ffffff",
            "text_secondary": "#d4d4d4",
            "text_muted": "#8c8c8c",
            "text_ghost": "#525252",
            
            "primary": "#3b82f6",
            "primary_hover": "#60a5fa",
            "accent": "#8b5cf6",
            "secondary": "#06b6d4",
            "secondary_hover": "#22d3ee",
            
            "success": "#10b981",
            "success_hover": "#34d399",
            "warning": "#f59e0b",
            "warning_hover": "#fbbf24",
            "error": "#ef4444",
            "error_hover": "#f87171",
            "info": "#06b6d4",
            "info_hover": "#22d3ee",
            
            "border_glass": "#2d3b5c",  # 修复
            "border_accent": "#4a3d6b",  # 修复
            
            "user_bubble": "#1a1a1a",
            "user_text": "#ffffff",
            "ai_bubble": "#0d0d0d",
            "ai_text": "#d4d4d4",
            "ai_bubble_border": "#2d3b5c",  # 修复
            "system_bubble": "#161616",
            "system_text": "#8b5cf6",
            "system_bubble_border": "#4a3d6b",  # 修复
            
            "affection_high": "#10b981",
            "affection_mid": "#f59e0b",
            "affection_low": "#ef4444"
        },
        "effects": {
            "blur": 8,
            "opacity": 0.98,
            "corner_radius": {
                "small": 6,
                "medium": 10,
                "large": 14,
                "xlarge": 20
            },
            "border": {
                "thin": 1,
                "medium": 2,
                "thick": 3
            },
            "shadow": {
                "light": "0 2px 8px rgba(0,0,0,0.4)",
                "medium": "0 4px 16px rgba(0,0,0,0.5)",
                "heavy": "0 8px 32px rgba(0,0,0,0.6)"
            }
        }
    }
}


class ThemeManager:
    """主题管理器"""
    
    def __init__(self, save_dir="baocun"):
        self.save_dir = save_dir
        self.theme_file = os.path.join(save_dir, "theme_config.json")
        
        # 当前主题
        self.current_theme_name = "glass"
        self.current_theme = None
        
        # 自定义主题
        self.custom_themes = {}
        
        # 主题切换回调
        self.change_callbacks: List[Callable] = []
        
        # 加载配置
        self.load_config()
        self.apply_theme(self.current_theme_name)
    
    def register_callback(self, callback: Callable):
        """注册主题切换回调"""
        self.change_callbacks.append(callback)
    
    def apply_theme(self, theme_name: str):
        """应用主题"""
        if theme_name in PRESET_THEMES:
            self.current_theme = Theme(theme_name, PRESET_THEMES[theme_name])
        elif theme_name in self.custom_themes:
            self.current_theme = Theme(theme_name, self.custom_themes[theme_name])
        else:
            # 默认主题
            self.current_theme = Theme("glass", PRESET_THEMES["glass"])
        
        self.current_theme_name = theme_name
        self.save_config()
        
        # 通知所有监听者
        for callback in self.change_callbacks:
            try:
                callback(self.current_theme)
            except Exception as e:
                print(f"主题切换回调错误: {e}")
        
        return self.current_theme
    
    def get_available_themes(self) -> List[Dict]:
        """获取可用主题列表"""
        themes = []
        
        # 预设主题
        for name, config in PRESET_THEMES.items():
            themes.append({
                "name": name,
                "display_name": config["display_name"],
                "icon": config["icon"],
                "type": "preset"
            })
        
        # 自定义主题
        for name, config in self.custom_themes.items():
            themes.append({
                "name": name,
                "display_name": config["display_name"],
                "icon": config.get("icon", "🎨"),
                "type": "custom"
            })
        
        return themes
    
    def create_custom_theme(self, name: str, base_theme: str, modifications: Dict):
        """创建自定义主题"""
        if base_theme not in PRESET_THEMES:
            base_theme = "glass"
        
        # 深拷贝基础主题
        import copy
        custom_config = copy.deepcopy(PRESET_THEMES[base_theme])
        
        # 应用修改
        if "display_name" in modifications:
            custom_config["display_name"] = modifications["display_name"]
        if "colors" in modifications:
            custom_config["colors"].update(modifications["colors"])
        if "effects" in modifications:
            custom_config["effects"].update(modifications["effects"])
        
        self.custom_themes[name] = custom_config
        self.save_config()
        
        return custom_config
    
    def delete_custom_theme(self, name: str):
        """删除自定义主题"""
        if name in self.custom_themes:
            del self.custom_themes[name]
            self.save_config()
            return True
        return False
    
    def save_config(self):
        """保存配置"""
        try:
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)
            
            config = {
                "current_theme": self.current_theme_name,
                "custom_themes": self.custom_themes
            }
            
            with open(self.theme_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存主题配置失败: {e}")
    
    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.theme_file):
                with open(self.theme_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.current_theme_name = config.get("current_theme", "glass")
                    self.custom_themes = config.get("custom_themes", {})
        except Exception as e:
            print(f"加载主题配置失败: {e}")
            self.current_theme_name = "glass"
            self.custom_themes = {}
    
    def get_color(self, key: str, fallback: str = "#ffffff") -> str:
        """获取颜色值"""
        if not self.current_theme:
            return fallback
        return self.current_theme.colors.get(key, fallback)
    
    def get_effect(self, category: str, key: str = None):
        """获取效果参数"""
        if not self.current_theme:
            return None
        
        effect = self.current_theme.effects.get(category)
        if key and isinstance(effect, dict):
            return effect.get(key)
        return effect