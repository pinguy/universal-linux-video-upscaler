# Third-party software and models

This repository does not vendor FFmpeg, PyTorch, Real-ESRGAN, NCNN binaries or
model weights. It discovers optional external installations and runs them as
separate processes.

Licences were checked against the upstream projects on 1 November 2026 before
selecting the MIT licence for this repository.

| Component | Use | Upstream licence |
|---|---|---|
| [FFmpeg](https://ffmpeg.org/) | Required external probe, scaling and encoder | LGPL 2.1+ by default; individual builds may enable GPL components such as x264 |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | Optional neural algorithms, Python package and model weights | BSD 3-Clause |
| [ncnn](https://github.com/Tencent/ncnn) | Optional Vulkan inference runtime used by `realesrgan-ncnn-vulkan` | BSD 3-Clause, with separately listed third-party components |
| [PyTorch](https://github.com/pytorch/pytorch) | Optional CPU FP32 inference | BSD-style licence and listed third-party notices |
| [BasicSR](https://github.com/XPixelGroup/BasicSR) | Optional Real-ESRGAN Python dependency | Apache-2.0 |
| [OpenCV](https://github.com/opencv/opencv) | Optional CPU worker image I/O | Apache-2.0 |

Users who download binaries or weights remain responsible for complying with
the licence and redistribution terms attached to those files. The installer in
this repository deliberately does not download or redistribute them.

The NCNN path always asks the model for its native 4× result and then uses
FFmpeg Lanczos to fit the selected output canvas. This preserves the proven
workaround for corrupted/zoomed tile output seen when `realesrgan-x4plus` is
asked for 2× output in some NCNN builds.
