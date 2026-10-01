# Battle.net on the Thor

Battle.net itself runs inside a GameNative container, signs in, and launches the native ARM64 WoW client. These files set that container up. The launch side is `wowgo.sh` and `make_launch_packets.py` in [launcher/scripts/](../../launcher/scripts/README.md).

Battle.net is a 32-bit x86 Windows app, so it runs through one of GameNative's x86 translators. Wine picks the translator per process from `HODLL` in the Windows environment, which is why the batch files set it.

| File | What it does |
|---|---|
| `bnet-setup.bat` | Runs Blizzard's `Battle.net-Setup.exe` (put it next to this file) under Box64 (`HODLL=wowbox64.dll`), installs to `C:\Program Files (x86)\Battle.net` in the prefix, then closes it and starts Battle.net again under FEX (`HODLL=libwow64fex.dll`). |
| `launch-bnet.bat` | The Battle.net container's `launch.bat`: starts Battle.net under FEX. |
| `wow_productdb.py` | Runs on a PC. Writes the two records Battle.net's Agent needs to find a WoW install it didn't install itself: the Agent's `product.db` and `<install>/.product.db`. `--arm64` changes the installed tags from "Windows x86_64" to "Windows arm64". Stop Battle.net first. Usage is in its docstring. |
| `provision_graphics.py` | Runs on a PC over adb. Gives the Battle.net container its own DXVK content: the ARM64 DXVK 3.1.1 build in system32 for WoW and GameNative's i686 DXVK 2.7.1 in syswow64 for Battle.net. It also changes Battle.net's settings file in that prefix, after a backup. It refuses to run while the fork app is open. |
| `dxvk-dualarch-profile.json` | The GameNative content profile `provision_graphics.py` installs with those DLLs. |

The container ids in the Python files (1835007374 for Battle.net, 1285328983 for the retail container) are my install's ids. Change them to yours.

The Wine fix Battle.net needs to write to the game folder on Android storage is in `patches/`, not here.
