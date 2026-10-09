# -*- coding: utf-8 -*-
"""
Web Bridge - Eel集成层
连接Python后端和Web前端的桥接层
"""
import eel
import sys
import os
import base64
from tkinter import filedialog
import tkinter as tk
import re
import traceback
import time
import hashlib


# ⭐ 全局版本号 - 使用时间戳确保每次启动都是新版本
APP_VERSION = str(int(time.time()))


def get_resource_path(relative_path):
    """获取资源文件路径（支持打包后）"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller打包后
        return os.path.join(sys._MEIPASS, relative_path)
    # 开发环境
    return os.path.join(os.path.abspath("."), relative_path)


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
                    'messages': messages,
                    'timestamp': conv.get('timestamp', 0)
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
                    # 获取对话标题（第一条AI消息的前20字）
                    title = "新对话"
                    for msg in conv_data.get('messages', []):
                        if msg['role'] == '你' and msg['content']:
                            title = msg['content'][:20] + ('...' if len(msg['content']) > 20 else '')
                            break
                    
                    convs.append({
                        'id': str(conv_id),
                        'title': conv_data.get('title', title),
                        'timestamp': conv_data.get('last_interaction_time', 0),
                        'message_count': len(conv_data.get('messages', [])),
                        'is_current': conv_id == current_id
                    })
                
                # 按时间倒序排序
                convs.sort(key=lambda x: x['timestamp'], reverse=True)
                return convs
            except Exception as e:
                print(f"获取对话列表错误: {e}")
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
            """删除对话"""
            try:
                # 转换为整数
                conv_id = int(conv_id)
                self.app.conversation_manager.delete_conversation(conv_id)
                return True
            except Exception as e:
                print(f"删除对话错误: {e}")
                return False
        
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
                    if settings.get('api_endpoint'):
                        self.app.config_manager.local_api_endpoint = settings['api_endpoint']
                    if settings.get('api_key'):
                        self.app.config_manager.local_api_key = settings['api_key']
                    if settings.get('model'):
                        self.app.config_manager.local_model = settings['model']
                else:
                    if settings.get('api_endpoint'):
                        self.app.config_manager.online_api_endpoint = settings['api_endpoint']
                    if settings.get('api_key'):
                        self.app.config_manager.online_api_key = settings['api_key']
                    if settings.get('model'):
                        self.app.config_manager.online_model = settings['model']
                
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
    web_folder = get_resource_path('web')
    eel.init(web_folder, allowed_extensions=['.js', '.html', '.css', '.json', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.moc3', '.moc', '.vtube'])
    
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
        
        # 写入到 index.html（如果使用模板）或覆盖原文件
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ 已注入版本号: v={APP_VERSION}")
    except Exception as e:
        print(f"⚠️ 版本号注入失败: {e}")
    
    # 调试：检查Live2D模型文件是否存在
    live2d_path = os.path.join(web_folder, 'assets', 'live2d', 'live2d_modules-master', 'yumi', 'yumi.model3.json')
    print(f"📁 Web目录: {web_folder}")
    print(f"🎭 Live2D模型路径: {live2d_path}")
    print(f"🎭 模型文件存在: {os.path.exists(live2d_path)}")
    
    # 列出assets目录内容
    assets_path = os.path.join(web_folder, 'assets')
    if os.path.exists(assets_path):
        print(f"📂 assets目录内容: {os.listdir(assets_path)}")
        live2d_assets = os.path.join(assets_path, 'live2d', 'live2d_modules-master')
        if os.path.exists(live2d_assets):
            print(f"📂 live2d模型目录内容: {os.listdir(live2d_assets)}")
    else:
        print(f"⚠️ assets目录不存在: {assets_path}")
    
    # 创建桥接
    bridge = WebBridge(app_instance)
    
    # 将桥接实例保存到app中
    app_instance.web_bridge = bridge
    
    print(f"🚀 启动Web服务器...")
    
    def on_close(page, sockets):
        print("❌ 窗口关闭，正在退出程序...")
        sys.exit(0)
    
    # 启动Eel应用
    # 尝试强制使用应用模式 (无地址栏)
    try:
        # 首选 Edge (通常Windows都有), 其次 Chrome
        eel.start(
            'index.html',
            size=(1300, 900),
            port=port,
            mode='edge',         # 尝试强制 Edge 应用模式
            close_callback=on_close,
            cmdline_args=['--kiosk', '--disable-http-cache', '--disable-cache'] # ⭐ 禁用浏览器缓存
        )
    except Exception as e:
        print(f"⚠️ Edge启动失败，尝试默认模式: {e}")
        try:
            eel.start(
                'index.html',
                size=(1300, 900),
                port=port,
                mode='chrome', # 尝试 Chrome
                close_callback=on_close,
                cmdline_args=['--disable-http-cache', '--disable-cache'] # ⭐ 禁用浏览器缓存
            )
        except Exception as ex:
             print(f"⚠️ Chrome启动失败，使用系统默认浏览器: {ex}")
             eel.start(
                'index.html',
                size=(1300, 900),
                port=port,
                mode='default',
                close_callback=on_close
            )

