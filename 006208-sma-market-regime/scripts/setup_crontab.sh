#!/bin/bash

################################################################################
# SMA006208 Crontab 自動配置腳本
################################################################################
#
# 用途: 自動配置 crontab，每日 12:30 執行機器人
#
# 使用方式:
#   bash setup_crontab.sh
#
# 清除配置:
#   bash setup_crontab.sh --remove
#
################################################################################

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# 配置
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SCRIPT="${SCRIPT_DIR}/run_daily_bot.sh"
CRON_DESCRIPTION="SMA006208 每日機器人 (台灣時間 12:30)"
CRON_TIME="30 12 * * 1-5"  # 週一至週五 12:30

# ============================================================================
# 函數定義
# ============================================================================

print_header() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║   SMA006208 Crontab 自動配置                                  ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${GREEN}ℹ️  $1${NC}"
}

check_prerequisites() {
    echo "檢查前置條件..."
    echo ""

    # 檢查 run_daily_bot.sh
    if [ ! -f "$RUN_SCRIPT" ]; then
        print_error "找不到執行腳本: $RUN_SCRIPT"
        return 1
    fi
    print_success "找到執行腳本: $RUN_SCRIPT"

    # 檢查執行權限
    if [ ! -x "$RUN_SCRIPT" ]; then
        print_warning "執行腳本沒有執行權限，正在修復..."
        chmod +x "$RUN_SCRIPT"
        if [ -x "$RUN_SCRIPT" ]; then
            print_success "已設置執行權限"
        else
            print_error "無法設置執行權限"
            return 1
        fi
    else
        print_success "執行腳本有正確的權限"
    fi

    echo ""
    return 0
}

setup_crontab() {
    echo "設置 Crontab..."
    echo ""

    # 檢查是否已有相同的 cron job
    if crontab -l 2>/dev/null | grep -q "$RUN_SCRIPT"; then
        print_warning "已存在相同的 cron job，將移除舊版本"
        remove_crontab
    fi

    # 建立臨時檔案存放新 crontab
    local temp_crontab=$(mktemp)

    # 保留現有的 crontab
    crontab -l 2>/dev/null > "$temp_crontab"

    # 加入新的 cron job
    echo "# $CRON_DESCRIPTION" >> "$temp_crontab"
    echo "$CRON_TIME $RUN_SCRIPT" >> "$temp_crontab"
    echo "" >> "$temp_crontab"

    # 應用新的 crontab
    if crontab "$temp_crontab"; then
        print_success "Crontab 已成功配置"
        rm "$temp_crontab"
        return 0
    else
        print_error "Crontab 配置失敗"
        rm "$temp_crontab"
        return 1
    fi
}

remove_crontab() {
    echo "移除舊的 Crontab 配置..."
    echo ""

    # 建立臨時檔案
    local temp_crontab=$(mktemp)

    # 保留現有 crontab 但排除我們的 job
    crontab -l 2>/dev/null | grep -v "$RUN_SCRIPT" | grep -v "$CRON_DESCRIPTION" > "$temp_crontab"

    # 應用新的 crontab
    if crontab "$temp_crontab"; then
        print_success "舊配置已移除"
        rm "$temp_crontab"
        return 0
    else
        print_error "移除失敗"
        rm "$temp_crontab"
        return 1
    fi
}

verify_crontab() {
    echo ""
    echo "驗證 Crontab 配置..."
    echo ""

    if crontab -l 2>/dev/null | grep -q "$RUN_SCRIPT"; then
        echo "當前的 crontab 配置:"
        echo "════════════════════════════════════════════════════════════"
        crontab -l 2>/dev/null | grep -A1 "$CRON_DESCRIPTION"
        echo "════════════════════════════════════════════════════════════"
        print_success "Crontab 配置已驗證"
        return 0
    else
        print_error "找不到 Crontab 配置"
        return 1
    fi
}

show_help() {
    echo "用途:"
    echo "  bash setup_crontab.sh                # 設置 Crontab"
    echo "  bash setup_crontab.sh --remove       # 移除 Crontab 配置"
    echo "  bash setup_crontab.sh --verify       # 驗證配置"
    echo "  bash setup_crontab.sh --help         # 顯示此説明"
    echo ""
}

show_usage_instructions() {
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "                    使用說明"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "1️⃣  檢查執行狀態:"
    echo "   crontab -l"
    echo ""
    echo "2️⃣  監看執行日誌:"
    echo "   tail -f /path/to/logs/crontab_*.log"
    echo ""
    echo "3️⃣  檢查 Crontab 系統日誌:"
    echo "   grep CRON /var/log/syslog | tail -20"
    echo ""
    echo "4️⃣  測試手動執行:"
    echo "   bash $RUN_SCRIPT"
    echo ""
    echo "5️⃣  移除配置:"
    echo "   bash setup_crontab.sh --remove"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo ""
}

# ============================================================================
# 主程式
# ============================================================================

main() {
    local action="${1:---setup}"

    print_header

    case "$action" in
        --setup|"")
            if check_prerequisites; then
                if setup_crontab; then
                    if verify_crontab; then
                        show_usage_instructions
                        exit 0
                    fi
                fi
            fi
            exit 1
            ;;
        --remove)
            print_warning "即將移除 Crontab 配置"
            read -p "確認移除? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                if remove_crontab; then
                    print_success "Crontab 已移除"
                    exit 0
                fi
            else
                print_info "已取消"
                exit 0
            fi
            exit 1
            ;;
        --verify)
            verify_crontab
            exit $?
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            print_error "未知的選項: $action"
            show_help
            exit 1
            ;;
    esac
}

# 執行主程式
main "$@"
