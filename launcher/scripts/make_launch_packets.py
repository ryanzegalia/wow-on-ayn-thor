"""Build the fixed-size WinHandler EXEC requests used by wowgo.sh.

Battle.net must already be signed in. These start a second instance of the genuine
launcher; they never manufacture login tokens or start WoW with cached credentials.
"""
import argparse
from pathlib import Path
import struct

# Battle.net's install path inside the Wine prefix (drive C: of the Battle.net container).
BNET = "C:" + r"\Program Files (x86)\Battle.net\Battle.net.exe"

COMMANDS = {
    "retail": "launch WoW",
    "classic": "launch WoWC",
    "beta": "launch WoWF",
}


def packet(parameters):
    filename = b"cmd.exe"
    args = parameters.encode("ascii")
    data = struct.pack("<BIII", 2, len(filename) + len(args) + 8, len(filename), len(args)) + filename + args
    if len(data) > 64:
        raise ValueError("Command exceeds WinHandler's fixed EXEC packet size")
    return data.ljust(64, b"\0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for flavor, command in COMMANDS.items():
        name = f"go-{flavor}.bat"
        batch = '@echo off\r\nset HODLL=libwow64fex.dll\r\nstart "" "' + BNET + '" --exec="' + command + '"\r\n'
        (args.output / name).write_bytes(batch.encode("ascii"))
        (args.output / f"exec-{flavor}.bin").write_bytes(packet(f"/c A:\\{name}"))
        print(flavor, command, "64-byte EXEC")
    select = '@echo off\r\nset HODLL=libwow64fex.dll\r\nstart "" "' + BNET + '" --exec="launch_uid wow_classic_beta"\r\n'
    (args.output / "select-beta.bat").write_bytes(select.encode("ascii"))
    (args.output / "select-beta.bin").write_bytes(packet("/c A:\\" + "select-beta.bat"))


if __name__ == "__main__":
    main()
