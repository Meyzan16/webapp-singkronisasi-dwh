'use client';

import React, { FC } from 'react';

interface Props {
  text?: string;
  color: string; 
  loading: boolean;
  size?: number; 
}

const CircleLoader: FC<Props> = ({ text, color, loading, size = 30 }) => {
  if (!loading) return null;

  return (
    <div className="flex gap-2">
      {/* Jika ada teks, tampilkan */}
      {text && <span style={{ color }}>{text}</span>}

      <div
        className="border-4 border-t-transparent border-solid rounded-full animate-spin"
        style={{
          borderColor: color,
          borderTopColor: "transparent",
          width: size,
          height: size,
        }}
        data-testid="loader"
      />
    </div>
  );
};

export default CircleLoader;
