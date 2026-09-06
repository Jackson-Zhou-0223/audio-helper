export const MIN_DURATION_MS = 1000;
export const MAX_DURATION_MS = 60_000;
export const MAX_FILE_BYTES = 5 * 1024 * 1024;

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm"];

export function pickRecordingMimeType() {
  if (
    typeof MediaRecorder === "undefined" ||
    typeof MediaRecorder.isTypeSupported !== "function"
  ) {
    return null;
  }

  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

export function extensionForMimeType(mimeType) {
  if (typeof mimeType === "string" && mimeType.includes("webm")) {
    return "webm";
  }
  return "webm";
}

export function formatDuration(ms) {
  const totalSeconds = Math.max(0, ms) / 1000;
  return `${totalSeconds.toFixed(1)} 秒`;
}

export function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function microphoneErrorMessage(error) {
  const name = error?.name;
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "麦克风未授权，请在浏览器中允许使用麦克风后再试。";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "没有找到可用的麦克风。";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "无法占用麦克风，可能被其他程序占用。";
  }
  return "录制失败，请重试。";
}

export function stopMediaStream(stream) {
  if (!stream) {
    return;
  }
  for (const track of stream.getTracks()) {
    track.stop();
  }
}
