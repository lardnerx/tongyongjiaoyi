"use client";

import { useEffect, useRef, useState } from "react";

interface MapPoint {
  id: string;
  lat: number;
  lng: number;
  label: string;
}

interface MapViewProps {
  points: MapPoint[];
  center?: { lat: number; lng: number };
  zoom?: number;
  className?: string;
  onPointClick?: (id: string) => void;
}

declare global {
  interface Window {
    AMap: any;
    _AMapSecurityConfig: { securityJsCode: string };
  }
}

let sdkLoaded: Promise<void> | null = null;

function loadAmapSDK(): Promise<void> {
  if (sdkLoaded) return sdkLoaded;
  sdkLoaded = new Promise((resolve, reject) => {
    const key = process.env.NEXT_PUBLIC_AMAP_KEY || "";
    const securityCode = process.env.NEXT_PUBLIC_AMAP_SECURITY_CODE || "";
    if (securityCode) {
      window._AMapSecurityConfig = { securityJsCode: securityCode };
    }
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("高德地图 SDK 加载失败"));
    document.head.appendChild(script);
  });
  return sdkLoaded;
}

export function MapView({
  points,
  center,
  zoom = 13,
  className = "w-full h-80",
  onPointClick,
}: MapViewProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<any>(null);
  const markersRef = useRef<any[]>([]);
  const [sdkFailed, setSdkFailed] = useState(false);
  // 地图实例异步创建完成，标记绘制需要等它就绪后再执行
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadAmapSDK()
      .then(() => {
        if (cancelled || !mapRef.current) return;
        const AMap = window.AMap;
        const defaultCenter: [number, number] = center
          ? [center.lng, center.lat]
          : [116.397428, 39.90923]; // 默认天安门
        mapInstance.current = new AMap.Map(mapRef.current, {
          zoom,
          center: defaultCenter,
        });
        setReady(true);
        // 未指定中心点时，默认定位到当前位置
        if (!center && typeof navigator !== "undefined" && navigator.geolocation) {
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              if (cancelled) return;
              mapInstance.current?.setCenter?.([
                pos.coords.longitude,
                pos.coords.latitude,
              ]);
            },
            () => {},
            { enableHighAccuracy: true, timeout: 8000 }
          );
        }
      })
      .catch(() => {
        setSdkFailed(true);
      });
    return () => {
      cancelled = true;
      if (mapInstance.current) {
        mapInstance.current.destroy();
        mapInstance.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 外部传入的中心点变化时跟随（如定位完成后回填当前位置）
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || !ready || !center) return;
    map.setCenter?.([center.lng, center.lat]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center?.lat, center?.lng, ready]);

  // 更新标记
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || !ready || sdkFailed) return;

    // 清除旧标记
    markersRef.current.forEach((m) => map.remove(m));
    markersRef.current = [];

    // 添加新标记
    const AMap = window.AMap;
    points.forEach((pt) => {
      const marker = new AMap.Marker({
        position: [pt.lng, pt.lat],
        map,
        title: pt.label,
        label: {
          content: `<div style="background:#1677ff;color:#fff;padding:2px 6px;border-radius:4px;font-size:12px;white-space:nowrap">${pt.label}</div>`,
          direction: "top",
          offset: new AMap.Pixel(0, -4),
        },
      });
      if (onPointClick) {
        marker.on("click", () => onPointClick(pt.id));
      }
      markersRef.current.push(marker);
    });

    // 自适应视野
    if (points.length > 0) {
      map.setFitView(markersRef.current, false, [40, 40, 40, 40]);
    }
  }, [points, ready, sdkFailed, onPointClick]);

  if (sdkFailed) {
    return (
      <div
        className={`${className} rounded-lg border border-gray-300 bg-gray-50 flex items-center justify-center`}
      >
        <p className="text-sm text-gray-500">地图加载失败，请检查网络和 AMap 配置</p>
      </div>
    );
  }

  return (
    <div
      ref={mapRef}
      className={`${className} rounded-lg border border-gray-300`}
    />
  );
}