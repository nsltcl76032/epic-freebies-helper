#!/usr/bin/env bash
set -e

# 默认虚拟显示器
export DISPLAY="${DISPLAY:-:99}"

# 启动虚拟 X 屏幕
Xvfb "$DISPLAY" -screen 0 1920x1080x24 &
XVFB_PID=$!

# 等待 Xvfb 准备就绪
for i in {1..10}; do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

# 如果开启了 Web 远程桌面（默认开启），启动 x11vnc 和 noVNC (websockify)
if [ "${ENABLE_NOVNC:-true}" = "true" ]; then
    VNC_PORT="${VNC_PORT:-5900}"
    NOVNC_PORT="${NOVNC_PORT:-6080}"
    echo "Starting x11vnc on :${VNC_PORT} and noVNC on :${NOVNC_PORT}..."
    x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport "$VNC_PORT" -bg -quiet
    websockify --web /usr/share/novnc/ "$NOVNC_PORT" "localhost:$VNC_PORT" &
fi

# 执行主任务（运行 deploy.py）
exec uv run app/deploy.py
