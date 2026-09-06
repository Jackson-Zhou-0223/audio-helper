import { useEffect, useRef, useState } from "react";
import {
  MAX_DURATION_MS,
  MAX_FILE_BYTES,
  MIN_DURATION_MS,
  extensionForMimeType,
  formatBytes,
  formatDuration,
  microphoneErrorMessage,
  pickRecordingMimeType,
  stopMediaStream,
} from "../recording.js";

function Recorder() {
  const [phase, setPhase] = useState("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState("");
  const [clip, setClip] = useState(null);

  const holdingRef = useRef(false);
  const sessionRef = useRef(0);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const startedAtRef = useRef(0);
  const limitTimerRef = useRef(0);
  const tickTimerRef = useRef(0);
  const stopReasonRef = useRef("release");
  const clipUrlRef = useRef("");
  const stoppingRef = useRef(false);

  function clearTimers() {
    window.clearTimeout(limitTimerRef.current);
    window.clearInterval(tickTimerRef.current);
    limitTimerRef.current = 0;
    tickTimerRef.current = 0;
  }

  function revokeClipUrl() {
    if (clipUrlRef.current) {
      URL.revokeObjectURL(clipUrlRef.current);
      clipUrlRef.current = "";
    }
  }

  function releaseMicrophone() {
    stopMediaStream(streamRef.current);
    streamRef.current = null;
  }

  function fail(message) {
    clearTimers();
    holdingRef.current = false;
    stopReasonRef.current = "cancel";
    setError(message);
    window.removeEventListener("pointerup", onWindowPointerUp);
    window.removeEventListener("pointercancel", onWindowPointerCancel);
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      stoppingRef.current = true;
      recorderRef.current.stop();
      return;
    }
    releaseMicrophone();
    recorderRef.current = null;
    chunksRef.current = [];
    setPhase("idle");
    setElapsedMs(0);
    setError(message);
  }

  function finishClip(blob, mimeType, durationMs) {
    revokeClipUrl();
    const url = URL.createObjectURL(blob);
    clipUrlRef.current = url;
    const extension = extensionForMimeType(mimeType);
    setClip({
      url,
      mimeType,
      size: blob.size,
      durationMs,
      fileName: `meetup-recording.${extension}`,
    });
    setPhase("ready");
    setElapsedMs(durationMs);
  }

  function handleRecorderStop() {
    stoppingRef.current = false;
    const reason = stopReasonRef.current;
    const durationMs = Math.max(0, Date.now() - startedAtRef.current);
    const mimeType = recorderRef.current?.mimeType || pickRecordingMimeType() || "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mimeType });

    recorderRef.current = null;
    chunksRef.current = [];
    releaseMicrophone();
    clearTimers();
    holdingRef.current = false;

    if (reason === "cancel") {
      setPhase("idle");
      setElapsedMs(0);
      return;
    }

    if (durationMs < MIN_DURATION_MS) {
      setPhase("idle");
      setElapsedMs(0);
      setError("录音太短，请按住至少 1 秒。");
      return;
    }

    if (blob.size > MAX_FILE_BYTES) {
      setPhase("idle");
      setElapsedMs(0);
      setError("录音文件过大，请控制在 5MB 以内。");
      return;
    }

    if (blob.size === 0) {
      setPhase("idle");
      setElapsedMs(0);
      setError("录制失败，没有生成有效音频。");
      return;
    }

    setError("");
    finishClip(blob, mimeType, Math.min(durationMs, MAX_DURATION_MS));
  }

  function stopRecording(reason) {
    if (stoppingRef.current) {
      return;
    }

    const hadSession =
      holdingRef.current || Boolean(recorderRef.current) || Boolean(streamRef.current);
    holdingRef.current = false;
    stopReasonRef.current = reason;
    clearTimers();
    window.removeEventListener("pointerup", onWindowPointerUp);
    window.removeEventListener("pointercancel", onWindowPointerCancel);

    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      stoppingRef.current = true;
      recorder.stop();
      return;
    }

    sessionRef.current += 1;
    releaseMicrophone();
    setPhase("idle");
    setElapsedMs(0);
    if (!hadSession || reason === "release" || reason === "limit" || reason === "cancel") {
      return;
    }
    setError("录制失败，请重试。");
  }

  function onWindowPointerUp() {
    if (holdingRef.current || recorderRef.current) {
      stopRecording("release");
    }
  }

  function onWindowPointerCancel() {
    if (holdingRef.current || recorderRef.current) {
      setError("");
      stopRecording("cancel");
    }
  }

  async function startRecording() {
    const mimeType = pickRecordingMimeType();
    if (!mimeType) {
      setError("当前浏览器不支持 WebM/Opus 录音，请改用 Chrome 或 Edge。");
      setPhase("idle");
      return;
    }

    const session = sessionRef.current + 1;
    sessionRef.current = session;
    holdingRef.current = true;
    stoppingRef.current = false;
    stopReasonRef.current = "release";
    chunksRef.current = [];
    setError("");
    setPhase("requesting");
    setElapsedMs(0);

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      holdingRef.current = false;
      setPhase("idle");
      setError(microphoneErrorMessage(error));
      return;
    }

    if (session !== sessionRef.current || !holdingRef.current) {
      stopMediaStream(stream);
      setPhase("idle");
      return;
    }

    streamRef.current = stream;

    let recorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType });
    } catch (error) {
      stopMediaStream(stream);
      streamRef.current = null;
      holdingRef.current = false;
      setPhase("idle");
      setError("录制失败，当前浏览器无法按检测到的格式录音。");
      return;
    }

    recorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };
    recorder.onerror = () => {
      fail("录制失败，请重试。");
    };
    recorder.onstop = handleRecorderStop;

    try {
      recorder.start();
    } catch (error) {
      fail("录制失败，请重试。");
      return;
    }

    startedAtRef.current = Date.now();
    setPhase("recording");
    window.addEventListener("pointerup", onWindowPointerUp);
    window.addEventListener("pointercancel", onWindowPointerCancel);
    tickTimerRef.current = window.setInterval(() => {
      setElapsedMs(Math.min(MAX_DURATION_MS, Date.now() - startedAtRef.current));
    }, 100);
    limitTimerRef.current = window.setTimeout(() => {
      stopRecording("limit");
    }, MAX_DURATION_MS);
  }

  function onPointerDown(event) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    if (phase === "recording" || phase === "requesting") {
      return;
    }
    startRecording();
  }

  function onPointerUp(event) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (phase === "recording" || phase === "requesting" || holdingRef.current) {
      stopRecording("release");
    }
  }

  function onPointerCancel(event) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (phase === "recording" || phase === "requesting" || holdingRef.current) {
      setError("");
      stopRecording("cancel");
    }
  }

  function onContextMenu(event) {
    event.preventDefault();
  }

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape" && holdingRef.current) {
        setError("");
        stopRecording("cancel");
      }
    }

    function onVisibilityChange() {
      if (document.hidden && holdingRef.current) {
        setError("");
        stopRecording("cancel");
      }
    }

    window.addEventListener("keydown", onKeyDown);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      sessionRef.current += 1;
      holdingRef.current = false;
      stopReasonRef.current = "cancel";
      clearTimers();
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      } else {
        releaseMicrophone();
      }
      revokeClipUrl();
    };
    // Cleanup only on unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const recording = phase === "recording" || phase === "requesting";
  const statusText =
    phase === "requesting"
      ? "正在申请麦克风…"
      : phase === "recording"
        ? `录音中 ${formatDuration(elapsedMs)} / 60.0 秒`
        : clip
          ? "录音完成，可以试听或下载"
          : "按住按钮说话，松开结束";

  return (
    <section className="recorder">
      <button
        type="button"
        className={recording ? "record-button is-recording" : "record-button"}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onContextMenu={onContextMenu}
        aria-pressed={recording}
      >
        {recording ? "松开结束" : "按住说话"}
      </button>
      <p className="recorder-status">{statusText}</p>
      {error ? <p className="recorder-error">{error}</p> : null}
      {clip ? (
        <div className="clip-panel">
          <audio controls src={clip.url} preload="metadata">
            浏览器不支持音频播放
          </audio>
          <p className="clip-meta">
            格式 {clip.mimeType} · {formatBytes(clip.size)} · {formatDuration(clip.durationMs)}
          </p>
          <a className="download-link" href={clip.url} download={clip.fileName}>
            下载录音文件
          </a>
        </div>
      ) : null}
    </section>
  );
}

export default Recorder;
