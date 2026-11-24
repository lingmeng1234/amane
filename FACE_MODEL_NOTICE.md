# 人脸定位裁剪模型说明

人脸定位裁剪使用两个随 Amane 源码分发的 ONNX 模型：

- `src/amane/media/face_detect_scrfd.onnx`：SCRFD 人脸检测模型。
- `src/amane/media/face_detect_genderage.onnx`：性别年龄属性模型。

模型文件必须由发布维护者直接提交到上述源码目录。开发、运行、Docker、wheel/sdist 及 Windows/macOS 桌面端构建均直接读取源码中的模型，不会从网络下载模型，也不会建立模型下载缓存。缺少任一模型时，人脸定位会按现有逻辑回退到居中裁剪；发布前必须确认两个模型均已上传且文件有效。

模型会话仍采用惰性加载：不触发人脸定位时不会创建 ONNX 推理会话。SCRFD 先执行人脸检测；只有检测到人脸后才加载性别年龄模型。

模型权重来源于 InsightFace 预训练模型。InsightFace 对预训练模型的使用限制为非商业研究用途；商业使用前请自行向权利方取得适当授权。将模型纳入源码或发行包不代表 Amane 获得了额外授权，使用者仍须遵守模型原始许可及适用法律。

参考项目：
- https://github.com/deepinsight/insightface
