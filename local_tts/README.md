# 本地语音组件（可选）

不想用云端语音、也不想按字数付费的时候，可以把模型跑在自己显卡上。
主程序本体不会因此变大 —— 这套东西装在独立的虚拟环境里，用 HTTP 跟主程序说话。

## 一、最快的一条路：Qwen3-TTS

要求：NVIDIA 显卡（6GB 显存起）、Windows 10/11、约 8GB 硬盘。

```bash
# 在项目根目录执行
python local_tts/install_local_tts.py           # 0.6B，约 3.5GB，速度快
python local_tts/install_local_tts.py --size 1.7b   # 1.7B，音质更好
```

脚本会做四件事：建虚拟环境 → 装 CUDA 版 torch → 装 `qwen-tts` → 从魔搭下模型，
最后生成 `start_tts.bat`。

以后每次要用语音，双击 `local_tts/start_tts.bat`（第一次加载模型约 20~60 秒），
看到 `🚀 本地语音服务: http://127.0.0.1:9880` 就好了。

然后到软件里：**设置 → 语音 → 下拉框里选「本地大模型」**，
本地语音服务填 `http://127.0.0.1:9880`，点「检测」。连上之后声音就不限量、也不花钱了。

## 二、已经装了别的模型？直接接

主程序的「本地大模型」引擎会自动识别下面三种协议，只要服务在本机跑起来：
填地址 → 点检测 → 能用。

| 服务 | 默认端口 | 起服务的方式 |
| --- | --- | --- |
| **Breeze TTS 2** | 7860 | `python -m breeze_infer.api <模型目录> --host 127.0.0.1 --port 7860` |
| **IndexTTS2**（Docker） | 8002 | `docker run -p 8002:8002 --gpus all neosun/indextts2:v2.1-cuda` |
| **GPT-SoVITS** | 9880 | `python api_v2.py -a 127.0.0.1 -p 9880` |

几点实话：

- **Breeze TTS 2** 最低 12GB 显存（默认 eager 模式约 7.7GB），官方只支持 Linux，
  权重是非商用许可。8GB 显卡的 Windows 机器装不了，别硬试。
- **IndexTTS2** 权重十几 GB，4060 上一句要 8~10 秒。它适合做配音、有声书，
  不适合「你一句我一句」的实时聊天 —— 真想用它，建议先把回复攒成段落再合成。
- **GPT-SoVITS** 适合「我只想听某个特定音色」，克隆 5 秒素材就够。

## 三、协议细节（想自己写服务的话）

主程序按顺序探测，命中哪个用哪个：

1. `GET /v1/models` 通 → 用 OpenAI 兼容协议
   `POST /v1/audio/speech`，body `{"input": "文本", "voice": "...", "response_format": "wav"}`
2. `GET /health` 或 `GET /docs` 通 → 按 IndexTTS 协议
   `POST /tts`，body `{"text": "文本", "spk_audio_prompt": "参考音频路径"}`
3. 返回值可以是裸音频字节，也可以是 `{"url": "..."}` 或 `{"data": "<base64>"}`，三种都认

文本开头可能带情感标签，例如 `[sad] 今天有点累`。
自己写服务时把标签转成模型自己的情绪参数效果最好；
不想要标签也行，主程序在引擎返回 400 时会自动去掉标签重试一次。
