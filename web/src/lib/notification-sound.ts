/**
 * 订单提示音与语音播报（Web Audio + 浏览器语音合成，无需音频资源）。
 * 用户可在接单大厅关闭提示音，开关状态存 localStorage。
 */

const STORAGE_KEY = "umcp.sound.enabled";

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    if (!audioCtx) {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!Ctor) return null;
      audioCtx = new Ctor();
    }
    if (audioCtx.state === "suspended") {
      void audioCtx.resume();
    }
    return audioCtx;
  } catch {
    return null;
  }
}

/** 播放一个提示音。 */
function tone(
  freq: number,
  delaySeconds: number,
  durationSeconds: number,
  volume = 0.22
): void {
  const ctx = getAudioContext();
  if (!ctx) return;
  const start = ctx.currentTime + delaySeconds;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(volume, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, start + durationSeconds);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(start);
  osc.stop(start + durationSeconds + 0.02);
}

export function isSoundEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) !== "off";
}

export function setSoundEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off");
}

/** 通用提示音：两声短促上扬。 */
export function playAlertTone(): void {
  if (!isSoundEnabled()) return;
  tone(880, 0, 0.16);
  tone(1175, 0.2, 0.16);
}

/** 成功提示音：柔和上行两音。 */
export function playSuccessTone(): void {
  if (!isSoundEnabled()) return;
  tone(523, 0, 0.12);
  tone(784, 0.13, 0.18);
}

/** 语音播报（中文）。 */
export function speak(text: string): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  if (!isSoundEnabled()) return;
  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1;
    utterance.volume = 0.9;
    window.speechSynthesis.speak(utterance);
  } catch {
    // 浏览器不支持时静默忽略
  }
}

/** 新订单到达：提示音 + 语音播报。 */
export function notifyNewOrder(): void {
  if (!isSoundEnabled()) return;
  playAlertTone();
  speak("您有新的订单，请及时抢单");
}
