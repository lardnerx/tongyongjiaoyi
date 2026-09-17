"use client";

import type { PaymentMethod } from "./payment-method-selector";

interface Props {
  method: PaymentMethod;
  amount: number;
}

const QR_SIZE = 21; // 21x21 grid
const MODULE_SIZE = 8; // px per module
const PADDING = 24; // px padding around QR
const CANVAS_SIZE = QR_SIZE * MODULE_SIZE + PADDING * 2;

/**
 * 基于 seed 的确定性伪随机数生成器，确保每次渲染图案一致。
 */
function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

/**
 * 生成 QR 码风格的模块矩阵。
 * - 固定位置探测图形（左上、右上、左下）
 * - 其余区域用伪随机填充
 * - 中心留白区域用于 logo
 */
function generateModules(seed: number): boolean[][] {
  const rand = seededRandom(seed);
  const grid: boolean[][] = [];

  for (let row = 0; row < QR_SIZE; row++) {
    grid[row] = [];
    for (let col = 0; col < QR_SIZE; col++) {
      let isDark = false;

      // 位置探测图形：左上角 (0,0)-(6,6)
      if (row <= 6 && col <= 6) {
        isDark = isFinderPattern(row, col);
      }
      // 右上角 (0, 14)-(6, 20)
      else if (row <= 6 && col >= QR_SIZE - 7) {
        isDark = isFinderPattern(row, col - (QR_SIZE - 7));
      }
      // 左下角 (14, 0)-(20, 6)
      else if (row >= QR_SIZE - 7 && col <= 6) {
        isDark = isFinderPattern(row - (QR_SIZE - 7), col);
      }
      // 中心区域（logo 位置）留白
      else if (row >= 8 && row <= 12 && col >= 8 && col <= 12) {
        isDark = false;
      }
      // 其他区域：伪随机
      else {
        isDark = rand() > 0.5;
      }

      grid[row][col] = isDark;
    }
  }

  return grid;
}

/** 位置探测图形（3 层同心方块）。 */
function isFinderPattern(r: number, c: number): boolean {
  // 外层 7x7
  if (r === 0 || r === 6 || c === 0 || c === 6) return true;
  // 内层 5x5（留白）
  if (r === 1 || r === 5 || c === 1 || c === 5) return false;
  // 核心 3x3
  if (r >= 2 && r <= 4 && c >= 2 && c <= 4) return true;
  return false;
}

/**
 * 生成模拟二维码的 SVG。
 * 使用确定性伪随机确保渲染一致性，支付宝/微信仅颜色不同。
 */
function generateQrSvg(method: PaymentMethod, seed: number): string {
  const grid = generateModules(seed);
  const fg = method === "alipay" ? "#1677ff" : "#07c160";
  const bg = method === "alipay" ? "#e6f4ff" : "#f0fff0";
  const logoFg = "#ffffff";
  const logoBg = method === "alipay" ? "#1677ff" : "#07c160";

  let modules = "";
  for (let row = 0; row < QR_SIZE; row++) {
    for (let col = 0; col < QR_SIZE; col++) {
      if (grid[row][col]) {
        const x = PADDING + col * MODULE_SIZE;
        const y = PADDING + row * MODULE_SIZE;
        modules += `<rect x="${x}" y="${y}" width="${MODULE_SIZE}" height="${MODULE_SIZE}" fill="${fg}" />`;
      }
    }
  }

  return `
    <svg viewBox="0 0 ${CANVAS_SIZE} ${CANVAS_SIZE}" xmlns="http://www.w3.org/2000/svg">
      <!-- 背景 -->
      <rect width="${CANVAS_SIZE}" height="${CANVAS_SIZE}" rx="8" fill="${bg}" />
      <!-- 模块 -->
      ${modules}
      <!-- 中心 Logo -->
      <rect x="${PADDING + 8 * MODULE_SIZE}" y="${PADDING + 8 * MODULE_SIZE}" width="${5 * MODULE_SIZE}" height="${5 * MODULE_SIZE}" rx="6" fill="${logoBg}" />
      <text x="${CANVAS_SIZE / 2}" y="${CANVAS_SIZE / 2 + 4}" text-anchor="middle" dominant-baseline="middle" fill="${logoFg}" font-size="10" font-weight="bold" font-family="system-ui, sans-serif">
        ${method === "alipay" ? "支" : "微"}
      </text>
    </svg>
  `;
}

export function MockQrDisplay({ method, amount }: Props) {
  // 使用 amount 作为 seed 的一部分，确保金额不同时图案不同
  const seed = Math.round(amount * 100) + (method === "alipay" ? 0 : 1);
  const svg = generateQrSvg(method, seed);
  const dataUri = `data:image/svg+xml,${encodeURIComponent(svg)}`;

  return (
    <div className="rounded-lg border bg-white p-4 space-y-3">
      <h3 className="font-medium text-sm text-gray-500">扫码支付</h3>
      <div className="flex flex-col items-center gap-3">
        <img
          src={dataUri}
          alt={`${method === "alipay" ? "支付宝" : "微信支付"} Mock 二维码`}
          className="w-48 h-48"
        />
        <p className="text-sm text-gray-500">
          请使用{method === "alipay" ? "支付宝" : "微信"}扫码支付
        </p>
        <p className="text-xs text-gray-400">
          （开发环境 Mock 二维码，点击「确认支付」即可模拟支付）
        </p>
      </div>
    </div>
  );
}