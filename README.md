# Glyph — Word Archive

一个简洁的、离线优先的英语生词本。当前预发布版支持 Linux Wayland / niri；Windows、macOS 和其他桌面的全局快捷键尚未适配。

## 功能

- 复制收录、框选英文 OCR、手动添加单词或短语。
- 本地英文 WordNet 2025、中文 ECDICT 参考；大小写规范、重复收录计数和手动纠错。
- 原网页内嵌查词：Oxford Learner’s、Merriam-Webster、Collins；Cookie 保存在用户自己的电脑。
- 可折叠合集、单组筛选、多选、拖放和批量加入合集。默认组代表未分组词汇。
- 整词复习，三档“生疏 / 不稳 / 熟练”，保存下次复习时间。这是简单的间隔调度，不宣称为经过验证的记忆算法。
- 窗口大小和位置保存；关闭窗口或按呼出快捷键只隐藏，菜单“彻底退出”释放后台进程。
- niri 全局快捷键可选集成；运行时注册，退出或进程异常结束后自动清理。不开机自启。

中文与英文来自不同词典，不能保证逐条对应。完整专业义、新词及释义准确性请核对原词典。

## 安装

推荐从 [Releases](https://github.com/TheNightIsYounger/Glyph-Word-Archive/releases) 下载
`Glyph-0.1.0-x86_64.AppImage`：内含所需 Python/Qt、浏览器引擎、OCR 和离线词典。
运行方法和系统要求见 [AppImage 使用说明](APPIMAGE.md)。
源码压缩包和 AppImage 是两种不同的分发形式，普通使用请选择 AppImage。

如需从源码运行，可下载 `glyph-0.1.0-linux-with-dictionaries.tar.gz`，内含已转换的两个离线词典。它是带数据的源码分发包，**不是含 Python/Qt 运行库的单文件可执行程序**。

在 Arch/CachyOS 上安装依赖：

```sh
sudo pacman -S --needed python python-pyqt6 python-pyqt6-webengine wl-clipboard grim slurp tesseract tesseract-data-eng libnotify
```

其他发行版请从包管理器安装等价组件。也可用虚拟环境安装 `requirements.txt` 中的 Python 依赖，但截图、OCR、剪贴板和通知工具仍需系统提供。

解压进入目录后检查依赖并安装：

```sh
python3 scripts/check_dependencies.py
python3 install.py
```

从应用启动器搜索 Glyph 打开，或执行 `~/.local/bin/glyph`。无需管理员权限，程序安装到 `$XDG_DATA_HOME/glyph/application`，默认是 `~/.local/share/glyph/application`。

### 启用 niri 全局快捷键

```sh
python3 install.py --niri
```

安装器会备份 niri 主配置，并明确加入一条 Glyph 专属 `include`。运行时只更新 `$XDG_CONFIG_HOME/glyph/niri-bindings.kdl`，不搜索替换用户其他快捷键。非默认配置可以加 `--niri-config /absolute/path/config.kdl`。

默认按键：

| 操作 | 默认按键 | 生效条件 |
| --- | --- | --- |
| 收录已复制的英文 | Alt+E | Glyph 运行且 niri 集成已启用 |
| 框选英文 OCR | Alt+Shift+E | 同上 |
| 显示 / 隐藏 | Alt+R | 同上 |
| 切换多选模式 | Ctrl+Shift+M | Glyph 窗口内 |

彻底退出后 Alt+R 不会重新启动程序，请从应用启动器重新打开。首次启动若存在按键冲突，请在 Glyph 设置里更换。默认按键不自动覆盖其他软件绑定。可不启用 niri 集成，继续使用界面入口和软件内快捷键；其他桌面尚未提供通用全局快捷键后端。

**已有开发原型的用户**：先退出旧 Glyph 并移除原先手动添加的三条 Glyph 快捷键，再启用新集成。新安装器不会擅自删除旧配置。安装与升级不要在 Glyph 运行时执行。

### 从源码取得词典

GitHub 源码中不包含大词典和任何个人数据。可阅读第三方许可后，从官方来源下载并本地转换：

```sh
python3 scripts/download_dictionaries.py --accept-licenses
```

ECDICT 固定使用官方提交 `82c9872` 的 CSV；WordNet 使用 2025 版 JSON。脚本下载的是官方公开数据，不爬取在线词典。转换后不保留下载的 CSV/ZIP，保存实际下载文件的 SHA256 和来源。下载数据仍受上游许可和权利范围约束。

### 多选与分组

点搜索框旁“多选”，无需按键即可逐个选择；点“完成”退出。普通模式下 Ctrl+点击增减选择，Shift+点击连续选择。选一个或多个词后点“加入合集”，或在合集页拖到标题。加入普通合集会保留原有归属；拖回默认会确认退出原合集，不删除词条或复习记录。

## 数据与隐私

- 词条、合集、复习与设置：`$XDG_DATA_HOME/glyph/glyph.db`。
- 网页 Cookie、缓存和历史：`$XDG_DATA_HOME/glyph/web-profile`。
- 软件不会自建服务器、上传词库或发送遥测。打开第三方网页时，网站自身仍可能加载统计、广告和 Cookie，受其隐私条款约束。
- OCR 通过用户主动框选执行，图像临时保存，Tesseract 在本机处理，结束后删除临时截图。剪贴板只在用户触发收录时读取。
- niri 键位：`$XDG_CONFIG_HOME/glyph/`；窗口几何由 Qt QSettings 保存在用户配置目录。
- 程序目录和个人目录分开。备份个人数据请先彻底退出；不要将个人目录或浏览会话提交到 GitHub。

## 卸载

先在菜单里彻底退出，然后从下载目录执行：

```sh
python3 install.py --uninstall
```

移除自己的启动入口、图标和 niri include，应用文件移到 `~/.local/share/glyph/uninstalled-application` 便于恢复。个人词库、复习和 Cookie 保留；不自动删除个人数据。

## 开发与发布

```sh
python3 -m unittest discover -s tests
python3 scripts/build_release.py
python3 scripts/build_release.py --dictionary-dir /absolute/path/to/dictionaries
```

第一个构建产生小型源码包，第二个构建产生含两套离线数据的包。构建器采用文件白名单，只接受词典数据表，拒绝打包含个人词条、复习或 Cookie 表的数据库。输出位于 `dist/`，可作为 GitHub Release 附件，勿提交进 Git 源码历史。

## 授权与范围

Glyph 自身程序代码按 GPL-3.0-only 发布，全文见 `LICENSE`。数据、Qt/PyQt、OCR 和其他依赖分别适用其自身许可，详见 `THIRD_PARTY_NOTICES.md` 与 `licenses/`。这些许可不替第三方权利人提供额外授权或不侵权担保。

在线词典显示的是原网站，不附带其离线词库、音频或网页快照，不绕过登录、收费、验证码或其他访问限制。产品名称仅用于指明访问的网站，不表示官方合作或背书。项目图标是自制几何图形，不包含游戏资源。

当前范围：Linux/niri 首版。安装包不是全平台适配承诺；全局快捷键门户、Windows 截图和安装包仍属后续工作。
