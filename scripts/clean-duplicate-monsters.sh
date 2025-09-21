#!/bin/bash

# 清理docker-data/images/monsters中的重复妖怪图片
# 保留原始文件(无数字后缀)，删除重复文件(带数字后缀)

set -e

MONSTERS_DIR="docker-data/images/monsters"
BACKUP_DIR="docker-data/backup-monsters-$(date +%Y%m%d_%H%M%S)"
LOG_FILE="duplicate-cleanup.log"

echo "🔍 开始清理重复妖怪图片..." | tee $LOG_FILE
echo "源目录: $MONSTERS_DIR" | tee -a $LOG_FILE
echo "备份目录: $BACKUP_DIR" | tee -a $LOG_FILE

# 检查源目录是否存在
if [ ! -d "$MONSTERS_DIR" ]; then
    echo "❌ 错误: 源目录不存在: $MONSTERS_DIR" | tee -a $LOG_FILE
    exit 1
fi

# 创建备份目录
mkdir -p "$BACKUP_DIR"
echo "✅ 备份目录已创建: $BACKUP_DIR" | tee -a $LOG_FILE

# 统计当前文件数量
TOTAL_FILES=$(ls -1 "$MONSTERS_DIR" | wc -l)
DUPLICATE_FILES=$(ls -1 "$MONSTERS_DIR" | grep -E '\s[0-9]+\.png$' | wc -l)

echo "📊 当前统计:" | tee -a $LOG_FILE
echo "  总文件数: $TOTAL_FILES" | tee -a $LOG_FILE
echo "  重复文件数: $DUPLICATE_FILES" | tee -a $LOG_FILE
echo "  预计保留: $((TOTAL_FILES - DUPLICATE_FILES))" | tee -a $LOG_FILE

# 备份要删除的文件
echo "📦 正在备份重复文件..." | tee -a $LOG_FILE
BACKUP_COUNT=0
ls -1 "$MONSTERS_DIR" | grep -E '\s[0-9]+\.png$' | while read file; do
    cp "$MONSTERS_DIR/$file" "$BACKUP_DIR/"
    BACKUP_COUNT=$((BACKUP_COUNT + 1))
    if [ $((BACKUP_COUNT % 100)) -eq 0 ]; then
        echo "  已备份 $BACKUP_COUNT 个文件..." | tee -a $LOG_FILE
    fi
done

echo "✅ 重复文件备份完成" | tee -a $LOG_FILE

# 删除重复文件
echo "🗑️  正在删除重复文件..." | tee -a $LOG_FILE
DELETED_COUNT=0
ls -1 "$MONSTERS_DIR" | grep -E '\s[0-9]+\.png$' | while read file; do
    rm "$MONSTERS_DIR/$file"
    DELETED_COUNT=$((DELETED_COUNT + 1))
    if [ $((DELETED_COUNT % 100)) -eq 0 ]; then
        echo "  已删除 $DELETED_COUNT 个文件..." | tee -a $LOG_FILE
    fi
done

# 最终统计
FINAL_FILES=$(ls -1 "$MONSTERS_DIR" | wc -l)
ACTUAL_DELETED=$(($TOTAL_FILES - $FINAL_FILES))

echo "✨ 清理完成!" | tee -a $LOG_FILE
echo "📊 最终统计:" | tee -a $LOG_FILE
echo "  原始文件数: $TOTAL_FILES" | tee -a $LOG_FILE
echo "  删除文件数: $ACTUAL_DELETED" | tee -a $LOG_FILE
echo "  剩余文件数: $FINAL_FILES" | tee -a $LOG_FILE
echo "  备份位置: $BACKUP_DIR" | tee -a $LOG_FILE

echo ""
echo "🔍 如需恢复，可以从备份目录复制文件:"
echo "   cp $BACKUP_DIR/* $MONSTERS_DIR/"