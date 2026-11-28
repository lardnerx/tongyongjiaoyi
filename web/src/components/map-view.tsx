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
  /** 当前用户位置（司机），以绿色标记显示在地图上。 */
  self?: { lat: number; lng: number; label?: string };
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

export function loadAmapSDK(): Promise<void> {
  if (sdkLoaded) return sdkLoaded;
  sdkLoaded = new Promise((resolve, reject) => {
    const key = process.env.NEXT_PUBLIC_AMAP_KEY || "";
    const securityCode = process.env.NEXT_PUBLIC_AMAP_SECURITY_CODE || "";
    if (securityCode) {
      window._AMapSecurityConfig = { securityJsCode: securityCode };
    }
    const script = document.createElement("script");
    // Geocoder 用于把定位坐标解析成具体地址
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}&plugin=AMap.Geocoder`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("高德地图 SDK 加载失败"));
    document.head.appendChild(script);
  });
  return sdkLoaded;
}

/** 逆地理编码：坐标 → 具体地址；SDK 未就绪或失败时返回空字符串。 */
export function reverseGeocodeAddress(lat: number, lng: number): Promise<string> {
  return new Promise((resolve) => {
    const AMap = typeof window !== "undefined" ? window.AMap : null;
    if (!AMap?.Geocoder) {
      resolve("");
      return;
    }
    try {
      const geocoder = new AMap.Geocoder();
      geocoder.getAddress([lng, lat], (status: string, result: any) => {
        const address =
          status === "complete" && result?.info === "OK"
            ? result?.regeocode?.formattedAddress
            : "";
        resolve(address || "");
      });
    } catch {
      resolve("");
    }
  });
}

export function MapView({
  points,
  center,
  self,
  zoom = 13,
  className = "w-full h-80",
  onPointClick,
}: MapViewProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<any>(null);
  const markersRef = useRef<any[]>([]);
  const selfMarkerRef = useRef<any>(null);
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

    // 当前用户位置标记（绿色），便于区分「我的位置」与待抢订单
    if (self) {
      if (selfMarkerRef.current) {
        selfMarkerRef.current.setPosition?.([self.lng, self.lat]);
      } else {
        selfMarkerRef.current = new AMap.Marker({
          position: [self.lng, self.lat],
          map,
          zIndex: 200,
          title: self.label || "我的位置",
          label: {
            content: `<div style="background:#16a34a;color:#fff;padding:2px 6px;border-radius:4px;font-size:12px;white-space:nowrap">${self.label || "我的位置"}</div>`,
            direction: "top",
            offset: new AMap.Pixel(0, -4),
          },
        });
      }
    } else if (selfMarkerRef.current) {
      map.remove(selfMarkerRef.current);
      selfMarkerRef.current = null;
    }

    // 自适应视野（同时包含「我的位置」）
    if (points.length > 0) {
      const fitTargets = selfMarkerRef.current
        ? [...markersRef.current, selfMarkerRef.current]
        : markersRef.current;
      map.setFitView(fitTargets, false, [40, 40, 40, 40]);
    }
  }, [points, self, ready, sdkFailed, onPointClick]);

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