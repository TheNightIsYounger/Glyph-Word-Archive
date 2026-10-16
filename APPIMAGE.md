# Glyph AppImage (Linux x86_64)

## 使用

`Glyph-0.1.0-x86_64.AppImage` 包含 Python、所需的 Qt/PyQt 模块、Qt WebEngine
浏览器核心、英文 OCR、截图/剪贴板辅助工具，以及 ECDICT / WordNet 双语词典。
首次运行不下载引擎、不安装 Python，也不开机自启。打开在线词典本身仍需要网络。

当前基础要求：Linux x86_64、glibc 2.39+（例如 Ubuntu 24.04 或更新），正常的
图形桌面和驱动。glibc、C++ 系统运行库、GLib、字体库、Wayland 客户端库及图形驱动
由系统提供；不是 Windows 程序。复制/OCR 使用 Wayland，默认快捷键集成只支持 niri。

先将文件保存在固定位置，再在文件属性里允许执行，或运行：

```sh
chmod +x Glyph-0.1.0-x86_64.AppImage
./Glyph-0.1.0-x86_64.AppImage
```

在程序菜单中选“安装启动入口 / 快捷键…”可明确授权添加启动器与 niri 集成。
也可使用命令行（只安装自己的入口；不会删除旧版本）：

```sh
./Glyph-0.1.0-x86_64.AppImage --install
./Glyph-0.1.0-x86_64.AppImage --install --niri
```

启用集成前，已有原型版的用户需先退出旧版并处理旧的三条 Glyph 手动绑定，
避免键位冲突。不自动替换用户的其他 niri 配置。快捷键只在 Glyph 运行时生效，
彻底退出后释放。移动 AppImage 后请重新安装启动入口。

## 引擎与个人数据

引擎及离线数据留在 AppImage，只读挂载使用。它不会复制一整份引擎到用户缓存。
默认挂载点通常在 `/tmp/.mount_*`；这不是永久安装第二份浏览器。

个人词库和网页数据在 `$XDG_DATA_HOME/glyph/`（默认 `~/.local/share/glyph/`），
快捷键集成在 `$XDG_CONFIG_HOME/glyph/`。程序位置与个人数据分开，升级不覆盖个人数据。
网页 Cookie/缓存保存在 `web-profile/`，可用于保持登录/同意状态；网站仍有权让同意过期。
截图临时文件和自检数据在临时目录，测试结束清理。系统字体/图形栈可能管理自己的缓存。

没有 FUSE 时，AppImage 运行器支持 `--appimage-extract-and-run`，但这种备用模式会
将包解压到临时目录，退出后清理；因此默认不使用它。不要把这个解压行为误认为后台下载。

## 自检和卸载

```sh
./Glyph-0.1.0-x86_64.AppImage --diagnose
./Glyph-0.1.0-x86_64.AppImage --diagnose --gui
./Glyph-0.1.0-x86_64.AppImage --uninstall
```

GUI 自检会短暂打开测试窗口，使用临时词库与网页档案，不读取个人词条。
卸载命令只移除自己的启动入口和集成，保留 AppImage 及个人数据。请先彻底退出应用。

检测到 Intel 显卡及其 Vulkan 驱动时，默认让 Qt/Chromium 都使用 Intel 核显，
不继承强制 NVIDIA 独显的进程变量。只影响 Glyph，不修改系统显卡设置；其他机器
使用系统默认。可用 `GLYPH_GPU=system` 明确恢复系统选择。驱动兼容问题可临时用
`GLYPH_RENDERER=software ./Glyph-0.1.0-x86_64.AppImage` 测试软件渲染；不关闭安全沙盒。

## 构建与发布说明

使用 Ubuntu 24.04 amd64 隔离环境；不要直接复制 CachyOS 的 x86_64_v3 系统运行库。
本项目使用 Bubblewrap 隔离 rootfs，`scripts/in_appimage_build_env.sh` 仅映射项目、
sysroot、设备及 DNS，不映射开发者的家目录。Ubuntu APT 检查仓库签名，PyPI wheels
从官方 HTTPS 索引下载。实际 wheel/deb 版本和摘要在包内
`usr/share/glyph/bundle-manifest.json`。

构建依赖：Python 3.12/venv/pip、squashfs-tools、patchelf、Qt 6.11.2 wheels、
PyQt6/PyQt6-WebEngine 6.11.0、PyQt6-sip 13.13.0，以及 OCR/Wayland/图形系统库。
`scripts/appimage-lock.json` 固定本次构建的 wheel 与运行器摘要。

有 Bubblewrap 的 Linux 构建机可先执行 `python3 scripts/prepare_appimage_build.py`，
它在 `.build/rootfs/` 准备隔离环境，不安装宿主系统包。之后通过
`sh scripts/in_appimage_build_env.sh python ...` 运行下列命令。
已自行准备好依赖的 Ubuntu 构建环境也可直接执行：

```sh
python scripts/build_appimage.py --dictionary-dir /path/to/validated/dictionaries
python scripts/collect_appimage_sources.py
python scripts/build_appimage.py --image-only
```

源码收集脚本需要已启用 `deb-src` 的 Ubuntu 签名索引，收集的是独立的依赖源码，
不是启动应用的必需下载。脚本包含 Ubuntu 补丁/构建文件，并保留 Qt/Chromium 等
组件声明。发布 AppImage 时，应同时提供 Glyph 对应源码、配套依赖源码及构建说明，
不能只上传二进制、删除源码配套附件；源码附件可以比应用本身大很多。
所有依赖分别适用其原许可，不把它们改成 Glyph 自己的 GPL 许可。

包可用 `--appimage-extract` 解开，未施加禁止调试、替换或重新链接 LGPL 库的限制。
源码配套与应用许可说明不保证第三方网站持续可用，也不构成不侵权保证。
