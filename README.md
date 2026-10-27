# ACT WBEX Updater

<img src="tools/assets/wbex-updater/updater.png" width="96" alt="ACT WBEX Updater icon">

**v1.0.0 · Intelligent Efficiency Team**

独立的 Windows ACT `.wbex` 插件更新器。无需启动 Workbench，即可备份并替换当前用户已安装的同 GUID 插件，并设置 **Load as default**。用户不需要安装 Python，也不需要插件源码。

## 下载与使用

从 [Releases](https://github.com/Luwattz/ACT-WBEX-Updater/releases/latest) 下载最新版。

- 推荐 **Windows x64 文件夹 ZIP**：完整解压，运行 `ACT_WBEX_Updater.exe`，保留同级 `_internal` 文件夹。它无需每次解包运行库，启动更快。
- **单文件 EXE** 可单独复制。首次或每次启动时的解包和安全扫描可能较慢。

1. 保存工作并关闭 Workbench、Mechanical、SpaceClaim。
2. 将一个 `.wbex` 拖入窗口，或点击“浏览…”选择文件。
3. 选择 Ansys 安装目录；存在有效 **v241** 时默认选 v241，否则默认选最新版本，也可手动修改。
4. 点击“检查（不更改）”核对，或点击“更新并设为默认”。结果和错误原因通过弹窗显示。
5. 下次启动 Ansys 时加载新版本。

默认 **Dark** 模式，右上角可切换 Dark / Light。选中背景滑动、界面渐变与 Windows 11 标题栏同步；关闭系统动画时直接切换。切换主题不清空输入，也不会触发安装。

支持中文路径、单个 WBEX 拖放、操作前备份及普通失败回退。更多安装布局、备份、诊断和兼容性说明见[用户指南](docs/user-guide.md)。

## 支持范围

- Windows x64；用户需已安装 Ansys，并初始化对应版本的用户配置。
- 本机实际验证过 Ansys 2024 R1 / v241；v261 等多版本选择与配置隔离经过模拟验证，完整安装仍需在对应版本环境确认。
- 支持能够识别定义和资源 ZIP 的原生 HDF5 WBEX。遇到未知或不完整格式会停止，不尝试运行插件代码。
- 仅更新当前用户的 ACT 扩展，不修改系统插件、工程内嵌插件或源码开发路径。

## 从源码运行

需要 Python 3.9+ 和 Tcl/Tk，运行时仅使用 Python 标准库。

```powershell
python tools/wbex_updater_app.py
python tools/wbex_updater_app.py --version
```

也可双击 `Run.cmd`。如需指定解释器，设置 `WBEX_PYTHON`；最终用户使用 Release 文件即可。

无界面检查必须显式提供报告路径：

```powershell
python tools/wbex_updater_app.py Plugin.wbex --headless --dry-run --ansys-root "C:\Program Files\ANSYS Inc\v241" --report check.json
```

## 构建和测试

在 Windows 使用包含 Tcl/Tk 的 Python：

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"
python tools/build_wbex_updater.py
python tools/build_wbex_updater.py --mode onefile
```

也可双击 `Build.cmd`，默认构建文件夹版。构建器只暂存白名单中的运行脚本和 ICO，不依赖任何 LumiDyna 仓库、WBEX 编译器或插件源码。`tools/update_wbex.py` 中的已知 GUID 身份校验是历史包的兼容保护，不需要对应源码。

EXE 的文件版本、产品版本为 **1.0.0**，开发公司及版权信息均为 **Intelligent Efficiency Team**。版本集中定义在 `tools/wbex_updater_version.py`。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证。

Copyright (c) 2026 Intelligent Efficiency Team.
