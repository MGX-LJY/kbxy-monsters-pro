import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { backupApi } from '../api';

interface BackupSettings {
  auto_backup_enabled: boolean;
  backup_interval_hours: number;
  max_backups: number;
}

type SettingsContextValue = {
  pageSize: number;
  setPageSize: (n: number) => void;
  crawlLimit: string;                // 存成字符串，便于空值
  setCrawlLimit: (s: string) => void;
  backupSettings: BackupSettings;
  setBackupSettings: (settings: BackupSettings) => void;
  updateBackupConfig: () => Promise<void>;
  loadBackupConfig: () => Promise<void>;
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

  // 备份设置状态
  const [backupSettings, setBackupSettings] = useState<BackupSettings>({
    auto_backup_enabled: false,
    backup_interval_hours: 24,
    max_backups: 30
  });

  // 从服务器加载备份配置
  const loadBackupConfig = async () => {
    try {
      const response = await backupApi.getConfig();
      const config = response.data;
      setBackupSettings({
        auto_backup_enabled: config.auto_backup_enabled || false,
        backup_interval_hours: config.backup_interval_hours || 24,
        max_backups: config.max_backups || 30
      });
    } catch (error) {
      console.error('Failed to load backup config:', error);
    }
  };

  // 更新服务器备份配置
  const updateBackupConfig = async () => {
    try {
      await backupApi.updateConfig(backupSettings);
    } catch (error) {
      console.error('Failed to update backup config:', error);
      throw error;
    }
  };

  // 初始加载备份配置
  useEffect(() => {
    loadBackupConfig();
  }, []);

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
    backupSettings,
    setBackupSettings,
    updateBackupConfig,
    loadBackupConfig,
  }), [pageSize, crawlLimit, backupSettings]);

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
}