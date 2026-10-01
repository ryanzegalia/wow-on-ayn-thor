@echo off
cd /d "%~dp0"
echo === bnet-setup %date% %time% > bnet-setup.log
set WINEDLLOVERRIDES=dxgi,d3d11,d3d10core=n,b
set HODLL=wowbox64.dll
start "" /wait Battle.net-Setup.exe --lang=enUS --installpath="C:\Program Files (x86)\Battle.net"
echo setup errorlevel %errorlevel% %time% >> bnet-setup.log
taskkill /f /im Battle.net.exe >> bnet-setup.log 2>&1
taskkill /f /im Agent.exe >> bnet-setup.log 2>&1
set HODLL=libwow64fex.dll
start "" "C:\Program Files (x86)\Battle.net\Battle.net.exe"
echo === relaunched under FEX %time% >> bnet-setup.log
