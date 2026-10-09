# 🌟 星织 AI - Hoshiori AI Companion

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)

**一个温暖、智能的AI陪伴助手，拥有情感记忆和Live2D立绘**

[功能特性](#功能特性) • [快速开始](#快速开始) • [配置说明](#配置说明) • [技术架构](#技术架构) • [贡献指南](#贡献指南)

</div>

---

## 📖 项目简介

**星织（Hoshiori）** 是一个开源的AI陪伴助手，她不仅仅是一个聊天机器人，更是一个有情感、有记忆、能共情的虚拟伙伴。

星织拥有银色的长发和蓝色的大眼睛，穿着校园制服，通过Live2D技术呈现生动的表情和动作。她能够记住你们的对话，理解你的情绪，并在交互中不断成长。

### 为什么选择星织？

- 💝 **情感陪伴**：不是冷冰冰的问答机器，而是有温度的伙伴
- 🧠 **智能记忆**：记住重要信息，越聊越懂你
- 🎭 **情绪共鸣**：根据对话内容实时调整情绪状态
- 🎨 **视觉呈现**：Live2D立绘让交互更生动
- 🔒 **隐私保护**：支持本地部署，数据完全掌握在自己手中
- 🚀 **灵活配置**：支持多种AI模型，可在线可本地

---

## ✨ 功能特性

### 🎯 核心功能

#### 1. 智能对话系统
- 支持多种AI模型（DeepSeek、小米MiMo、本地模型等）
- 深度思考模式，提供更专业的回答
- 联网搜索功能，获取实时信息

#### 2. 情感系统
- **PAD情绪模型**：愉悦度(Pleasure)、激活度(Arousal)、支配度(Dominance)
- **性格特征**：开放性、尽责性、外向性、宜人性、神经质
- **关系系统**：信任度、亲密度、压力值的动态变化

#### 3. 记忆系统
- **长期记忆**：自动提取并保存重要信息
- **用户画像**：记录姓名、生日、职业等基本信息
- **偏好记忆**：记住你喜欢和讨厌的事物
- **事件记忆**：记录重要的共同回忆

#### 4. 视觉系统
- Live2D立绘显示
- 3个可选角色：Murasame_Yukata、nahida、yumi
- 根据对话内容自动调整表情

#### 5. 语音系统（可选）
- Edge-TTS文字转语音
- 多种语音可选
- 情绪驱动的语音表达

### 🎨 界面特性

- 现代化UI设计
- 多主题支持（浅色/深色）
- 流畅的动画效果
- 响应式布局

---

## 🚀 快速开始

### 前置要求

- Python 3.8 或更高版本
- Windows 操作系统（推荐 Windows 10/11）
- 网络连接（如使用在线API）

### 安装步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/hoshiori-ai.git
cd hoshiori-ai
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 配置API密钥

**方法一：使用示例配置文件（推荐）**

```bash
# 复制示例配置文件
copy config.py.example config.py

# 编辑 config.py，将 YOUR_API_KEY_HERE 替换为你的API密钥
```

**方法二：在程序中配置**

首次运行程序时，点击"设置"按钮，输入你的API密钥即可。

#### 4. 运行程序

```bash
python main.py
```

### 获取API密钥

星织支持多种AI提供商，你可以选择以下任一方式：

#### 在线API（推荐新手）

1. **DeepSeek API**
   - 访问：https://platform.deepseek.com/
   - 注册账号并获取API密钥
   - 支持深度思考模式

2. **小米 MiMo API**
   - 访问：https://mimo.xiaomimimo.com/
   - 注册账号并获取API密钥
   - 多种模型可选

#### 本地模型（隐私保护）

1. 下载并安装 [LM Studio](https://lmstudio.ai/)
2. 在 LM Studio 中下载模型（推荐 Qwen2.5-7B-Instruct-GGUF）
3. 启动本地服务器（默认端口 1234）
4. 在星织中切换到"本地模式"

---

## ⚙️ 配置说明

### 基本配置

配置文件位于 `baocun/config.json`，主要配置项：

```json
{
  "model_mode": "online",           // 模式: "online" 或 "local"
  "api_provider": "mimo",           // 提供商: "deepseek", "mimo", "custom"
  "thinking_mode": "disabled",      // 思考模式: "enabled" 或 "disabled"
  "web_search_enabled": false,      // 联网搜索: true 或 false
  "online_api_key": "YOUR_API_KEY", // 在线API密钥
  "show_avatar": true               // 显示立绘: true 或 false
}
```

### 高级配置

#### 切换AI提供商

在程序界面点击"设置"按钮，选择不同的API提供商：
- DeepSeek：支持深度思考，适合复杂推理
- 小米MiMo：多种模型，性价比高
- 自定义：支持任何兼容OpenAI格式的API

#### 启用深度思考模式

深度思考模式会让AI进行更深入的推理，适合复杂问题：
1. 打开设置
2. 选择"开启深度思考"
3. 注意：会增加Token消耗和响应时间

#### 启用联网搜索

让星织能够搜索互联网获取最新信息：
1. 打开设置
2. 启用"联网搜索"
3. 目前仅支持部分模型

### 本地模型配置

#### LM Studio 设置

1. **下载模型**
   - 推荐模型：Qwen2.5-7B-Instruct-GGUF
   - 量化版本：Q4_K_M（4.3GB）或 Q5_K_M（5.2GB）

2. **加载模型**
   - GPU Offload：拉满（Max）
   - Context Length：8192 tokens
   - Temperature：无需设置（代码中已优化）

3. **启动服务器**
   - 切换到"Local Server"标签
   - 点击"Start Server"
   - 确认端口为 1234

#### 性能建议

| 配置 | 推荐模型 | 显存占用 | 性能 |
|------|----------|----------|------|
| 8GB 显存 | Q4_K_M | ~5GB | 优秀 |
| 12GB+ 显存 | Q5_K_M | ~6GB | 极佳 |
| 无显卡 | 不推荐本地模型 | - | - |

---

## 🏗️ 技术架构

### 项目结构

```
hoshiori-ai/
├── main.py                    # 主程序入口
├── config.py                  # 配置管理
├── api_handler.py             # API请求处理
├── conversation_manager.py    # 对话管理
├── memory_manager.py          # 记忆系统
├── emotion_analyzer.py        # 情绪分析
├── theme_system.py            # 主题系统
├── tts_manager.py             # 语音管理
├── web_bridge.py              # Live2D桥接
├── assets/                    # 资源文件
│   ├── avatars/              # 头像
│   ├── icons/                # 图标
│   └── live2d/               # Live2D模型
├── web/                      # Web界面资源
├── baocun/                   # 数据存储目录
│   ├── config.json          # 用户配置
│   ├── conversations.json   # 对话记录
│   └── theme_config.json    # 主题配置
├── requirements.txt          # Python依赖
└── README.md                 # 说明文档
```

### 核心模块

#### 1. 配置管理 (config.py)
- 支持本地/在线模型切换
- 多API提供商预设
- 配置持久化存储

#### 2. API处理器 (api_handler.py)
- OpenAI格式API兼容
- 支持流式输出
- 自动重试机制
- 深度思考模式支持
- 联网搜索功能

#### 3. 对话管理 (conversation_manager.py)
- 多会话管理
- 上下文压缩
- 长期记忆存储

#### 4. 记忆系统 (memory_manager.py)
- 自动记忆提取
- 智能摘要生成
- 向量化存储（可选）

#### 5. 情绪系统 (emotion_analyzer.py)
- PAD情绪模型
- 性格特征建模
- 情绪状态可视化

#### 6. 主题系统 (theme_system.py)
- 多主题支持
- 自定义主题配置
- 流畅的主题切换

---

## 🎯 使用指南

### 首次使用

1. **启动程序**
   ```bash
   python main.py
   ```

2. **配置API**
   - 点击右上角"设置"按钮
   - 选择API提供商
   - 输入API密钥
   - 点击"保存并关闭"

3. **开始对话**
   - 在底部输入框输入消息
   - 按Enter或点击发送按钮
   - 享受与星织的对话！

### 高级功能

#### 模型切换
- 点击顶部的"🏠 本地"或"☁️ 在线"按钮
- 一键切换本地/在线模式

#### 记忆管理
- 星织会自动记住你说过的重要信息
- 可以问"你还记得我叫什么吗？"来测试记忆

#### 情绪互动
- 星织会根据对话内容调整情绪
- 你可以尝试安慰、夸奖、调侃她
- 观察她的情绪变化和反应

---

## 🛠️ 开发指南

### 环境搭建

```bash
# 克隆仓库
git clone https://github.com/yourusername/hoshiori-ai.git
cd hoshiori-ai

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate  # Windows

# 安装开发依赖
pip install -r requirements.txt
```

### 代码规范

- 遵循 PEP 8 编码规范
- 使用有意义的变量名
- 添加必要的注释
- 编写单元测试

### 提交代码

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📝 更新日志

### v1.2.0
- ✨ 新增多API提供商支持（DeepSeek、小米MiMo）
- ✨ 新增深度思考模式
- ✨ 新增联网搜索功能
- 🎨 优化Live2D立绘显示
- 🐛 修复对话顺序问题
- 🐛 修复缓存问题
- 📝 重构配置系统

### v1.1.0
- ✨ 新增本地模型支持（LM Studio）
- ✨ 新增智能记忆系统
- 🎨 优化UI界面
- 🐛 修复多个已知问题

### v1.0.0
- 🎉 初始版本发布
- ✨ 基础对话功能
- ✨ Live2D立绘
- ✨ 情绪系统

---

## 🤝 贡献指南

欢迎所有形式的贡献！

### 如何贡献

1. **报告Bug** - 提交Issue描述问题
2. **建议功能** - 提交Issue描述你的想法
3. **提交代码** - Fork仓库并提交Pull Request
4. **完善文档** - 帮助改进README和代码注释

### 行为准则

- 尊重所有贡献者
- 保持友善和建设性的讨论
- 接受建设性批评

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

### 使用的开源项目

- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) - 现代化的Tkinter UI库
- [Pillow](https://python-pillow.org/) - Python图像处理库
- [Live2D](https://www.live2d.com/) - 2D模型动画技术
- [Edge-TTS](https://github.com/rany2/edge-tts) - 微软Edge文字转语音

### 灵感来源

感谢所有AI陪伴项目为这个领域带来的创新和启发。

---

## 📮 联系方式

- 提交Issue: [GitHub Issues](https://github.com/yourusername/hoshiori-ai/issues)
- 功能建议: [GitHub Discussions](https://github.com/yourusername/hoshiori-ai/discussions)

---

<div align="center">

**如果这个项目对你有帮助，请给一个 ⭐️ Star！**

Made with ❤️ by Hoshiori AI Team

</div>
