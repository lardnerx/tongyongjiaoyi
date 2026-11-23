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
    if (!key) {
      reject(new Error("未配置高德地图 Key"));
      return;
    }
    if (securityCode) {
      window._AMapSecurityConfig = { securityJsCode: securityCode };
    }
    const script = document.createElement("script");
    // v2.0 的 Geocoder / Geolocation / PlaceSearch 都是异步插件，必须显式加载
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${key}&plugin=AMap.Geocoder,AMap.Geolocation,AMap.PlaceSearch`;
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
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [address, setAddress] = useState("");
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [keyword, setKeyword] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResults, setSearchResults] = useState<
    { name: string; address: string; lat: number; lng: number }[]
  >([]);
  const [hint, setHint] = useState("");
  const [locating, setLocating] = useState(false);
  const [sdkFailed, setSdkFailed] = useState(false);
  const [manualLat, setManualLat] = useState("");
  const [manualLng, setManualLng] = useState("");

  const placeMarker = (lat: number, lng: number) => {
    const AMap = window.AMap;
    if (!mapInstance.current) return;
    if (markerRef.current) {
      markerRef.current.setPosition([lng, lat]);
    } else {
      markerRef.current = new AMap.Marker({
        position: [lng, lat],
        map: mapInstance.current,
      });
    }
  };

  const applyLocation = (lat: number, lng: number, addr?: string) => {
    const label = addr || `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    placeMarker(lat, lng);
    if (mapInstance.current) {
      mapInstance.current.setCenter([lng, lat]);
      mapInstance.current.setZoom(16);
    }
    setAddress(label);
    setCoords({ lat, lng });
    setHint("");
    setSearchResults([]);
    onChangeRef.current({ lat, lng, address: label });
  };

  /** 逆地理编码：优先取高德返回的详细地址，失败时回落为经纬度或兜底地址。 */
  const applyWithGeocode = (lat: number, lng: number, fallbackAddress?: string) => {
    const AMap = window.AMap;
    let geocoder: any = null;
    try {
      geocoder = new AMap.Geocoder();
    } catch {
      geocoder = null;
    }
    if (!geocoder) {
      applyLocation(lat, lng, fallbackAddress);
      return;
    }
    geocoder.getAddress([lng, lat], (status: string, result: any) => {
      const formatted =
        status === "complete" && result?.info === "OK"
          ? result?.regeocode?.formattedAddress
          : "";
      applyLocation(lat, lng, formatted || fallbackAddress);
    });
  };

  const handleSearch = () => {
    const AMap = window.AMap;
    const q = keyword.trim();
    if (!AMap || !q) return;
    setSearching(true);
    setSearchError("");
    setSearchResults([]);
    try {
      const placeSearch = new AMap.PlaceSearch({
        pageSize: 10,
        pageIndex: 1,
        extensions: "base",
      });
      placeSearch.search(q, (status: string, result: any) => {
        setSearching(false);
        const pois = result?.poiList?.pois;
        if (status !== "complete" || !pois || pois.length === 0) {
          setSearchError("未搜索到相关地点，请换个关键词或直接点击地图选择");
          return;
        }
        setSearchResults(
          pois
            .filter((poi: any) => poi.location)
            .map((poi: any) => ({
              name: poi.name as string,
              address:
                typeof poi.pname === "string"
                  ? `${poi.pname}${poi.cityname ?? ""}${poi.adname ?? ""}${poi.address ?? ""}`
                  : (poi.address as string) || "",
              lat: poi.location.getLat(),
              lng: poi.location.getLng(),
            }))
        );
      });
    } catch {
      setSearching(false);
      setSearchError("搜索服务不可用，请直接点击地图选择");
    }
  };

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
          placeMarker(lat, lng);
          // 逆地理编码（失败时回落为经纬度，保证一定能选到位置）
          applyWithGeocode(lat, lng);
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

  const handleLocate = () => {
    const AMap = window.AMap;
    if (!AMap) return;
    setLocating(true);
    setHint("");
    try {
      const geolocation = new AMap.Geolocation({
        enableHighAccuracy: true,
        timeout: 10000,
        showButton: false,
        showMarker: false,
        showCircle: false,
      });
      geolocation.getCurrentPosition((status: string, result: any) => {
        setLocating(false);
        if (status === "complete" && result.position) {
          const lat = result.position.lat;
          const lng = result.position.lng;
          // 定位接口不一定返回 formattedAddress，统一再做一次逆地理编码
          applyWithGeocode(lat, lng, result.formattedAddress);
        } else {
          setHint("未获取到定位，请点击地图手动选择");
        }
      });
    } catch {
      setLocating(false);
      setHint("当前浏览器不支持定位，请点击地图手动选择");
    }
  };

  const handleManualSubmit = () => {
    const lat = parseFloat(manualLat);
    const lng = parseFloat(manualLng);
    if (isNaN(lat) || isNaN(lng)) return;
    applyLocation(lat, lng);
  };

  return (
    <div className="space-y-2">
      {!sdkFailed && (
        <>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="搜索地点，如：深圳北站"
              className="min-w-0 flex-1 rounded-md border border-gray-300 p-2 text-sm"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch();
              }}
              data-testid="place-search-input"
            />
            <button
              type="button"
              onClick={handleSearch}
              disabled={searching || !keyword.trim()}
              data-testid="place-search-button"
              className="shrink-0 rounded-md bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-60"
            >
              {searching ? "搜索中..." : "搜索"}
            </button>
          </div>
          {searchError && <p className="text-xs text-red-500">{searchError}</p>}
          {searchResults.length > 0 && (
            <ul
              className="max-h-56 divide-y divide-gray-100 overflow-auto rounded-lg border border-gray-200 bg-white"
              data-testid="place-search-results"
            >
              {searchResults.map((poi, index) => (
                <li key={`${poi.name}-${index}`}>
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left hover:bg-gray-50"
                    onClick={() => {
                      setKeyword(poi.name);
                      applyLocation(poi.lat, poi.lng, poi.address || poi.name);
                    }}
                  >
                    <span className="block text-sm text-gray-800">{poi.name}</span>
                    {poi.address && (
                      <span className="block text-xs text-gray-400">{poi.address}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="relative">
            <div
              ref={mapRef}
              className="w-full h-64 rounded-lg border border-gray-300"
              data-testid="amap-container"
            />
            <button
              type="button"
              onClick={handleLocate}
              disabled={locating}
              data-testid="locate-button"
              className="absolute right-2 top-2 rounded-md bg-white/95 px-3 py-1.5 text-xs font-medium text-gray-700 shadow ring-1 ring-gray-200 disabled:opacity-60"
            >
              {locating ? "定位中..." : "定位到我"}
            </button>
          </div>
          <p className="text-xs text-gray-500">
            {hint || "点击地图选择上车地点，或搜索地点、点右上角获取当前位置"}
          </p>
        </>
      )}
      {sdkFailed && (
        <div className="w-full h-64 rounded-lg border border-gray-300 bg-gray-50 flex flex-col items-center justify-center space-y-3 p-4" data-testid="amap-fallback">
          <p className="text-sm text-gray-500 text-center">地图未配置或加载失败，请手动输入坐标</p>
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
        <div
          className="rounded-lg border border-blue-100 bg-blue-50/70 px-3 py-2 space-y-0.5"
          data-testid="selected-address"
        >
          <p className="text-xs text-blue-500">上车地点</p>
          <p className="text-sm font-medium text-gray-800">{address}</p>
          {coords && (
            <p className="font-mono text-[11px] text-gray-500">
              {coords.lat.toFixed(6)}, {coords.lng.toFixed(6)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
