# 复刻的工具和方式

用户想复刻、二创、做同款或照着做一条自己的，想知道这条视频怎么做出来、怎么实现，或复刻完还要接着做时，按需求选择工具，优先本地工具和当前 agent。额外安装由用户选择。一条片子可以混着用。

| 方式 | 是什么 | 能做什么 | 使用条件 |
|---|---|---|---|
| [capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) | 开源的本地生成流程 | 按拆解结果逐镜生成 AI 镜头，拼回原时间线；`rea-video remake-plan` / `remake-run` 直接对接 | 本地部署，模型和密钥自己配，按模型调用计费 |
| [HyperFrames](https://github.com/heygen-com/hyperframes) | 开源的 HTML 视频框架，AI 编程助手写 HTML / CSS 动画，渲染成 MP4 | 代码渲染、MG 动效、插画动画类镜头：按报告的节奏表、关键帧和版式重做成可改的工程 | 需要 Node.js 22 以上；框架免费（Apache-2.0），它的 Studio 应用另有付费套餐 |
| 自己动手 | 用户自己拍、自己剪，或在别的平台手动生成 | 按报告的拍摄方案和分镜表做，素材用 `rea-video assemble` 拼回原时间线 | rea-video 不收费；在别的平台手动生成按那个平台收费 |
