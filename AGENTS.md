# rea-video：给 Agent 的说明

- 本分支的安装与隐私设置以 `skills/rea-video/references/setup.md` 为准。需要安装时使用仓库内 `.venv`，只向用户选择的 agent 注册 skill。外部 VLM API 已禁用，使用当前 agent 看图复核。
- 用户要拆解视频、判断制作方式、标真实素材、拆音乐音效、复刻时，**先读 `skills/rea-video/SKILL.md`**，按里面的流程做，并复核低置信镜头。
- 仓库分工：
  - `skills/rea-video/`：给 agent 用的 skill（流程 + references），只写怎么用，不放开发文档
  - `rea_video/`：CLI 和拆解逻辑；模型能力地图在 `rea_video/capabilities/`，capsule-cinema 对接脚本在 `rea_video/integrations/`
  - `docs/`：给人看的文档；`docs/dev/` 是开发文档（扩充评测集、加拍法维度）
  - `eval/`：评测集；`tests/`：可提交的回归测试
- 开发约定：
  - 开发环境：`pip install -e ".[ocr,dev]"`（dev 带 pytest 和 jsonschema，测试和能力地图校验要用）
  - 规则改动后跑 `python3 -m pytest -q` 和 `rea-video eval eval/labels.yaml` / `eval/holdout*.yaml`，结果更新到 `eval/RESULTS.md`
  - 能力地图改完跑 `python3 scripts/validate_capabilities.py --matrix`
- 不要提交任何密钥；外部 VLM 凭据在本分支不起作用。回归测试：`python3 -m unittest discover -s tests -v`。
