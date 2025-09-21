import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { settingsApi } from '../api';


type SettingsContextValue = {
  pageSize: number;
  setPageSize: (n: number) => void;
  crawlLimit: string;                // 存成字符串，便于空值
  setCrawlLimit: (s: string) => void;
  loadSettings: () => Promise<void>;
  saveSettings: () => Promise<void>;
};

const SettingsContext = createContext<SettingsContextValue | undefined>(undefined);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  // 状态初始化为默认值，然后从后端加载
  const [pageSize, setPageSize] = useState<number>(20);
  const [crawlLimit, setCrawlLimit] = useState<string>('');


  // 从后端加载所有设置
  const loadSettings = async () => {
    try {
      const response = await settingsApi.getSettings();
      const settings = response.data.data;
      
      // 更新各种设置
      if (typeof settings.pageSize === 'number' && settings.pageSize > 0) {
        setPageSize(settings.pageSize);
      }
      if (typeof settings.crawlLimit === 'string') {
        setCrawlLimit(settings.crawlLimit);
      }
    } catch (error) {
      console.error('Failed to load settings:', error);
      // 如果加载失败，尝试从localStorage恢复（兼容性）
      const localPageSize = Number(localStorage.getItem('pageSize'));
      if (Number.isFinite(localPageSize) && localPageSize > 0) {
        setPageSize(localPageSize);
      }
      const localCrawlLimit = localStorage.getItem('crawlLimit');
      if (localCrawlLimit) {
        setCrawlLimit(localCrawlLimit);
      }
    }
  };

  // 保存设置到后端
  const saveSettings = async () => {
    try {
      await settingsApi.updateSettings({
        pageSize,
        crawlLimit
      });
    } catch (error) {
      console.error('Failed to save settings:', error);
      throw error;
    }
  };


  // 初始加载所有设置
  useEffect(() => {
    loadSettings();
  }, []);

  const value = useMemo(() => ({
    pageSize,
    setPageSize,
    crawlLimit,
    setCrawlLimit,
    loadSettings,
    saveSettings,
  }), [pageSize, crawlLimit]);

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
}