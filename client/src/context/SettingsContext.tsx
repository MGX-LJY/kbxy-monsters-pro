import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { backupApi, settingsApi } from '../api';

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
  loadSettings: () => Promise<void>;
  saveSettings: () => Promise<void>;
};

const SettingsContext = createContext<SettingsContextValue | undefined>(undefined);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  // 状态初始化为默认值，然后从后端加载
  const [pageSize, setPageSize] = useState<number>(20);
  const [crawlLimit, setCrawlLimit] = useState<string>('');

  // 备份设置状态
  const [backupSettings, setBackupSettings] = useState<BackupSettings>({
    auto_backup_enabled: false,
    backup_interval_hours: 24,
    max_backups: 30
  });

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
      if (settings.backupSettings) {
        setBackupSettings({
          auto_backup_enabled: settings.backupSettings.auto_backup_enabled || false,
          backup_interval_hours: settings.backupSettings.backup_interval_hours || 24,
          max_backups: settings.backupSettings.max_backups || 30
        });
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
        crawlLimit,
        backupSettings
      });
    } catch (error) {
      console.error('Failed to save settings:', error);
      throw error;
    }
  };

  // 从服务器加载备份配置（保持兼容性）
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

  // 更新服务器备份配置（只更新备份API，不调用saveSettings）
  const updateBackupConfig = async () => {
    try {
      await backupApi.updateConfig(backupSettings);
    } catch (error) {
      console.error('Failed to update backup config:', error);
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
    backupSettings,
    setBackupSettings,
    updateBackupConfig,
    loadBackupConfig,
    loadSettings,
    saveSettings,
  }), [pageSize, crawlLimit, backupSettings]);

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
}