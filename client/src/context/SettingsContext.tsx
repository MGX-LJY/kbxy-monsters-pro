import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

type SettingsContextValue = {
  pageSize: number;
  setPageSize: (n: number) => void;
  crawlLimit: string;                // 存成字符串，便于空值
  setCrawlLimit: (s: string) => void;
};

const SettingsContext = createContext<SettingsContextValue | undefined>(undefined);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  // 从 localStorage 恢复，找不到就给默认值
  const [pageSize, setPageSize] = useState<number>(() => {
    const v = Number(localStorage.getItem('pageSize'));
    return Number.isFinite(v) && v > 0 ? v : 20;      // 默认 20
  });

  const [crawlLimit, setCrawlLimit] = useState<string>(() => {
    return localStorage.getItem('crawlLimit') || '';  // 默认留空
  });

  // 持久化到 localStorage
  useEffect(() => {
    localStorage.setItem('pageSize', String(pageSize));
  }, [pageSize]);

  useEffect(() => {
    localStorage.setItem('crawlLimit', crawlLimit);
  }, [crawlLimit]);

  const value = useMemo(() => ({
    pageSize,
    setPageSize,
    crawlLimit,
    setCrawlLimit,
  }), [pageSize, crawlLimit]);

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
}