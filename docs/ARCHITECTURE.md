# Architecture

All entry points call the same `video_upscaler.engine.Engine`.

```text
Dolphin service menu ─┐
Nautilus Script ──────┼─> shared Tk GUI ─┐
Nautilus extension ───┘                  │
standalone CLI ──────────────────────────┼─> core engine
                                        │      ├─ FFmpeg Lanczos
                                        │      ├─ Real-ESRGAN PyTorch CPU
                                        │      └─ Real-ESRGAN NCNN/Vulkan GPU
                                        └─ progress / cancellation / notifications
```

## Device identity

GPU IDs are backend-specific. The NCNN backend obtains IDs from NCNN's own
Vulkan startup report and falls back only to `vulkaninfo` Vulkan enumeration.
It never treats CUDA, NVML, VA-API or DRM indices as interchangeable.

Encoding is separate from scaling. Version 0.1 deliberately offers x264 only:
it is universally available in supported FFmpeg builds and has been exercised
end to end. Merely listing NVENC/VA-API/QSV encoders is not sufficient proof
that a particular device, driver and pixel-format path works.

## Job lifecycle

1. Validate explicit configuration, backend dependencies and collision policy.
2. Probe dimensions, frame rate, frame count, duration and audio.
3. Acquire a user-level single-job lock.
4. Check free space and create an isolated temporary directory.
5. Run a backend through argv arrays—never through interpolated shell text.
6. Encode into a uniquely named partial output.
7. Verify dimensions, duration, audio and full FFmpeg decode.
8. Atomically replace the requested destination only after validation.
9. Clean frames and partial output after success, failure or cancellation.

Progress is stage-local and based on real FFmpeg frame reports or completed
neural frames. The GUI does not manufacture a cross-stage ETA or percentage.
