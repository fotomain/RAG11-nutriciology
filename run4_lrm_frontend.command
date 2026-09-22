#!/bin/zsh
# Expo (React Native) app: web on :8081. Start run3_lrm_fastapi.command first (API :8000).
cd "$(dirname "$0")/stage9_frontend" || exit 2
[ -d node_modules ] || npm install || exit 1
npx expo start --web --port 8081
