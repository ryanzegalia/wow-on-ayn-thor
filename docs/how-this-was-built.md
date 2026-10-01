# How this was built

I built this with AI-assisted development, using Claude as a coding assistant.

What that means in practice:

- The debugging (reading Wine and Mesa source, disassembling DLLs, reading logs from the device), the patches, the addons, the scripts and these notes were done with Claude.
- Every Wine, DXVK and driver fix in this repo was run on my own AYN Thor. The addon versions in this repo (FFSpan 2.9.0, FFScale 1.11.0, FFBinds 1.8.4) are the ones installed on it. Where a doc says something works, that's what I saw on my device. Where I haven't tested something, the doc says so.
- I don't know how it behaves on other hardware, other GameNative versions or other Wine builds.

I haven't sent any of these changes upstream. I'm one person using AI, and I don't want to put changes that might be wrong in front of the people who maintain these projects. The patches and the reasoning behind them are here if anyone who knows those codebases wants to check them.

If you find something wrong, please open an issue. I'd rather correct it than leave it up.
