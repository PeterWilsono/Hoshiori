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
import db
import window_shell
import runtime_guard
import document_reader

try:
    from version import VERSION as BUILD_VERSION   # 项目根目录唯一版本来源
except Exception:
    BUILD_VERSION = "0.0.0"


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
        def get_build_version():
            """真实的产品版本号（设置页显示用，不是缓存用的时间戳）"""
            return BUILD_VERSION
        
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
                self.app.conversation_manager._ensure_messages_loaded(conv_id)
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
                    title = _display_title(conv_data)
                    # 「对话 2 - 2026-11-08 17:30」这种是迁移时留下的占位标题，
                    # 列表和历史弹窗里全是它，很难认。用第一句话替掉。
                    if not title or re.match(r'^对话\s*\d+', title or ''):
                        try:
                            first = self.app.conversation_manager.conv_store \
                                .first_user_message(conv_id)
                        except Exception:
                            first = ""
                        if first:
                            first = re.sub(r"\s+", " ", first).strip()
                            title = first[:22] + ('…' if len(first) > 22 else '')
                    convs.append({
                        'id': str(conv_id),
                        'title': title,
                        'timestamp': _to_epoch(conv_data.get('last_interaction_time')),
                        'message_count': conv_data.get(
                            'message_count', len(conv_data.get('messages', []))),
                        'is_current': conv_id == current_id,
                        'continuity': bool(conv_data.get('continuity', 1))
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
        def new_conversation_from_web(continuity=True):
            """新建对话。

            continuity=True：延续你们的关系和记忆，只是换个话题；
            continuity=False：重新认识，关系回到陌生人，也读不到跨对话的记忆。
            """
            try:
                conv_id = self.app.new_conversation(continuity=bool(continuity))
                return {'success': True, 'conv_id': conv_id,
                        'continuity': bool(continuity)}
            except Exception as e:
                print(f"新建对话错误: {e}")
                return {'success': False, 'error': str(e)}
        
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

            # 她的生活 + 主动消息的定时器。放在语音预热之前——
            # 语音初始化偶尔会卡住音频设备，一卡就把后面全堵住了。
            try:
                self.app.start_background_services()
            except Exception as exc:
                print("⚠️ 后台服务启动失败: %s" % exc)

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
        def get_memory_stats():
            """记忆条数（设置页显示）"""
            try:
                store = self.app.conversation_manager.memory_store
                return store.stats()
            except Exception as e:
                print(f"读取记忆统计失败: {e}")
                return {"total": 0, "active": 0, "superseded": 0}

        @eel.expose
        def get_memories(limit=24, scope=None):
            """她记得的事。

            scope=None  → 这段对话能看到的全部（含跨对话的）
            scope='user'→ 只列跨对话的（"她本来就知道的"）
            scope='conv'→ 只列这段对话的
            """
            try:
                cm = self.app.conversation_manager
                # 「重新认识」的对话看不到跨对话记忆，面板也别列出来——
                # 否则界面上写着"她不记得"，下面却摆着一条条旧事。
                if scope is None and 'user' not in cm.memory_scopes():
                    scope = 'conv'
                return cm.memory_store.list_recent(
                    cm.current_conversation_id, limit=int(limit),
                    include_superseded=True, scope=scope)
            except Exception as e:
                print(f"读取记忆失败: {e}")
                return []

        @eel.expose
        def get_relationship_status():
            """心情、关系阶段、当前对话是否延续——给界面显示。"""
            try:
                cm = self.app.conversation_manager
                info = cm.mood_summary()
                core = cm.get_psych_state() or {}
                rel = core.get('relationship') or {}
                info['intimacy'] = int(rel.get('intimacy', 50))
                info['trust'] = int(rel.get('trust', 50))
                return info
            except Exception as e:
                print(f"读取关系状态失败: {e}")
                return {'label': '', 'stage': '熟悉', 'continuity': True}

        @eel.expose
        def delete_memory(mem_id):
            """手动删掉一条记忆（她会真的忘记）"""
            try:
                self.app.conversation_manager.memory_store.forget(int(mem_id))
                return True
            except Exception as e:
                print(f"删除记忆失败: {e}")
                return False

        @eel.expose
        def truncate_from(msg_id):
            """把这条消息和它之后的都删掉（编辑重发）。"""
            try:
                removed = self.app.conversation_manager.truncate_from(int(msg_id))
                return {"success": removed >= 0, "removed": removed}
            except Exception as e:
                print("截断消息失败: %s" % e)
                return {"success": False, "error": str(e)}

        @eel.expose
        def update_memory(mem_id, content):
            """改一条记忆。她记错的时候，改比删好——别把对的那半也丢了。"""
            try:
                ok = self.app.conversation_manager.memory_store.edit(
                    int(mem_id), content)
                return {"success": bool(ok)}
            except Exception as e:
                print("修改记忆失败: %s" % e)
                return {"success": False, "error": str(e)}

        @eel.expose
        def search_messages(query, limit=40):
            """全库搜聊天记录。

            跨所有对话，包括已经切走的那几段——"那次他说过什么来着"这种问题，
            没有搜索就只能一段段翻。
            """
            query = (query or "").strip()
            if len(query) < 1:
                return []

            try:
                conn = db.connect(self.app.conversation_manager.db_path)
                conn.row_factory = None
                pattern = "%" + query.replace("%", "").replace("_", "") + "%"
                rows = conn.execute(
                    "SELECT m.id, m.conv_id, m.role, m.content, m.created_at,"
                    "       c.title "
                    "FROM messages m LEFT JOIN conversations c ON c.id = m.conv_id "
                    "WHERE m.content LIKE ? "
                    "ORDER BY m.id DESC LIMIT ?",
                    (pattern, int(limit))
                ).fetchall()
                conn.close()
            except Exception as e:
                print("搜索消息失败: %s" % e)
                return []

            # 标题要用"这段对话的第一句话"，而不是库里的默认名。
            # 一次性把涉及到的对话的首句捞出来，别每条都查一遍。
            firsts = {}
            conv_ids = sorted({r[1] for r in rows if r[1] is not None})
            if conv_ids:
                try:
                    conn2 = db.connect(self.app.conversation_manager.db_path)
                    conn2.row_factory = None
                    marks = ",".join("?" * len(conv_ids))
                    for row in conn2.execute(
                        "SELECT conv_id, content FROM messages "
                        "WHERE conv_id IN (%s) AND role='user' AND id=("
                        "  SELECT MIN(id) FROM messages b "
                        "  WHERE b.conv_id = messages.conv_id AND b.role='user')"
                        % marks, conv_ids):
                        firsts[row[0]] = row[1]
                    conn2.close()
                except Exception as exc:
                    print("取对话首句失败: %s" % exc)

            out = []
            low = query.lower()
            for r in rows:
                msg_id, conv_id, role, content, created, title = r
                content = content or ""
                idx = content.lower().find(low)
                if idx < 0:
                    idx = 0
                start = max(0, idx - 30)
                snippet = content[start:start + 120].replace("\n", " ")
                if start > 0:
                    snippet = "…" + snippet
                out.append({
                    "id": msg_id,
                    "conv_id": conv_id,
                    "conv_title": _display_title({
                        "title": title,
                        "messages": [{"role": "user", "content": firsts.get(conv_id, "")}],
                    }),
                    "role": "user" if role == "user" else "ai",
                    "snippet": snippet,
                    "time": _to_epoch(created) if created else 0,
                    "clock": (created or "")[11:16] or (created or "")[:16],
                    "day": (created or "")[:10],
                })
            return out

        @eel.expose
        def get_daily_life():
            """她今天。给「她今天」面板用。"""
            try:
                return self.app.conversation_manager.life_state()
            except Exception as e:
                print("读取她的生活失败: %s" % e)
                return None

        @eel.expose
        def refresh_daily_life():
            """手动让她"过一会儿日子"（补写一段）。"""
            try:
                cfg = self.app.config_manager.get_current_api_config()
                from api_handler import APIHandler
                handler = APIHandler(
                    cfg["api_key"], cfg["api_endpoint"], cfg["model"],
                    "disabled", False, cfg.get("provider", ""))
                cm = self.app.conversation_manager
                wrote = cm.daily_life.ensure(handler, cm.get_effective_role_prompt(),
                                             cm.life_hints())
                return {"success": True, "wrote": bool(wrote),
                        "state": self.app.conversation_manager.life_state()}
            except Exception as e:
                print("补写她的生活失败: %s" % e)
                return {"success": False, "error": str(e)}

        @eel.expose
        def get_proactive_status():
            try:
                return self.app.proactive_status()
            except Exception as e:
                return {"enabled": False, "why": str(e)}

        @eel.expose
        def fire_proactive():
            """「现在让她说一句」——绕过间隔和上限，用户手动点的。"""
            try:
                return self.app.proactive_fire(force=True)
            except Exception as e:
                print("主动消息触发失败: %s" % e)
                return {"ok": False, "reason": str(e)}

        @eel.expose
        def save_proactive_settings(payload):
            """主动消息的开关与节奏。"""
            try:
                cfg = self.app.config_manager
                if "enabled" in payload:
                    cfg.proactive_enabled = bool(payload["enabled"])
                if "gap_hours" in payload:
                    cfg.proactive_gap_hours = max(0.5, float(payload["gap_hours"]))
                if "daily_cap" in payload:
                    cfg.proactive_daily_cap = max(1, min(6, int(payload["daily_cap"])))
                if "quiet" in payload:
                    cfg.proactive_quiet = str(payload["quiet"])[:20]
                if "daily_life_enabled" in payload:
                    cfg.daily_life_enabled = bool(payload["daily_life_enabled"])
                cfg.save_config()
                return {"success": True, "status": self.app.proactive_status()}
            except Exception as e:
                print("保存主动消息设置失败: %s" % e)
                return {"success": False, "error": str(e)}

        @eel.expose
        def tidy_memories():
            """把长期没用、又不重要的记忆归档（可恢复，不删除）"""
            try:
                n = self.app.conversation_manager.memory_store.prune()
                return n
            except Exception as e:
                print(f"整理记忆失败: {e}")
                return 0

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
                return bool(self.app.tts_manager.set_voice(voice_id))
            except Exception as e:
                print(f"设置TTS声音错误: {e}")
                return False

        @eel.expose
        def get_current_tts_voice():
            """获取当前TTS声音"""
            try:
                return self.app.tts_manager.voice_id
            except Exception:
                return ""

        @eel.expose
        def preview_tts_voice(voice_id=None):
            """试听：即使语音开关没开也念一句，让用户听听差别"""
            try:
                mgr = self.app.tts_manager
                if voice_id:
                    mgr.set_voice(voice_id)
                mgr.prewarm()
                was = mgr.is_enabled
                mgr.is_enabled = True
                mgr.speak('你好呀，我是星织。这个声音，你听着还习惯吗？')
                # speak() 已经在同步阶段检查过开关，这里立刻还原，
                # 免得「试听」变成顺手把语音打开了
                mgr.is_enabled = was
                return True
            except Exception as e:
                print(f"试听失败: {e}")
                return False

        @eel.expose
        def get_tts_status():
            """当前语音状态（给设置页显示用）"""
            try:
                mgr = self.app.tts_manager
                status = mgr.get_status()
                status['enabled'] = bool(self.app.voice_enabled)
                return status
            except Exception as e:
                print(f"获取语音状态错误: {e}")
                return {'enabled': False, 'voice_id': '', 'engine': '', 'engine_label': '',
                        'emotion': True, 'qwen_ok': False, 'local_ok': False, 'baidu_ok': False}

        @eel.expose
        def get_tts_catalog():
            """按引擎分组的音色清单（含「为什么不能用」的提示）"""
            try:
                mgr = self.app.tts_manager
                return {
                    'groups': mgr.get_voice_catalog(),
                    'current': mgr.voice_id,
                    'status': mgr.get_status(),
                }
            except Exception as e:
                print(f"获取语音清单错误: {e}")
                return {'groups': [], 'current': '', 'status': {}}

        @eel.expose
        def save_tts_config(payload):
            """保存语音引擎配置：Key、本地服务地址、情绪开关"""
            try:
                mgr = self.app.tts_manager
                cm = self.app.config_manager
                changed = []

                api_key = (payload.get('api_key') or '').strip()
                if api_key != (cm.tts_api_key or ''):
                    cm.tts_api_key = api_key
                    mgr._qwen.fatal = False
                    if api_key:
                        changed.append('千问')

                fish_key = payload.get('fish_key')
                if fish_key is not None:
                    cm.tts_fish_key = (fish_key or '').strip()

                local_url = payload.get('local_url')
                if local_url is not None:
                    cm.tts_local_url = (local_url or '').strip()
                    mgr._local.proto = None
                    mgr._local.checked_at = 0.0

                if payload.get('ref_audio') is not None:
                    cm.tts_ref_audio = (payload['ref_audio'] or '').strip()

                if payload.get('emotion') is not None:
                    mgr.set_emotion_enabled(bool(payload['emotion']))

                cm.save_config()

                # 刚填了千问的 Key：顺手把音色切过去，用户马上就能听到差别
                if mgr._qwen.available and mgr.engine_name in ('baidu', 'auto', 'sapi'):
                    mgr.set_voice('qwen:Serena')
                if mgr._local.base() and not mgr._local.available:
                    mgr._local.probe()

                return {'ok': True, 'changed': changed, 'status': mgr.get_status()}
            except Exception as e:
                print(f"保存语音配置失败: {e}")
                return {'ok': False, 'error': str(e)}

        @eel.expose
        def test_tts_key():
            """真的合成一句来验证 Key（不是只看长度）"""
            try:
                return self.app.tts_manager.test_qwen()
            except Exception as e:
                return {'ok': False, 'error': str(e)}

        @eel.expose
        def test_tts_local():
            """检测本地大模型语音服务"""
            try:
                return self.app.tts_manager.probe_local()
            except Exception as e:
                return {'ok': False, 'error': str(e), 'info': ''}

        @eel.expose
        def preview_tts(mode='normal'):
            """试听：mode=emotion 时用角色当前情绪念，方便对比"""
            try:
                mgr = self.app.tts_manager
                was_emotion = mgr.emotion_enabled
                if mode == 'normal':
                    mgr.emotion_enabled = False
                    sample = '你好呀，我是星织。这样平着念，是不是就有点闷？'
                else:
                    mgr.emotion_enabled = True
                    if not mgr.get_mood_tag():
                        mgr.set_mood('joy', {'pleasure': 0.8, 'arousal': 0.6, 'dominance': 0.2})
                    sample = '你好呀，我是星织！今天见到你，真的很开心呢。'

                was = mgr.is_enabled
                mgr.is_enabled = True
                mgr.speak(sample)
                mgr.is_enabled = was
                mgr.emotion_enabled = was_emotion
                return True
            except Exception as e:
                print(f"试听失败: {e}")
                return False
        
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

                def tts_fields():
                    """语音相关配置（和模型 API Key 分开存，互不干扰）"""
                    cm = self.app.config_manager
                    return {
                        'tts_api_key': getattr(cm, 'tts_api_key', ''),
                        'tts_fish_key': getattr(cm, 'tts_fish_key', ''),
                        'tts_local_url': getattr(cm, 'tts_local_url', ''),
                        'tts_emotion': bool(getattr(cm, 'tts_emotion', True)),
                        # 她会不会先开口、有没有自己的日子
                        'proactive_enabled': bool(getattr(cm, 'proactive_enabled', False)),
                        'daily_life_enabled': bool(getattr(cm, 'daily_life_enabled', True)),
                        'proactive_gap_hours': float(getattr(cm, 'proactive_gap_hours', 6) or 6),
                        'proactive_daily_cap': int(getattr(cm, 'proactive_daily_cap', 2) or 2),
                        'proactive_quiet': getattr(cm, 'proactive_quiet', '23:30-07:30'),
                    }

                if mode == "local":
                    return {
                        'model_mode': 'local',
                        'api_provider': provider,
                        'thinking_mode': 'disabled',
                        'web_search_enabled': False,
                        'api_endpoint': self.app.config_manager.local_api_endpoint,
                        'api_key': self.app.config_manager.local_api_key,
                        'model': self.app.config_manager.local_model,
                        **tts_fields(),
                    }
                else:
                    return {
                        'model_mode': 'online',
                        'api_provider': provider,
                        'thinking_mode': thinking_mode,
                        'web_search_enabled': web_search,
                        'api_endpoint': self.app.config_manager.online_api_endpoint,
                        'api_key': self.app.config_manager.online_api_key,
                        'model': self.app.config_manager.online_model,
                        **tts_fields(),
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
                    filetypes=document_reader.FILETYPES
                )
                
                root.destroy()
                
                if not file_path:
                    print("⚠️ 用户取消了文件选择")
                    return {"success": False, "cancelled": True}
                
                print(f"✅ 选择了文件: {file_path}")
                file_name = os.path.basename(file_path)

                # Word / Excel / PPT / PDF 走文档解析，纯文本走编码探测
                try:
                    doc = document_reader.read_document(file_path)
                except document_reader.DocumentError as exc:
                    print("❌ 文档读取失败: %s" % exc)
                    return {
                        'success': False,
                        'filename': file_name,
                        'error': str(exc),
                    }

                content = doc['text']
                print("✅ 文件读取成功: %s · %s · %d 字符%s" % (
                    file_name, doc['kind'], len(content),
                    "（已截断）" if doc['truncated'] else ''))

                return {
                    'success': True,
                    'filename': file_name,
                    'content': content,
                    'char_count': len(content),
                    'kind': doc['kind'],
                    'truncated': doc['truncated'],
                    'original_chars': doc['original_chars'],
                    'warning': doc['warning'],
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
        """从 Python 调用前端函数。

        不能直接用 getattr(eel, name)：页面连上之前那个属性是 mock，
        只把调用塞进队列、根本不发 websocket。所以统一走 _js_call。
        """
        try:
            if not getattr(eel, '_websockets', None):
                return          # 页面还没连上，静默跳过
            eel._js_call(function_name, list(args))
        except Exception as e:
            print(f"调用Web函数错误 {function_name}: {e}")
    
    def update_ai_response(self, content):
        """更新AI回复到Web"""
        self.send_to_web('receiveAIResponse', content)

    def push_proactive(self, content):
        """她会先开口：这条不是回你，是她自己找上来的。"""
        self.send_to_web('pushProactive', content)

    def append_ai_response(self, extra):
        """把一小段补充（比如结尾的 emoji）接到上一条气泡后面"""
        if not extra:
            return
        self.send_to_web('appendAIResponse', extra)
    
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

    def stop_avatar_talking(self):
        """停止说话动画（一句念完就闭嘴）"""
        self.send_to_web('stopAvatarTalking')
    
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
        # 这里只影响“Python 能否在前端 JS 里找到 eel.expose 出来的函数”，
        # 服务静态文件不受影响。之前把 .js/.css/.json 全列上，eel 会用
        # pyparsing 把 pixi.min.js 这种几百 KB 的压缩文件整个解析一遍，
        # 白白多花 2~3 秒，所以只留 .html。
        # 代价是前端写在 js/ 里的回调不会被自动发现——下面手动登记一份。
        allowed_extensions=['.html'],
    )
    _register_js_callbacks()
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

    # 先把上次崩溃/被强杀留下的窗口进程收了。放线程里是因为真要查命令行
    # 得 1.3 秒，站在这儿等会拖慢冷启动；这时候自己的 WebView2 还没起，
    # 也不会误伤自己。
    _sweep_stale_async()

    if _start_native_window(app_instance, url):
        return

    # 没有 WebView2 时退回 Edge 应用窗口
    print("⚠️ 原生窗口不可用，改用 Edge 应用窗口")
    existing = [hwnd for hwnd, _ in window_shell.list_windows()]
    browser_proc = window_shell.launch(url, 1300, 900)
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
            # 浏览器进程要显式收掉：只关窗口的话，Edge 有时会留在后台
            try:
                if browser_proc is not None:
                    browser_proc.terminate()
            except Exception:
                pass
            try:
                runtime_guard.kill_children()
            except Exception:
                pass
            os._exit(0)


def _sweep_stale_async():
    """后台清掉上次崩溃/被强杀留下的 WebView2。

    单独开线程：判断孤儿要先看进程快照（12ms），但确认是不是我们的
    得读命令行（1.3 秒）。这个时间不该算进冷启动。
    """
    def work():
        try:
            runtime_guard.sweep_stale(app_paths.webview_dir())
        except Exception as exc:
            print("⚠️ 清理残留窗口进程失败: %s" % exc)

    try:
        import threading
        threading.Thread(target=work, daemon=True).start()
    except Exception:
        pass


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

    # 收尾：pywebview 偶尔会留下 WebView2 的子进程，留着会占内存、
    # 还会一直握着数据目录和页面文件的句柄。
    try:
        runtime_guard.kill_children()
    except Exception:
        pass
    os._exit(0)


def _pick_free_port():
    """挑一个空闲端口，eel 的 port=0 拿不到实际值。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------- 前端回调

#: 前端用 eel.expose 暴露给 Python 调用的函数（web/js/*.js）。
#: eel.init 只解析 .html，所以这张表要跟着前端一起维护。
JS_CALLBACKS = (
    'updateAvatarDisplay',
    'updateMood',
    'updateAffection',
    'updatePADValues',
    'triggerAvatarEffect',
    'startAvatarTalking',
    'stopAvatarTalking',
    'receiveAIResponse',
    'appendAIResponse',
    'pushProactive',
    'lifeUpdated',
    'applyThemeFromPython',
)


def _register_js_callbacks():
    """把前端回调补进 eel 的名单。

    eel.init 只解析 .html，js/ 里 eel.expose 出来的函数它看不到。
    这一步把它们塞回 _js_functions：页面连上时 eel 会给这些函数装上真正的
    发送实现（_import_js_function），而不是 init 时那个只入队不发送的 mock。
    """
    try:
        merged = list(dict.fromkeys(list(getattr(eel, '_js_functions', []) or []) + list(JS_CALLBACKS)))
        eel._js_functions = merged
    except Exception as exc:
        print("⚠️ 注册前端回调失败: %s" % exc)


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
