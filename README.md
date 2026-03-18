# azureauth-bin

[Microsoft Authentication CLI](https://github.com/AzureAD/microsoft-authentication-cli) repackaged as Python wheels for easy installation via `pip` or `uv`.

## Install

```sh
uv tool install azureauth-bin
```

## Usage

```sh
azureauth aad --resource https://management.azure.com
```

## Supported Platforms

| Platform | Wheel tag |
|----------|-----------|
| Linux x64 | `manylinux_2_17_x86_64` |
| Linux ARM64 | `manylinux_2_17_aarch64` |
| macOS x64 | `macosx_12_0_x86_64` |
| macOS ARM64 | `macosx_12_0_arm64` |
| Windows x64 | `win_amd64` |
| Windows ARM64 | `win_arm64` |

## How It Works

This package downloads the official azureauth release archives from
[AzureAD/microsoft-authentication-cli](https://github.com/AzureAD/microsoft-authentication-cli/releases)
and repackages each `.tar.gz` / `.zip` / `.deb` as a platform-specific Python wheel.

A thin Python entry point (`console_scripts`) delegates to the native binary,
so `azureauth` is available on `PATH` after install.

## License

This package redistributes Microsoft Authentication CLI under its
[MIT License](https://github.com/AzureAD/microsoft-authentication-cli/blob/main/LICENSE.txt).
