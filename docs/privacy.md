# Fork setup and privacy

This personal fork keeps the local analysis tools and the current agent's visual
review workflow. It removes the sponsored editor promotion and its installer
instructions. Upstream examples and translated documentation can describe features
that are disabled here; this page and the skill's setup guide describe this fork.

## Changes

- ONNX Runtime's 1DS telemetry is disabled with `ORT_DISABLE_TELEMETRY=1` before
  importing inference or OCR dependencies. The package overrides an inherited `0`.
  The installer also sets the variable before invoking Python. Use a fresh CLI
  process; importing this package cannot undo telemetry from an ONNX Runtime
  instance that another application has already initialized.
- The external VLM upload client is removed. `--vlm` is rejected, old saved VLM
  preferences are ignored, and VLM API environment variables are ignored. Direct
  Python callers requesting `decompose(..., use_vlm=True)` receive an error before
  the video is processed. Review prompts and normalization remain available.
- The installer uses only the checkout's `.venv`. It registers a skill only when
  you select one agent and preserves an existing registration pointing elsewhere.
- Current Codex or Claude Code image review remains enabled. Images the agent
  opens are handled by that agent's configured model service.

## Install

Requirements: Python 3.10+ and FFmpeg with `ffprobe`. From the fork's checkout, run:

```bash
bash scripts/install_skill.sh --agent codex
source .venv/bin/activate
rea-video --help
```

Omit `--agent codex` to leave agent registrations unchanged. Other supported
targets are `--agent claude` and `--agent agents`. The installer creates no global
command link and does not edit shell startup files.

## Analyse a video

Run `rea-video survey input.mp4 -o out/input` and let the current agent answer its
image tasks until the survey is complete. Then run:

```bash
rea-video decompose input.mp4 -o out/input --lang en
rea-video review out/input
```

After the agent fills in `out/input/review_answers.json`, merge its answers:

```bash
rea-video apply-review out/input --by Codex
```

The agent handles visual interpretation. Without an external video/audio model,
some motion or sound judgments remain uncertain. Local OCR, audio analysis, and
optional speech recognition are retained.

## Network and storage

Installation still contacts GitHub and Python package hosts. First use downloads
models from GitHub and, for Japanese or Korean OCR, ModelScope. Model hosts can
observe normal download metadata, including the source IP address. Audio
separation downloads approximately 216 MB of models; face detection and optional
language or speech features download additional models. Dependency versions are
not locked, so review resolved packages before installation.

Models are cached in `~/.cache/rea-video/models` by default. Preferences and
corrections live in `~/.rea-video`, and extracted media and reports live in the
selected output directory. These files can contain sensitive content.

A Python virtual environment isolates packages, not file or network permissions.
The telemetry setting is not a firewall or a telemetry-free dependency build.
Optional generation integrations can call external services when deliberately
invoked; they are separate from analysis. No packet-capture verification is
claimed. Recheck these protections when incorporating upstream changes.

## Verify changes without installation

Run the regression checks with Python's standard library:

```bash
python3 -m unittest discover -s tests -v
```

The CLI and pipeline checks use analysis dependencies already available in the
test environment. They do not install the application or download models.
