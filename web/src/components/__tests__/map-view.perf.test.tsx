import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import type { MapView as MapViewType } from "../map-view";

// ── 测试数据点类型 ──
interface TestMapPoint {
  id: string;
  lat: number;
  lng: number;
  label: string;
}

// ── AMap SDK Mock 工厂 ──
function createMockAMap() {
  const mockMap = {
    remove: vi.fn<[unknown]>(),
    setFitView: vi.fn<[unknown, unknown, unknown]>(),
    destroy: vi.fn(),
  };
  const MockMap = vi.fn(() => mockMap);
  const MockMarker = vi.fn(() => ({ on: vi.fn<[string, () => void]>() }));
  const MockBounds = vi.fn(() => ({ extend: vi.fn() }));
  const MockLngLat = vi.fn();
  const MockPixel = vi.fn();
  return {
    instance: { Map: MockMap, Marker: MockMarker, Bounds: MockBounds, LngLat: MockLngLat, Pixel: MockPixel },
    mockMap,
    MockMap,
    MockMarker,
    MockBounds,
  };
}

// ── 测试数据生成器 ──
function generatePoints(count: number, seed = 0): TestMapPoint[] {
  const baseLat = 31.23;
  const baseLng = 121.47;
  return Array.from({ length: count }, (_, i) => {
    const offset = seed + i;
    return {
      id: `p_${seed}_${i}`,
      lat: baseLat + offset * 0.005,
      lng: baseLng + offset * 0.005,
      label: `标记#${offset}`,
    };
  });
}

// ── 辅助：等待组件完成 SDK 加载和地图初始化 ──
async function waitForMapReady() {
  await vi.waitFor(
    () => { expect(window.AMap.Map).toHaveBeenCalled(); },
    { timeout: 3000, interval: 10 },
  );
}

// ── 辅助：等待标记渲染完成 ──
async function waitForMarkers(count: number) {
  await vi.waitFor(
    () => { expect(window.AMap.Marker).toHaveBeenCalledTimes(count); },
    { timeout: 3000, interval: 10 },
  );
}

// ═══════════════════════════════════════════════
// 主测试套件 - 每次测试前重置模块以确保 sdkLoaded 状态
// ═══════════════════════════════════════════════
describe("MapView 标记渲染性能", () => {
  let MapViewComponent: typeof MapViewType;
  let originalCreateElement: typeof document.createElement;
  let amap: ReturnType<typeof createMockAMap>;

  beforeEach(async () => {
    vi.clearAllMocks();
    originalCreateElement = document.createElement.bind(document);

    // 拦截 script 创建，onload 立即执行模拟 SDK 加载成功
    vi.spyOn(document, "createElement").mockImplementation(
      (tagName: string, options?: ElementCreationOptions) => {
        const el = originalCreateElement(tagName, options);
        if (tagName.toLowerCase() === "script") {
          Object.defineProperty(el, "onload", {
            set(fn) { if (typeof fn === "function") fn(); },
            configurable: true,
          });
        }
        return el;
      },
    );

    amap = createMockAMap();
    (window as any).AMap = amap.instance;
    (window as any)._AMapSecurityConfig = { securityJsCode: "test" };
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).AMap;
    delete (window as any)._AMapSecurityConfig;
  });

  it("基础：空 points 不创建标记", async () => {
    const { MapView } = await import("../map-view");
    render(<MapView points={[]} />);
    await waitForMapReady();
    expect(amap.MockMarker).not.toHaveBeenCalled();
  });

  it("性能：10 个标记首次渲染时间", async () => {
    const { MapView } = await import("../map-view");
    const points = generatePoints(10);
    const start = performance.now();

    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    await act(async () => { rerender(<MapView points={points} />); });
    await waitForMarkers(10);
    const elapsed = performance.now() - start;

    console.log(`  [10 markers] 首次渲染耗时: ${elapsed.toFixed(2)}ms`);
    expect(elapsed).toBeLessThan(2000);
    expect(amap.MockMarker).toHaveBeenCalledTimes(10);
    expect(amap.mockMap.setFitView).toHaveBeenCalled();
  });

  it("性能：50 个标记渲染时间", async () => {
    const { MapView } = await import("../map-view");
    const points = generatePoints(50);
    const start = performance.now();

    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    await act(async () => { rerender(<MapView points={points} />); });
    await waitForMarkers(50);
    const elapsed = performance.now() - start;

    console.log(`  [50 markers] 渲染耗时: ${elapsed.toFixed(2)}ms`);
    expect(elapsed).toBeLessThan(1000);
    expect(amap.MockMarker).toHaveBeenCalledTimes(50);
  });

  it("性能：100 个标记渲染时间", async () => {
    const { MapView } = await import("../map-view");
    const points = generatePoints(100);
    const start = performance.now();

    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    await act(async () => { rerender(<MapView points={points} />); });
    await waitForMarkers(100);
    const elapsed = performance.now() - start;

    console.log(`  [100 markers] 渲染耗时: ${elapsed.toFixed(2)}ms`);
    expect(elapsed).toBeLessThan(1500);
    expect(amap.MockMarker).toHaveBeenCalledTimes(100);
    expect(amap.mockMap.remove).toHaveBeenCalledTimes(0);
  });

  it("性能：标记增量更新 (10→50→10) 耗时", async () => {
    const { MapView } = await import("../map-view");
    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    // Phase 1: 10 markers
    const t1 = performance.now();
    await act(async () => { rerender(<MapView points={generatePoints(10, 0)} />); });
    await waitForMarkers(10);
    const phase1 = performance.now() - t1;
    console.log(`  [Phase 1: 10] 耗时: ${phase1.toFixed(2)}ms`);

    amap.MockMarker.mockClear();
    amap.mockMap.remove.mockClear();

    // Phase 2: 50 markers
    const t2 = performance.now();
    await act(async () => { rerender(<MapView points={generatePoints(50, 10)} />); });
    await waitForMarkers(50);
    const phase2 = performance.now() - t2;
    console.log(`  [Phase 2: 50] 耗时: ${phase2.toFixed(2)}ms`);

    amap.MockMarker.mockClear();
    amap.mockMap.remove.mockClear();

    // Phase 3: back to 10 markers
    const t3 = performance.now();
    await act(async () => { rerender(<MapView points={generatePoints(10, 60)} />); });
    await waitForMarkers(10);
    const phase3 = performance.now() - t3;
    console.log(`  [Phase 3: 10] 耗时: ${phase3.toFixed(2)}ms`);

    expect(phase1).toBeLessThan(500);
    expect(phase2).toBeLessThan(500);
    expect(phase3).toBeLessThan(500);
  });

  it("性能：高频连续更新 10 次", async () => {
    const { MapView } = await import("../map-view");
    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    const timings: number[] = [];
    for (let i = 0; i < 10; i++) {
      amap.MockMarker.mockClear();
      amap.mockMap.remove.mockClear();

      const start = performance.now();
      await act(async () => { rerender(<MapView points={generatePoints(5, i * 5)} />); });
      await vi.waitFor(
        () => { expect(amap.MockMarker).toHaveBeenCalledTimes(5); },
        { timeout: 2000, interval: 5 },
      );
      timings.push(performance.now() - start);
    }

    const avg = timings.reduce((a, b) => a + b, 0) / timings.length;
    const max = Math.max(...timings);
    const min = Math.min(...timings);
    console.log(`  [10 rapid updates x 5 markers] 平均: ${avg.toFixed(2)}ms, 最大: ${max.toFixed(2)}ms, 最小: ${min.toFixed(2)}ms`);

    timings.forEach((t) => expect(t).toBeLessThan(200));
    expect(avg).toBeLessThan(100);
  });

  it("性能：标记清除并重新添加 20 个", async () => {
    const { MapView } = await import("../map-view");
    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    // Add 20
    await act(async () => { rerender(<MapView points={generatePoints(20, 0)} />); });
    await waitForMarkers(20);

    // Clear
    amap.MockMarker.mockClear();
    amap.mockMap.remove.mockClear();

    const t1 = performance.now();
    await act(async () => { rerender(<MapView points={[]} />); });
    await vi.waitFor(
      () => { expect(amap.mockMap.remove.mock.calls.length).toBeGreaterThanOrEqual(20); },
      { timeout: 2000, interval: 5 },
    );
    const clearTime = performance.now() - t1;
    console.log(`  [Clear 20 markers] 耗时: ${clearTime.toFixed(2)}ms`);

    // Re-add 20
    amap.MockMarker.mockClear();
    amap.mockMap.remove.mockClear();

    const t2 = performance.now();
    await act(async () => { rerender(<MapView points={generatePoints(20, 100)} />); });
    await waitForMarkers(20);
    const addTime = performance.now() - t2;
    console.log(`  [Re-add 20 markers] 耗时: ${addTime.toFixed(2)}ms`);

    expect(clearTime).toBeLessThan(300);
    expect(addTime).toBeLessThan(300);
  });

  it("性能：30 个标记点击事件注册", async () => {
    const { MapView } = await import("../map-view");
    const onClick = vi.fn();
    const start = performance.now();

    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    await act(async () => { rerender(<MapView points={generatePoints(30)} onPointClick={onClick} />); });
    await waitForMarkers(30);
    const elapsed = performance.now() - start;

    console.log(`  [30 markers with click handler] 耗时: ${elapsed.toFixed(2)}ms`);
    expect(elapsed).toBeLessThan(1000);

    const markerInstances = amap.MockMarker.mock.results;
    (markerInstances as { value: { on: ReturnType<typeof vi.fn> } }[]).forEach((result) => {
      expect(result.value.on).toHaveBeenCalledWith("click", expect.any(Function));
    });
  });

  it("压力：200 个标记渲染时间", async () => {
    const { MapView } = await import("../map-view");
    const points = generatePoints(200);
    const start = performance.now();

    const { rerender } = render(<MapView points={[]} />);
    await waitForMapReady();

    await act(async () => { rerender(<MapView points={points} />); });
    await waitForMarkers(200);
    const elapsed = performance.now() - start;

    console.log(`  [200 markers stress test] 耗时: ${elapsed.toFixed(2)}ms`);
    expect(elapsed).toBeLessThan(3000);
    expect(amap.MockMarker).toHaveBeenCalledTimes(200);
    expect(amap.MockBounds).toHaveBeenCalled();
  });
});