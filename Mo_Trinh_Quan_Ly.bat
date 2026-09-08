@echo off
chcp 65001 >nul
title TikTok Streak Flow - Trinh Quan Ly 24/7
echo ======================================================================
echo       TIKTOK STREAK FLOW - TRÌNH QUẢN LÝ CẤU HÌNH VÀ TỰ ĐỘNG
echo ======================================================================
echo.
echo [1] Dang khoi dong may chu quan ly cuc bo (Local API)...
echo [2] Trinh duyet se tu dong mo tai: http://127.0.0.1:7860
echo [3] Moi thao tac (Them/Xoa ban be, Doi ngon ngu) se DONG BO TRUC TIEP vao .env
echo.
echo * Luu y: Giu nguyen cua so nay khi dang su dung Trinh Quan Ly.
echo         Nhan Ctrl + C de dong may chu khi hoan tat.
echo ======================================================================
echo.

set PYTHONIOENCODING=utf-8
python app_manager.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [LOI] Khong the khoi chay python app_manager.py!
    echo Dang mo giao dien offline...
    start Quan_Ly_TikTok_Streak.html
)
pause
