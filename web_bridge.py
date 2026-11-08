# -*- coding: utf-8 -*-
"""
Web Bridge - Eel集成层
连接Python后端和Web前端的桥接层
"""
import eel
import sys
import os
import base64
import re
import socket
import threading
import traceback
import time
import hashlib
from datetime import datetime

import app_paths
import boot
import window_shell


# ⭐ 全局版本号 - 使用时间戳确保每次启动都是新版本
APP_VERSION = str(int(time.time()))

_TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _display_title(conv):
    """对话的显示标题：优先用自动生成的「首句」，其次退回存档标题。"""
    title = (conv.get('title') or '').strip() or '新对话'
    if title.startswith('对话 '):
        for msg in conv.get('messages', []):
            if msg.get('role') in ('user', '你') and msg.get('content'):
                text = re.sub(r'\s+', ' ', msg['content']).strip()
                if text:
                    return text[:22] + ('…' if len(text) > 22 else '')
    return title


def _to_epoch(value):
    """把对话里保存的时间字段统一成 epoch 秒，供前端格式化。

    历史数据里 last_interaction_time 是 '2026-11-08 17:20' 这样的字符串，
    新数据可能是数字。解析不出来时返回 0，前端会显示为「更早」。
    """
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        for fmt in _TIME_FORMATS:
            try:
                return int(datetime.strptime(text, fmt).timestamp())
            except ValueError:
                continue
        try:
            return int(float(text))
        except ValueError:
            return 0
    return 0


def get_resource_path(relative_path):
    """获取资源文件路径（支持打包后）"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller打包后
        return os.path.join(sys._MEIPASS, relative_path)
    # 开发环境
    return os.path.join(os.path.abspath("."), relative_path)


def _dir_size(path):
    """目录占用（MB），设置面板里给用户一个“占了多少地方”的概念。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except Exception:
                    continue
    except Exception:
        return 0
    return round(total / 1024.0 / 1024.0, 1)


def get_file_hash(filepath):
    """获取文件的MD5哈希值（用于缓存破坏）"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()[:8]
    except:
        pass
    return APP_VERSION


class WebBridge:
    """Web桥接类 - 连接Python和JavaScript"""
    
    def __init__(self, app_instance):
        """
        初始化Web桥接
        Args:
            app_instance: 主应用实例（重构后的main.py中的类实例）
        """
        self.app = app_instance
        self.setup_eel_functions()
    
    def setup_eel_functions(self):
        """设置所有Eel暴露的函数"""
        
        # ===== 主题相关 =====
        # ===== 版本相关 =====
        @eel.expose
        def get_app_version():
            """获取应用版本号（用于缓存破坏）"""
            return APP_VERSION
        
        @eel.expose
        def get_current_theme():
            """获取当前主题"""
            try:
                return self.app.theme_manager.current_theme_name
            except Exception as e:
                print(f"获取主题错误: {e}")
                return "glass"
        
        @eel.expose
        def save_theme(theme_name):
            """保存主题"""
            try:
                self.app.theme_manager.apply_theme(theme_name)
                return True
            except Exception as e:
                print(f"保存主题错误: {e}")
                return False
        
        # ===== 应用状态相关 =====
        @eel.expose
        def get_app_state():
            """获取应用状态"""
            try:
                # 获取好感度
                affection = 50
                if hasattr(self.app.conversation_manager, 'get_affection'):
                    affection = self.app.conversation_manager.get_affection()
                
                return {
                    'voiceEnabled': self.app.voice_enabled,
                    'avatarVisible': self.app.avatar_visible,
                    'modelMode': self.app.config_manager.model_mode,
                    'affection': affection,
                    'mood': self.app.current_mood  # 修正：从app获取current_mood
                }
            except Exception as e:
                print(f"获取状态错误: {e}")
                traceback.print_exc()
                return {}
        
        @eel.expose
        def save_avatar_visibility(visible):
            """保存立绘显示状态"""
            try:
                self.app.config_manager.show_avatar = visible
                self.app.avatar_visible = visible
                self.app.config_manager.save_config()
                return True
            except Exception as e:
                print(f"保存立绘显示状态错误: {e}")
                return False
        
        # ===== 立绘相关 =====
        @eel.expose
        def get_avatar_path(mood):
            """获取立绘路径 (返回Base64编码图片)"""
            try:
                if mood in self.app.avatar_images and self.app.avatar_images[mood]:
                    file_path = self.app.avatar_images[mood]
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as image_file:
                            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                            return f"data:image/png;base64,{encoded_string}"
                return ""
            except Exception as e:
                print(f"获取立绘错误: {e}")
                return ""
        
        # ===== 消息相关 =====
        @eel.expose
        def send_message_from_web(message):
            """从Web发送消息"""
            try:
                if message:
                    self.app.process_message(message)
                    return True
                return False
            except Exception as e:
                print(f"发送消息错误: {e}")
                return False
        
        @eel.expose
        def get_current_conversation():
            """获取当前对话"""
            try:
                conv_id = self.app.conversation_manager.current_conversation_id
                conv = self.app.conversation_manager.conversations.get(conv_id, {})
                
                # 清理消息内容（移除JSON块）
                messages = []
                for msg in conv.get('messages', []):
                    clean_msg = msg.copy()
                    # 对AI消息进行清理
                    if msg['role'] == 'assistant':
                        clean_msg['content'] = self.app._clean_ai_message(msg['content'])
                    # 对用户消息清理文件内容标记
                    elif msg['role'] == 'user':
                        clean_msg['content'] = re.sub(r'\n\n--- 文件内容.*?---\n.*', '', msg['content'], flags=re.DOTALL)
                    messages.append(clean_msg)
                
                return {
                    'id': str(conv_id),
                    'title': _display_title(conv),
                    'messages': messages,
                    'timestamp': _to_epoch(conv.get('last_interaction_time'))
                }
            except Exception as e:
                print(f"获取对话错误: {e}")
                return {'messages': []}
        
        # ===== 对话列表相关 =====
        @eel.expose
        def get_conversations_list():
            """获取对话列表"""
            try:
                convs = []
                current_id = self.app.conversation_manager.current_conversation_id

                for conv_id, conv_data in self.app.conversation_manager.conversations.items():
                    convs.append({
                        'id': str(conv_id),
                        'title': _display_title(conv_data),
                        'timestamp': _to_epoch(conv_data.get('last_interaction_time')),
                        'message_count': len(conv_data.get('messages', [])),
                        'is_current': conv_id == current_id
                    })

                # 按时间倒序排序
                convs.sort(key=lambda x: x['timestamp'], reverse=True)
                return convs
            except Exception as e:
                print(f"获取对话列表错误: {e}")
                traceback.print_exc()
                return []
        
        @eel.expose
        def load_conversation_from_web(conv_id):
            """加载指定对话"""
            try:
                # 转换为整数（JavaScript传过来的是字符串）
                conv_id = int(conv_id)
                self.app.load_conversation(conv_id)
                return True
            except Exception as e:
                print(f"加载对话错误: {e}")
                return False
        
        @eel.expose
        def new_conversation_from_web():
            """新建对话"""
            try:
                self.app.new_conversation()
                return True
            except Exception as e:
                print(f"新建对话错误: {e}")
                return False
        
        @eel.expose
        def delete_conversation_from_web(conv_id):
            """删除对话

            返回结构化的结果，前端据此决定是否需要重新载入对话区。
            注意：删除会引起 ID 重排，调用后必须重新拉取对话列表。
            """
            try:
                conv_id = int(conv_id)
                manager = self.app.conversation_manager
                was_current = conv_id == manager.current_conversation_id

                ok, message, current_id = manager.delete_conversation(conv_id)

                # 删掉的是当前对话：同步切换主程序状态，重建记忆图谱
                if ok and was_current and current_id is not None:
                    self.app.load_conversation(current_id)

                remaining = len(manager.conversations)
                return {
                    'success': bool(ok),
                    'message': message,
                    'wasCurrent': bool(was_current),
                    'currentId': str(current_id) if current_id is not None else None,
                    'remaining': remaining
                }
            except Exception as e:
                print(f"删除对话错误: {e}")
                traceback.print_exc()
                return {
                    'success': False,
                    'message': str(e),
                    'wasCurrent': False,
                    'currentId': None,
                    'remaining': 0
                }

        @eel.expose
        def quit_app_from_web():
            """从界面退出程序（前端已做过确认）"""
            try:
                self.app.conversation_manager.save_conversations()
                print("👋 用户从界面关闭了星织")
            except Exception as e:
                print(f"退出前保存失败: {e}")

            def _exit():
                win = getattr(self.app, 'window', None)
                if win is not None:
                    try:
                        win.destroy()
                    except Exception:
                        pass
                try:
                    window_shell.close_window()
                except Exception:
                    pass
                time.sleep(0.25)
                os._exit(0)

            # 留一点时间让前端收到返回值、播放收场动画
            import threading
            threading.Timer(0.45, _exit).start()
            return True

        @eel.expose
        def begin_window_drag():
            """窗口栏按下时交给系统拖动"""
            try:
                return window_shell.begin_drag()
            except Exception:
                return False

        @eel.expose
        def minimize_window():
            # frameless 窗口上 pywebview 的 minimize() 可能不生效，直接交给系统
            try:
                if window_shell.minimize():
                    return True
            except Exception:
                pass
            win = getattr(self.app, 'window', None)
            if win is not None:
                try:
                    win.minimize()
                    return True
                except Exception:
                    pass
            return False
        
        @eel.expose
        def app_ready_from_web():
            """前端画出第一帧了：把启动图撤掉，用户可以开始用了"""
            boot.log("前端就绪")
            close_splash("前端就绪")
            # 界面可以用了，再在后台把发请求要用的库热起来
            try:
                from api_handler import prewarm_http
                prewarm_http()
            except Exception:
                pass
            # 语音的音频设备也放到后台开，免得用户点开语音时卡一下
            try:
                self.app.tts_manager.prewarm()
            except Exception:
                pass
            return True

        # ===== 存储位置 =====
        @eel.expose
        def get_app_paths():
            """当前程序位置 / 数据位置，给设置面板显示"""
            try:
                info = app_paths.describe()
                info["data_size"] = _dir_size(info["data_dir"])
                return info
            except Exception as e:
                print(f"读取路径信息失败: {e}")
                return {}

        @eel.expose
        def open_data_dir():
            """在资源管理器里打开数据目录"""
            return app_paths.open_path(app_paths.data_dir())

        @eel.expose
        def pick_data_dir():
            """弹系统文件夹选择框，返回用户选的路径（取消返回空串）"""
            try:
                import tkinter as tk
                from tkinter import filedialog

                root = tk.Tk()
                root.withdraw()
                root.wm_attributes('-topmost', 1)
                root.update()
                path = filedialog.askdirectory(
                    parent=root,
                    title="选择星织保存数据的位置",
                    mustexist=False,
                    initialdir=os.path.dirname(app_paths.data_dir()) or app_paths.data_dir(),
                )
                root.destroy()
                return path or ""
            except Exception as e:
                print(f"选择目录失败: {e}")
                return ""

        @eel.expose
        def change_data_dir(new_dir):
            """切换数据目录（会把现有的对话一起搬过去），需要重启才完全生效"""
            try:
                old = app_paths.data_dir()
                ok, message = app_paths.set_data_dir(new_dir, migrate=True)
                print(("📁 " if ok else "⚠️ ") + message)
                return {"success": ok, "message": message, "old": old,
                        "current": app_paths.data_dir()}
            except Exception as e:
                print(f"切换数据目录失败: {e}")
                return {"success": False, "message": str(e)}

        @eel.expose
        def reset_data_dir():
            """恢复自动选址"""
            try:
                app_paths.reset_data_dir()
                return {"success": True, "current": app_paths.resolve_data_dir()}
            except Exception as e:
                return {"success": False, "message": str(e)}

        @eel.expose
        def restart_app():
            """重启自己：先把当前对话落盘，再拉起一个新进程"""
            try:
                self.app.conversation_manager.save_conversations()
            except Exception:
                pass
            try:
                self.app.config_manager.save_config()
            except Exception:
                pass

            def _restart():
                try:
                    if getattr(sys, 'frozen', False):
                        os.startfile(sys.executable)  # noqa: S606
                    else:
                        import subprocess
                        subprocess.Popen([sys.executable, os.path.join(app_paths.app_root(), 'main.py')])
                except Exception as exc:
                    print(f"重启失败: {exc}")
                time.sleep(0.3)
                os._exit(0)

            import threading
            threading.Timer(0.5, _restart).start()
            return True

        # ===== 语音相关 =====
        @eel.expose
        def toggle_voice_from_web():
            """切换语音开关"""
            try:
                self.app.toggle_voice()
                return self.app.voice_enabled
            except Exception as e:
                print(f"切换语音错误: {e}")
                return False
        
        @eel.expose
        def get_tts_voices():
            """获取可用的TTS声音列表"""
            try:
                return self.app.tts_manager.get_available_voices()
            except Exception as e:
                print(f"获取TTS声音错误: {e}")
                return []
        
        @eel.expose
        def set_tts_voice(voice_id):
            """设置TTS声音"""
            try:
                self.app.tts_manager.set_voice(voice_id)
                return True
            except Exception as e:
                print(f"设置TTS声音错误: {e}")
                return False
        
        @eel.expose
        def get_current_tts_voice():
            """获取当前TTS声音"""
            try:
                return self.app.tts_manager.edge_voice
            except:
                return "zh-CN-XiaoyiNeural"
        
        # ===== 模型模式相关 =====
        @eel.expose
        def toggle_model_mode_from_web():
            """切换模型模式"""
            try:
                # 调用ConfigManager的切换方法
                new_mode = self.app.config_manager.switch_model_mode()
                
                # 获取当前模式的模型名称
                model_name = self.app.config_manager.local_model if new_mode == "local" else self.app.config_manager.online_model
                
                return {
                    "mode": new_mode,
                    "mode_name": "本地模式" if new_mode == "local" else "在线模式",
                    "model": model_name
                }
            except Exception as e:
                print(f"切换模型模式错误: {e}")
                return {'mode': 'local', 'mode_name': '本地模型', 'model': ''}
        
        # ===== 设置相关 =====
        @eel.expose
        def get_settings():
            """获取设置"""
            try:
                mode = self.app.config_manager.model_mode
                provider = self.app.config_manager.api_provider
                thinking_mode = self.app.config_manager.thinking_mode
                web_search = self.app.config_manager.web_search_enabled
                
                if mode == "local":
                    return {
                        'model_mode': 'local',
                        'api_provider': provider,
                        'thinking_mode': 'disabled',
                        'web_search_enabled': False,
                        'api_endpoint': self.app.config_manager.local_api_endpoint,
                        'api_key': self.app.config_manager.local_api_key,
                        'model': self.app.config_manager.local_model
                    }
                else:
                    return {
                        'model_mode': 'online',
                        'api_provider': provider,
                        'thinking_mode': thinking_mode,
                        'web_search_enabled': web_search,
                        'api_endpoint': self.app.config_manager.online_api_endpoint,
                        'api_key': self.app.config_manager.online_api_key,
                        'model': self.app.config_manager.online_model
                    }
            except Exception as e:
                print(f"获取设置错误: {e}")
                return {}
        
        @eel.expose
        def get_api_presets():
            """获取API提供商预设列表"""
            try:
                return self.app.config_manager.get_api_presets()
            except Exception as e:
                print(f"获取API预设错误: {e}")
                return {}
        
        @eel.expose
        def apply_api_preset(provider):
            """应用API提供商预设"""
            try:
                success = self.app.config_manager.apply_api_preset(provider)
                if success:
                    print(f"✅ 已应用API提供商预设: {provider}")
                return success
            except Exception as e:
                print(f"应用API预设错误: {e}")
                return False
        
        @eel.expose
        def save_settings_from_web(settings):
            """保存设置"""
            try:
                # 更新配置
                if settings.get('model_mode'):
                    self.app.config_manager.model_mode = settings['model_mode']
                
                # 更新API提供商
                if settings.get('api_provider'):
                    self.app.config_manager.api_provider = settings['api_provider']
                
                # 更新思考模式
                if settings.get('thinking_mode'):
                    self.app.config_manager.thinking_mode = settings['thinking_mode']
                
                # 更新联网搜索
                if 'web_search_enabled' in settings:
                    self.app.config_manager.web_search_enabled = settings['web_search_enabled']
                
                # 根据当前模式更新对应的属性
                if settings['model_mode'] == 'local':
                    # 本地端点固定为 LM Studio 默认地址，不接受用户修改
                    if settings.get('api_key'):
                        self.app.config_manager.local_api_key = settings['api_key']
                    if settings.get('model'):
                        self.app.config_manager.local_model = settings['model']
                else:
                    # ⭐ 在线模式：端点一律使用提供商预设值，用户无需也无法填写接入地址
                    provider = settings.get('api_provider') or self.app.config_manager.api_provider
                    preset = self.app.config_manager.API_PRESETS.get(provider)
                    if preset:
                        self.app.config_manager.online_api_endpoint = preset["endpoint"]
                        # 模型：前端下拉选择优先，缺省则用预设默认模型
                        if settings.get('model'):
                            self.app.config_manager.online_model = settings['model']
                        else:
                            self.app.config_manager.online_model = preset["default_model"]
                    elif settings.get('api_endpoint'):
                        # 兜底：未知提供商时保留原值
                        pass
                    if settings.get('api_key'):
                        self.app.config_manager.online_api_key = settings['api_key']
                
                # 保存配置到文件
                self.app.config_manager.save_config()
                print(f"✅ 配置已保存: 提供商={settings.get('api_provider')}, 模型={settings.get('model')}, 思考={settings.get('thinking_mode')}, 联网={settings.get('web_search_enabled')}")
                return True
            except Exception as e:
                print(f"保存设置错误: {e}")
                return False
        
        # ===== 角色相关 =====
        @eel.expose
        def get_role_data():
            """获取角色数据"""
            try:
                conv_id = self.app.conversation_manager.current_conversation_id
                conv = self.app.conversation_manager.conversations.get(conv_id, {})
                
                # 检查是否有自定义角色设定
                custom_prompt = conv.get('custom_role_prompt')
                has_custom = custom_prompt is not None and custom_prompt.strip() != ''
                
                return {
                    # 如果没有自定义，返回空字符串（隐藏默认设定）
                    'prompt': custom_prompt if has_custom else '',
                    'isCustom': has_custom,
                    'defaultInfo': '当前使用星织默认角色设定'
                }
            except Exception as e:
                print(f"获取角色数据错误: {e}")
                return {'prompt': '', 'isCustom': False, 'defaultInfo': ''}
        
        @eel.expose
        def save_role_from_web(prompt):
            """保存角色设定"""
            try:
                # 判断是否为空（恢复默认）
                if not prompt or not prompt.strip():
                    self.app.conversation_manager.reset_to_builtin_role()
                else:
                    self.app.conversation_manager.update_role_prompt(prompt)
                return True
            except Exception as e:
                print(f"保存角色错误: {e}")
                return False
        
        @eel.expose
        def reset_role_from_web():
            """恢复默认角色"""
            try:
                self.app.conversation_manager.reset_to_builtin_role()
                return ""  # 返回空字符串表示已重置
            except Exception as e:
                print(f"重置角色错误: {e}")
                return ""
        
        # ===== 文件上传相关 =====
        @eel.expose
        def upload_file_from_web():
            """上传文件（使用tkinter文件对话框）"""
            try:
                print("📎 开始文件上传流程...")

                # tkinter 只在真正要用的时候才导入，省下启动的几百毫秒
                import tkinter as tk
                from tkinter import filedialog

                # 创建临时tk窗口
                root = tk.Tk()
                root.withdraw()  # 隐藏主窗口
                
                # Windows特定设置：确保对话框在最前面
                root.wm_attributes('-topmost', 1)
                root.focus_force()
                root.lift()
                
                print("📂 打开文件选择对话框...")
                
                file_path = filedialog.askopenfilename(
                    parent=root,
                    title="选择文件",
                    filetypes=[
                        ("文本文件", "*.txt;*.md;*.log;*.py;*.js;*.html;*.css;*.json"),
                        ("所有文件", "*.*")
                    ]
                )
                
                root.destroy()
                
                if not file_path:
                    print("⚠️ 用户取消了文件选择")
                    return {"success": False, "cancelled": True}
                
                print(f"✅ 选择了文件: {file_path}")
                file_name = os.path.basename(file_path)
                
                # 读取文件内容
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    # 尝试其他编码
                    print("⚠️ UTF-8解码失败，尝试GBK编码...")
                    with open(file_path, 'r', encoding='gbk') as f:
                        content = f.read()
                
                print(f"✅ 文件读取成功: {file_name} ({len(content)} 字符)")
                
                return {
                    'success': True,
                    'filename': file_name,
                    'content': content,
                    'char_count': len(content)
                }
            except Exception as e:
                error_msg = f"文件上传错误: {e}"
                print(f"❌ {error_msg}")
                traceback.print_exc()
                return {'success': False, 'error': str(e)}

        @eel.expose
        def upload_avatar(mood, image_data):
            """上传并保存立绘"""
            try:
                # 能够处理base64数据 (data:image/png;base64,.....)
                if ',' in image_data:
                    header, encoded = image_data.split(",", 1)
                else:
                    encoded = image_data
                
                import base64
                data = base64.b64decode(encoded)
                
                # 保存路径
                save_dir = os.path.join(get_resource_path("assets"), "avatars")
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                    
                file_path = os.path.join(save_dir, f"{mood}.png")
                
                with open(file_path, "wb") as f:
                    f.write(data)
                
                # 重新加载立绘
                self.app.reload_avatars()
                return True
            except Exception as e:
                print(f"上传立绘失败: {e}")
                return False
    
    def send_to_web(self, function_name, *args):
        """从Python调用JavaScript函数"""
        try:
            getattr(eel, function_name)(*args)
        except Exception as e:
            print(f"调用Web函数错误 {function_name}: {e}")
    
    def update_ai_response(self, content):
        """更新AI回复到Web"""
        self.send_to_web('receiveAIResponse', content)
    
    def update_avatar(self, mood):
        """更新立绘"""
        self.send_to_web('updateAvatarDisplay', mood)
    
    def update_pad_values(self, pad):
        """更新PAD情绪值"""
        self.send_to_web('updatePADValues', pad)
    
    def trigger_avatar_effect(self, content):
        """根据对话内容触发特效"""
        self.send_to_web('triggerAvatarEffect', content)
    
    def start_avatar_talking(self, duration):
        """开始说话动画"""
        self.send_to_web('startAvatarTalking', duration)
    
    def update_affection(self, value):
        """更新好感度"""
        self.send_to_web('updateAffection', value)
    
    def update_mood(self, mood):
        """更新情绪"""
        self.send_to_web('updateMood', mood)


def start_web_app(app_instance, port=0):
    """
    启动Web应用
    Args:
        app_instance: 主应用实例
        port: Web服务器端口 (0为随机端口)
    """
    # 初始化Eel
    import boot

    boot.log("开始装配本地服务")
    web_folder = get_resource_path('web')
    eel.init(
        web_folder,
        # 这里只影响“Python 是否能在前端 JS 里找 eel.expose 出来的函数”，
        # 服务静态文件不受影响。之前把 .js/.css/.json 全列上，eel 会用
        # pyparsing 把 pixi.min.js 这种几百 KB 的压缩文件整个解析一遍，
        # 白白多花 2~3 秒。本项目没有 Python 调 JS 的用法，留 .html 足够。
        allowed_extensions=['.html'],
    )
    boot.log("eel.init 完成")

    # ⭐ 动态注入版本号到 index.html
    index_path = os.path.join(web_folder, 'index.html')
    index_template_path = os.path.join(web_folder, 'index_template.html')

    # 如果存在模板文件，使用模板；否则直接修改 index.html
    source_file = index_template_path if os.path.exists(index_template_path) else index_path

    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # 替换所有 ?v=数字 为当前版本号
        html_content = re.sub(r'\?v=\d+', f'?v={APP_VERSION}', html_content)

        # 把上次用的主题直接写进 <body>：页面第一帧就是对的配色，
        # 不会先闪一下默认主题再被 JS 纠正。
        theme_name = 'glass'
        try:
            theme_name = app_instance.theme_manager.current_theme_name or 'glass'
        except Exception:
            pass
        boot_mode = 'extract' if app_paths.is_onefile() else 'fast'
        html_content = re.sub(
            r'<body data-theme="[^"]*"',
            '<body data-theme="%s" data-boot="%s"' % (theme_name, boot_mode),
            html_content, count=1)

        # 写入到 index.html（如果使用模板）或覆盖原文件
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"✅ 已注入版本号: v={APP_VERSION} 主题={theme_name}")
    except Exception as e:
        # 装到 Program Files 这类只读目录时会走到这里，页面本身有 no-cache 头，不影响使用
        print(f"⚠️ 版本号注入失败（目录可能只读）: {e}")

    live2d_path = os.path.join(web_folder, 'assets', 'live2d', 'live2d_modules-master', 'yumi', 'yumi.model3.json')
    if not os.path.exists(live2d_path):
        print(f"⚠️ Live2D 模型缺失: {live2d_path}")

    boot.log("页面注入完成")

    # 创建桥接
    bridge = WebBridge(app_instance)
    boot.log("桥接对象创建完成")

    # 将桥接实例保存到app中
    app_instance.web_bridge = bridge

    window_shell.enable_dpi_awareness()

    if not port:
        port = _pick_free_port()

    url = 'http://127.0.0.1:%d/index.html' % port
    print("🚀 启动本地服务: %s" % url)

    boot.log("桥接就绪，开始起服务")

    # eel 的服务器跑在自己的线程里（它需要独立的 gevent hub），
    # 主线程留给原生窗口，这样窗口不会带任何浏览器痕迹。
    def _serve():
        try:
            eel.start(
                'index.html',
                port=port,
                mode=None,
                block=True,
                shutdown_delay=1.0,
            )
        except Exception as exc:
            print("⚠️ eel 服务异常: %s" % exc)

    import threading
    server = threading.Thread(target=_serve, daemon=True)
    server.start()

    if not _wait_port(port, timeout=15):
        print("⚠️ 本地服务未就绪")

    if _start_native_window(app_instance, url):
        return

    # 没有 WebView2 时退回 Edge 应用窗口
    print("⚠️ 原生窗口不可用，改用 Edge 应用窗口")
    existing = [hwnd for hwnd, _ in window_shell.list_windows()]
    window_shell.launch(url, 1300, 900)
    hwnd = window_shell.adopt(existing, 1300, 900, timeout=40)

    if hwnd is None:
        print("⚠️ 没能接管应用窗口，改为用默认浏览器打开")
        close_splash("退回浏览器")
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        return

    _arm_splash_watchdog()
    time.sleep(0.6)
    close_splash("Edge 窗口已接管")

    while True:
        time.sleep(1.0)
        if not window_shell.is_alive():
            print("❌ 窗口已关闭，程序退出")
            try:
                app_instance.conversation_manager.save_conversations()
            except Exception:
                pass
            os._exit(0)


def _start_native_window(app_instance, url):
    """用 WebView2 开一个真正的原生窗口。

    页面里照常加载 eel.js，所以和 Python 的通信方式完全不用改。
    """
    try:
        import webview
    except Exception as exc:
        print("⚠️ 未安装 pywebview: %s" % exc)
        return False

    try:
        # 窗口底色跟着主题走：纸白主题下不该出现一圈深色的窗口边框
        theme_bg = {
            'glass': '#090c12',
            'clay': '#f1f4ed',
            'fresh': '#faf8f2',
            'dark': '#070708',
        }.get(getattr(getattr(app_instance, 'theme_manager', None), 'current_theme_name', ''), '#090c12')

        window = webview.create_window(
            '星织 · Hoshiori',
            url,
            width=1300,
            height=900,
            min_size=(960, 640),
            frameless=True,
            easy_drag=False,
            background_color=theme_bg,
        )
    except Exception as exc:
        print("⚠️ 创建窗口失败: %s" % exc)
        return False

    app_instance.window = window
    boot.log("窗口对象已创建，交给 WebView2")

    # 启动画面先留着，等页面真的画出第一帧（前端会回调 app_ready_from_web）
    _arm_splash_watchdog()

    def _bind_handle():
        # 必须放后台：这个回调在 GUI 线程里跑，卡住会让窗口假死甚至被关掉
        def _find():
            hwnd = window_shell.find_by_title('星织', timeout=20, sleep=time.sleep)
            if hwnd:
                boot.log("原生窗口已绑定")

        import threading
        threading.Thread(target=_find, daemon=True).start()

    window.events.shown += _bind_handle

    def _on_closed():
        try:
            app_instance.conversation_manager.save_conversations()
        except Exception:
            pass

    window.events.closed += _on_closed

    print("🪟 启动原生窗口")
    boot.log("webview.start()")
    try:
        webview.start(private_mode=False, storage_path=app_paths.webview_dir())
    except Exception as exc:
        print("⚠️ 原生窗口启动失败: %s" % exc)
        return False

    # webview.start() 在窗口关闭后返回
    try:
        app_instance.conversation_manager.save_conversations()
    except Exception:
        pass
    os._exit(0)


def _pick_free_port():
    """挑一个空闲端口，eel 的 port=0 拿不到实际值。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------- 启动画面

_SPLASH_CLOSED = False


def close_splash(reason=""):
    """撤掉 PyInstaller 的启动图。

    只在单文件版里存在（onedir 版没有这个窗口），所以整段都容错。
    一定要等页面画出第一帧之后再撤，否则中间会露出空白窗口。
    """
    global _SPLASH_CLOSED
    if _SPLASH_CLOSED:
        return False
    _SPLASH_CLOSED = True
    # 目录版没有预启动图，环境变量不存在时 pyi_splash 会抛 KeyError，先挡掉
    if not os.environ.get('_PYI_SPLASH_IPC'):
        return False
    try:
        import pyi_splash
        pyi_splash.close()
        boot.log("启动画面已撤下 %s" % reason)
    except Exception:
        return False
    return True


def _arm_splash_watchdog(timeout=25.0):
    """页面万一崩了，也别让启动图永远挂在屏幕中间。"""
    def _later():
        time.sleep(timeout)
        close_splash("超时兜底")

    threading.Thread(target=_later, daemon=True).start()



def _wait_port(port, timeout=15):
    """等服务真正开始监听。

    这里必须用 eel.sleep（gevent），普通的 time.sleep 会占住主线程，
    bottle 的 greenlet 拿不到执行机会，页面永远打不开。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), 0.4):
                return True
        except OSError:
            eel.sleep(0.15)
    return False
