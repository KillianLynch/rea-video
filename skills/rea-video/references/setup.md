# Fork setup and agent review

This fork uses your current image-capable agent for visual review. English is the
default CLI and report language; use `--lang zh` for a Chinese report. External VLM
API calls are disabled. API keys and old `vlm=on` preferences cannot enable them.
ONNX Runtime's 1DS telemetry is disabled before package initialization reaches
any OCR or inference imports. Run the CLI in a fresh process.

## Install when requested

Requirements: Python 3.10+ and FFmpeg, including `ffprobe`.
From this fork's checkout, run:

```bash
bash scripts/install_skill.sh --agent codex
source .venv/bin/activate
rea-video --help
```

The installer modifies only this checkout's `.venv` and the selected agent's
skill link. Omit `--agent codex` to install the CLI without registering a skill.
Use `--agent claude` or `--agent agents` for a different agent. Existing skill
links pointing elsewhere are preserved. No global command link is created.

On Python up to 3.12, OCR pulls in two OpenCV packages. The installer removes the
GUI package and reinstalls headless OpenCV only inside this checkout's `.venv`.
To select Python explicitly, prefix the installer command with
`PYTHON_BIN=python3.12`.

## Optional local speech recognition

After installation, add speech recognition inside the same environment:

```bash
.venv/bin/python -m pip install -e ".[ocr,asr]"
```

装了之后 `decompose` 会自动在分离出的人声干声上识别（SenseVoice，中 / 英 / 日 / 韩 / 粤；首次使用下载约 160 MB 模型到 `$REA_VIDEO_MODELS`，默认 `~/.cache/rea-video/models`），
一分钟的片子几秒钟。结果在 `breakdown.json` 的 `speech.lines`（每句有起止时间），报告「脚本」表和 `review_tasks.json` 每镜的 `said` 会用它。`--no-asr` 可跳过。
台词是孟加拉语时加 `--asr-lang bn`（或 `rea-video prefs asr_lang bn` 设成默认）：SenseVoice 不认孟加拉语，会把它听成英 / 日 / 韩文的乱码；
`bn` 换用孟加拉语的流式识别模型（另下约 90 MB），`speech.language` 是 `bn`，识别出的句子不带标点。
同一个可选包还会分出说话人（另下约 35 MB 模型）：多人对话时台词带上是谁说的，并给每人输出一条音轨，见 `audio.md`。

这是机器听写，会有同音错字、专有名词听错：画面上有字幕时以字幕为准，VLM 给了台词时报告用 VLM 的；引用台词给用户时注明"语音识别，未校对"。
长句里逐句的时间是按字数估的（`timing: estimated`），整段的起止是测出来的。没装时 `speech.reason` 是 `not_installed`，其余照常。

## Visual review with your agent

Use `rea-video survey` and answer its image tasks until it reports completion.
Run `rea-video decompose`, then `rea-video review`. Inspect the frames, fill in
`review_answers.json`, and run `rea-video apply-review`.

If the agent cannot inspect images, report the resulting uncertainty. A separate
model API is not required or supported in this fork. First-use model downloads
still require network access. See [fork privacy](../../../docs/privacy.md).
