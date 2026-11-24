# 人脸定位裁剪模型说明

人脸定位裁剪使用以下 ONNX 模型：

- SCRFD 人脸检测模型：InsightFace buffalo_l 模型包中的 det_10g。
- 性别年龄模型：InsightFace GenderAge 属性模型。

SCRFD 先执行人脸检测；只有检测到至少一张人脸后，才会按需加载性别年龄模型。未检测到人脸时直接居中裁剪，不额外下载性别年龄模型。

模型文件不会作为大型二进制文件提交到 Git。开发环境通过 `just setup` 的 `face-models` 步骤下载；Docker、wheel/sdist 与 Windows/macOS 桌面包的构建流程也会先获取模型并将其纳入发行产物。模型下载来源固定到参考实现仓库的提交 `657b70dc36047a875eb1431dca342abc7a07a346`，并在写入前校验文件大小及 Git blob SHA-1。

运行时优先使用随包模型；若发行环境缺少模型文件，则在首次需要人脸定位时下载到本地缓存。默认缓存目录为 `~/.cache/amane/models`；可通过 `AMANE_MODEL_DIR` 环境变量覆盖。模型会话仍采用惰性加载和缓存复用，不启用人脸模式时不会创建 ONNX 推理会话。

模型权重来源于 InsightFace 预训练模型。InsightFace 对预训练模型的使用限制为非商业研究用途；商业使用前请自行向权利方取得适当授权。模型仅在本地执行推理，不上传封面图片。首次下载需要网络连接；下载失败或模型不可用时，人脸定位模式会回退到居中裁剪。

参考实现与模型镜像：
- https://github.com/BiancaVeritas/amane-promax/tree/657b70dc36047a875eb1431dca342abc7a07a346/src/amane/media
- https://github.com/deepinsight/insightface

