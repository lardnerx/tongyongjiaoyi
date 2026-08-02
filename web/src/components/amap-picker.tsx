"use client";

import { useEffect, useRef, useState } from "react";

interface AmapPickerProps {
  value?: { lat: number; lng: number };
  onChange: (loc: { lat: number; lng: number; address: string }) => void;
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

export function AmapPicker({ value, onChange }: AmapPickerProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const [address, setAddress] = useState("");
  const [sdkFailed, setSdkFailed] = useState(false);
  const [manualLat, setManualLat] = useState("");
  const [manualLng, setManualLng] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadAmapSDK()
      .then(() => {
        if (cancelled || !mapRef.current) return;
        const AMap = window.AMap;
        const center: [number, number] = value
          ? [value.lng, value.lat]
          : [116.397428, 39.90923]; // 默认天安门
        mapInstance.current = new AMap.Map(mapRef.current, {
          zoom: 15,
          center,
        });
        mapInstance.current.on("click", (e: any) => {
          const lng = e.lnglat.getLng();
          const lat = e.lnglat.getLat();
          if (markerRef.current) {
            markerRef.current.setPosition([lng, lat]);
          } else {
            markerRef.current = new AMap.Marker({
              position: [lng, lat],
              map: mapInstance.current,
            });
          }
          // 逆地理编码
          const geocoder = new AMap.Geocoder();
          geocoder.getAddress([lng, lat], (status: string, result: any) => {
            if (status === "complete" && result.info === "OK") {
              const addr = result.regeocode.formattedAddress;
              setAddress(addr);
              onChange({ lat, lng, address: addr });
            } else {
              setAddress(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
              onChange({ lat, lng, address: `${lat.toFixed(6)}, ${lng.toFixed(6)}` });
            }
          });
        });
      })
      .catch(() => {
        // SDK 加载失败，显示降级 UI
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

  const handleManualSubmit = () => {
    const lat = parseFloat(manualLat);
    const lng = parseFloat(manualLng);
    if (isNaN(lat) || isNaN(lng)) return;
    const addr = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    setAddress(addr);
    onChange({ lat, lng, address: addr });
  };

  return (
    <div className="space-y-2">
      {!sdkFailed && (
        <div
          ref={mapRef}
          className="w-full h-64 rounded-lg border border-gray-300"
          data-testid="amap-container"
        />
      )}
      {sdkFailed && (
        <div className="w-full h-64 rounded-lg border border-gray-300 bg-gray-50 flex flex-col items-center justify-center space-y-3 p-4" data-testid="amap-fallback">
          <p className="text-sm text-gray-500 text-center">地图加载失败，请手动输入坐标</p>
          <div className="flex gap-2 w-full">
            <input
              type="text"
              placeholder="纬度 (lat)"
              className="flex-1 rounded-md border border-gray-300 p-2 text-sm"
              value={manualLat}
              onChange={(e) => setManualLat(e.target.value)}
              data-testid="manual-lat"
            />
            <input
              type="text"
              placeholder="经度 (lng)"
              className="flex-1 rounded-md border border-gray-300 p-2 text-sm"
              value={manualLng}
              onChange={(e) => setManualLng(e.target.value)}
              data-testid="manual-lng"
            />
            <button
              type="button"
              className="rounded-md bg-blue-600 text-white px-4 py-2 text-sm"
              onClick={handleManualSubmit}
              data-testid="manual-submit"
            >
              确定
            </button>
          </div>
          <button
            type="button"
            className="text-xs text-blue-600 underline"
            onClick={() => {
              setManualLat("39.909230");
              setManualLng("116.397428");
            }}
          >
            使用默认坐标（天安门）
          </button>
        </div>
      )}
      {address && (
        <p className="text-sm text-gray-600" data-testid="selected-address">
          已选位置：{address}
        </p>
      )}
    </div>
  );
}
