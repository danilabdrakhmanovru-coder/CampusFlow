@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not defined CAMPUSFLOW_PORT set "CAMPUSFLOW_PORT=8768"

docker info --format "{{.ServerVersion}}" >nul 2>&1
if errorlevel 1 (
    echo Start Docker Desktop, wait for it to be ready, and run this file again.
    popd
    exit /b 1
)

set "build=--build"
if /i "%~1"=="--no-build" set "build=--no-build"
if /i "%~1"=="--pull-base" (
    docker pull node:22-alpine
    if errorlevel 1 (
        echo Docker Hub is not reachable. Check Docker Desktop network, proxy or DNS.
        popd
        exit /b 1
    )
)

docker compose -f compose.demo.yaml up %build% -d --wait --wait-timeout 120
set "result=%errorlevel%"
if not "%result%"=="0" (
    echo CampusFlow did not start. See the final Docker error above.
    echo If loading node:22-alpine metadata failed, try: run_dev.cmd --pull-base
    echo To reuse previously built images without updating code: run_dev.cmd --no-build
    popd
    exit /b %result%
)

echo CampusFlow is ready: http://127.0.0.1:%CAMPUSFLOW_PORT%/
popd
exit /b 0
