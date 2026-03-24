#!/bin/bash

# Selenium Docker 爬蟲啟動腳本

PROJECT_DIR="/home/tom/stock-verify/tdcc-whale-accumulation"
CONTAINER_NAME="selenium-wantgoo"
CONTAINER_PORT=4444

echo "="*80
echo "啟動 Selenium Docker 容器"
echo "="*80

# 檢查容器是否已運行
if docker ps -a | grep -q "$CONTAINER_NAME"; then
    echo "容器 $CONTAINER_NAME 已存在，停止並刪除..."
    docker stop "$CONTAINER_NAME" 2>/dev/null
    docker rm "$CONTAINER_NAME" 2>/dev/null
fi

# 下載並啟動容器
echo "啟動新的 Selenium 容器..."
docker run -d \
    -p $CONTAINER_PORT:4444 \
    --name "$CONTAINER_NAME" \
    --shm-size=2g \
    selenium/standalone-chromium:latest

# 等待容器就緒
echo "等待容器啟動..."
sleep 5

# 檢查容器是否在運行
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo "✓ Selenium 容器已啟動"

    # 運行爬蟲
    echo ""
    echo "開始爬取新聞..."
    echo ""

    cd "$PROJECT_DIR" || exit 1
    python3 v8/news_crawler_docker_selenium.py

    # 清理
    echo ""
    echo "清理容器..."
    docker stop "$CONTAINER_NAME"
    docker rm "$CONTAINER_NAME"
    echo "✓ 完成"
else
    echo "✗ 容器啟動失敗"
    exit 1
fi
