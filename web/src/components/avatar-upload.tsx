"use client";

import { useState, useRef, useCallback } from "react";
import Cropper, { Area } from "react-easy-crop";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import type { AvatarUploadResponse } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

interface AvatarUploadProps {
  /** 当前头像 URL，来自 user.avatar_url */
  currentAvatarUrl: string | null;
  /** 头像上传成功后的回调，父组件可更新 store */
  onSuccess?: () => void;
  /** 是否正在加载中 */
  disabled?: boolean;
}

export default function AvatarUpload({ currentAvatarUrl, onSuccess, disabled }: AvatarUploadProps) {
  const { setTokens } = useAuthStore();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 裁剪状态
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  /** 文件选择处理 */
  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // 验证文件类型
    if (!file.type.startsWith("image/")) {
      setError("仅支持图片文件");
      return;
    }
    // 验证文件大小（5MB）
    if (file.size > 5 * 1024 * 1024) {
      setError("头像文件大小不能超过 5MB");
      return;
    }

    setError(null);
    const reader = new FileReader();
    reader.onload = () => {
      setImageSrc(reader.result as string);
    };
    reader.readAsDataURL(file);

    // 重置 input 以便重复选择同一文件
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  /** 裁剪完成回调 */
  const onCropComplete = useCallback((_: Area, croppedAreaPixels: Area) => {
    setCroppedAreaPixels(croppedAreaPixels);
  }, []);

  /** 创建裁剪后的 canvas 并返回 Blob */
  const getCroppedBlob = useCallback(
    (imageSrc: string, pixelCrop: Area): Promise<Blob> => {
      return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => {
          const canvas = document.createElement("canvas");
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            reject(new Error("无法创建 canvas 上下文"));
            return;
          }

          canvas.width = pixelCrop.width;
          canvas.height = pixelCrop.height;

          ctx.drawImage(
            image,
            pixelCrop.x,
            pixelCrop.y,
            pixelCrop.width,
            pixelCrop.height,
            0,
            0,
            pixelCrop.width,
            pixelCrop.height,
          );

          canvas.toBlob(
            (blob) => {
              if (blob) {
                resolve(blob);
              } else {
                reject(new Error("canvas 转 blob 失败"));
              }
            },
            "image/jpeg",
            0.9,
          );
        };
        image.onerror = () => reject(new Error("图片加载失败"));
        image.src = imageSrc;
      });
    },
    [],
  );

  /** 上传裁剪后的头像 */
  const handleUpload = useCallback(async () => {
    if (!imageSrc || !croppedAreaPixels) return;

    setUploading(true);
    setError(null);
    try {
      const blob = await getCroppedBlob(imageSrc, croppedAreaPixels);
      const formData = new FormData();
      formData.append("file", blob, "avatar.jpg");

      const resp = await apiClient.upload<AvatarUploadResponse>("/auth/avatar", formData);

      // 更新 token（头像上传后签发新 token）
      setTokens(resp.access_token, resp.refresh_token);

      // 关闭裁剪对话框
      setImageSrc(null);
      setZoom(1);
      setCrop({ x: 0, y: 0 });

      // 通知父组件
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "头像上传失败");
    } finally {
      setUploading(false);
    }
  }, [imageSrc, croppedAreaPixels, getCroppedBlob, setTokens, onSuccess]);

  /** 取消裁剪 */
  const handleCancelCrop = useCallback(() => {
    setImageSrc(null);
    setZoom(1);
    setCrop({ x: 0, y: 0 });
    setError(null);
  }, []);

  // 头像完整 URL
  const avatarFullUrl = currentAvatarUrl
    ? `${API_BASE_URL.replace("/api/v1", "")}${currentAvatarUrl}`
    : null;

  return (
    <div className="flex flex-col items-center gap-3">
      {/* 头像显示 */}
      <div className="relative">
        <div className="h-24 w-24 overflow-hidden rounded-full border-2 border-gray-200 bg-gray-100">
          {avatarFullUrl ? (
            <img
              src={avatarFullUrl}
              alt="用户头像"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-3xl text-gray-400">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="48"
                height="48"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </div>
          )}
        </div>
        {/* 更换头像按钮 */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
          className="absolute bottom-0 right-0 flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-blue-500 text-white shadow-sm hover:bg-blue-600 disabled:opacity-50"
          title="更换头像"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={handleFileSelect}
        />
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {/* 裁剪对话框 */}
      {imageSrc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="mx-4 w-full max-w-md rounded-lg bg-white p-4 shadow-xl">
            <h3 className="mb-3 text-lg font-semibold">裁剪头像</h3>
            <div className="relative h-72 w-full overflow-hidden rounded-lg bg-gray-900">
              <Cropper
                image={imageSrc}
                crop={crop}
                zoom={zoom}
                aspect={1}
                cropShape="round"
                showGrid={false}
                onCropChange={setCrop}
                onZoomChange={setZoom}
                onCropComplete={onCropComplete}
              />
            </div>
            {/* 缩放滑块 */}
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-gray-500">缩小</span>
              <input
                type="range"
                min={1}
                max={3}
                step={0.1}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
                className="flex-1 accent-blue-500"
              />
              <span className="text-xs text-gray-500">放大</span>
            </div>
            <div className="mt-3 flex gap-3">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={handleCancelCrop}
                disabled={uploading}
              >
                取消
              </Button>
              <Button
                type="button"
                className="flex-1"
                onClick={handleUpload}
                disabled={uploading}
              >
                {uploading ? "上传中..." : "确认上传"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}