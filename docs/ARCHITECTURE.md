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
4. Create an isolated temporary directory.
5. Run a backend through argv arrays—never through interpolated shell text.
6. For neural backends, stream decoded PNGs into a bounded frame batch, enhance
   that batch, feed it to one persistent FFmpeg encoder, then replace the batch
   files. Batch size is capped by both a byte target and a 120-frame ceiling.
7. Encode into a uniquely named partial output.
8. Verify dimensions, frame count, duration, audio and full FFmpeg decode.
9. Atomically replace the requested destination only after validation.
10. Clean frames and partial output after success, failure or cancellation.

Progress is stage-local and based on real FFmpeg frame reports or completed
neural frames. The GUI does not manufacture a cross-stage ETA or percentage.

The neural pipeline never accumulates a whole video's decoded or enhanced
frames. Source extraction and final encoding are persistent processes; only the
current batch exists on disk. A write or child-process `ENOSPC` failure aborts
the job and removes its partial output and isolated workspace.
