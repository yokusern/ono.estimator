"use client";

import { useState, useEffect } from "react";

interface WindowSize {
  width: number;
  isMobile: boolean;   // < 768px
  isTablet: boolean;   // 768px – 1023px
}

export function useWindowSize(): WindowSize {
  const [size, setSize] = useState<WindowSize>({
    width: typeof window !== "undefined" ? window.innerWidth : 1200,
    isMobile: false,
    isTablet: false,
  });

  useEffect(() => {
    function update() {
      const w = window.innerWidth;
      setSize({ width: w, isMobile: w < 768, isTablet: w >= 768 && w < 1024 });
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return size;
}
