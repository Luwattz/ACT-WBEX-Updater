# ACT WBEX Updater v1.1.0

Intelligent Efficiency Team · Copyright (c) 2026 Intelligent Efficiency Team


推荐给用户分发 **`dist/wbex-updater-folder/ACT_WBEX_Updater.zip` 和 `.wbex` 插件包**。先完整解压 ZIP，再运行文件夹中的 `ACT_WBEX_Updater.exe`；必须保留同级 `_internal` 文件夹，不能只移动 EXE。内置 Python 与 Tcl/Tk，无需提供仓库、`tools`、CMD 或插件源码，也不需要用户安装 Python。

仍可选用单文件版 `dist/wbex-updater/ACT_WBEX_Updater.exe`，该版本可单独复制，但每次启动都要解包运行库，在部分电脑上可能较慢。文件夹版直接使用解压好的运行库。

双击 EXE，将一个 `.wbex` 从资源管理器拖入已打开的窗口，或点击“浏览…”选择插件包，再选择目标 Ansys 版本目录（例如 `C:\Program Files\ANSYS Inc\v241`）。点击 **更新并设为默认**，或先点 **检查（不更改）** 查看安装计划。EXE 所在目录只有一个 WBEX 时，程序自动填入该包；有多个包时手动选择。也可以把一个 WBEX 拖到 EXE 图标上启动并预选该包。

窗口拖放支持中文、空格和大写 `.WBEX` 后缀。每次只接受一个插件包；多文件、其他格式或更新过程中拖入不会覆盖当前选择。拖放只填入路径，仍需点击检查或更新。原生 Windows 拖放不依赖额外安装 Python、Tcl 扩展或第三方库。

更新时若检测到 Workbench、Mechanical 或 SpaceClaim 仍在运行，程序会列出相关进程并询问是否强制关闭。强制关闭可能丢失未保存的工作或计算结果，默认选择“否”：取消本次更新，保存工作并手动关闭后可重试。选择“是”后，程序在后台关闭列出的进程，确认退出后重新检查插件包、配置和安装条件，再继续备份和更新。关闭失败或权限不足时停止更新并提示处理办法；出现新的相关进程时需要重新确认。“检查（不更改）”及命令行更新不会自动关闭进程。

程序合并 `AWP_ROOT*` 环境变量与 Windows 标准 Ansys 安装目录中的有效安装。**只要存在有效的 v241，就默认选择 v241；只有找不到 v241 时，才默认选择最新已安装版本。**多版本同时安装时，可从路径下拉框切换，或浏览/输入自定义路径；手动选择优先于默认规则。界面显示目标版本，例如 **Ansys 2024 R1 (v241)**；未检测到安装时保持空白，提示手动选择。

插件目录、备份和默认加载配置跟随所选版本：选择 v261 时使用该用户的 `Ansys/v261` 配置，不改 v241；选择 v241 时也不会改 v261。

仓库根目录的 `Run.cmd` 是开发环境的源码启动方式，仍依赖同一仓库的 `tools` 和 Python，不能只把 CMD 单独分发给用户。

### 启动速度与计时

界面先显示，Ansys 版本及同目录 WBEX 的检测在后台进行，避免失效环境路径或网络目录使窗口迟迟不出现。检测完成前可手动选择路径；后台结果不会覆盖手动输入，默认仍是 v241 优先。

圆角背景使用较大的中心块平铺，避免微小图片在高 DPI 大窗口中产生大量重复绘制，造成文字逐步出现、残影和按钮延迟。可见窗口响应测试纳入回归检查；隐藏窗口的启动自检不能替代重绘测试。

点击检查或更新时先显示处理中反馈，再由工作线程检查文件是否存在及解析路径。浏览按钮使用已知安装目录或上次成功选择的目录，不在主线程逐层探测用户输入的失效网络路径。

按 Ctrl+D 打开技术详情可查看 `[启动计时]`，分别记录 Python 入口至界面就绪、Ansys 路径检测及后台检测总耗时。**Python 入口之前的单文件 EXE 解包、运行库加载及系统安全扫描不包含在这些计时内。**若点击后等待很久，但这些计时都很短，延迟主要位于计时之前，应在目标机器上检查运行位置、临时目录与安全软件扫描记录；不能仅凭这一现象确认具体是哪一项。

### 高清显示与系统缩放

EXE 内嵌 System DPI aware 清单，源码启动方式也在创建 Tk 窗口前启用相同模式。程序按系统 DPI 绘制字体、圆角、控件间距和窗口尺寸，避免 Windows 把整个窗口及原生文件选择框当作低分辨率位图放大。技术详情和自检报告会记录实际 DPI 与界面缩放比例。

该模式与 Tk 8.6 的全局字体缩放保持一致；已验证 100%、125%、150%、200% 的布局。本机以 144 DPI / 150% 原生绘制。若多显示器的 DPI 不同，移动到与系统 DPI 不同的显示器仍可能被 Windows 缩放；当前没有宣称逐显示器动态重排支持。参见 [Windows DPI 感知模式](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)。

### 简洁窗口与弹窗结果

主窗口仅保留标题、明确的“将 .wbex 文件拖到这里”区域、插件包路径、Ansys 版本路径和检查/更新按钮。拖入区域也可点击选包。运行记录、“准备检查”状态卡片及灰色说明文字已移除。

每次启动默认使用 **Dark** 深色模式，右上角 **Dark / Light** 分段开关可即时切换当前窗口主题。拖放区、路径输入、按钮、版本下拉列表及技术详情使用对应配色；切换不清空输入、不重建窗口，也不会触发检查或安装。两套主题资源预先缓存，操作期间也可切换。

切换器与标题垂直对齐，使用固定文字和单个滑动选中背景。按下时立即反馈，松开后应用主题；指针移到外部松开可取消选择。滑动使用无弹跳的阻尼弹簧，连续点击从当前位置和速度反向，不重启动画。主题及开关位图在首次显示时准备并缓存，动画每帧只移动一个小图像，不重新生成圆角或调整主窗口布局。Tab 可聚焦，方向键选择模式，空格/Enter 切换；键盘操作及关闭 Windows 动画时直接切换。

鼠标切换主题时，主窗口背景、卡片、输入框、按钮、文字、下拉列表及技术详情在约半秒内渐变，避免 Dark → Light 突然整窗变亮。快速反向时从当前亮度和速度继续，保留正在进行的检查或更新。颜色过渡复用现有图片和预先压缩的形状，只更新小型 PNG 调色板，不逐帧创建新主题或大量图片；圆角透明区域保持不变。可见窗口回归检查会采样实际中间亮度和事件间隔。

Windows 11 原生标题栏背景和文字使用与主界面相同的逐帧配色，主窗口及技术详情窗口同步渐变；不再等渐变结束后才切换标题栏。已按多个中间亮度检查原生标题栏像素及主界面配色一致。旧版 Windows 不支持原生标题栏颜色属性时保留系统明暗标题栏，不重复调用不支持的接口。使用的 [DWM 标题栏颜色属性](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)由 Windows 提供。

检查和更新完成后用成功弹窗告知结果；检查弹窗明确本次未更改文件，更新弹窗说明已设为默认加载，并在存在备份时显示备份位置。失败弹窗包含中文原因、处理办法及原始错误详情；只有后台明确确认回退成功，才说明已恢复更新前的安装状态，恢复不完整时会显示恢复文件位置。

操作期间输入会禁用，相应按钮显示“正在检查…”或“正在更新…”。使用 Windows 系统动画时同时显示进度条；关闭动画时仅显示按钮文字。多文件、错误格式及忙碌拖入用弹窗提示，保留原安装包选择。

路径输入框中的 Enter 执行“检查（不更改）”，安装仍需明确点击更新按钮。Ctrl+O 选包；维护诊断仍可通过 Ctrl+D 打开技术详情、Ctrl+S 导出内存中的诊断记录，不占用主窗口。

工具完全不启动 Workbench、Mechanical 或 Ansys 批处理宿主。更新的是当前 Windows 用户在所选 Ansys 版本中的安装；下次打开 Workbench / Mechanical 时使用新版本，并按 **Load as default** 加载。更新前先保存工作并关闭 Workbench、Mechanical 和 SpaceClaim；工具只检测并阻止冲突，不结束已有进程。

## 执行内容

1. 读取 WBEX 的 GUID、名称、版本和资源，检查资源 CRC 与路径；不运行插件脚本。
2. 按 GUID 找到当前用户的旧 WBEX，而不是只比较文件名。Full 和 Lite 的 GUID 不同，分别更新；它们的名称和 shortid 仍需符合各自身份。
3. 将同 GUID 的旧包及配套资源目录移至备份，复制新 WBEX，提取新资源。不同 GUID 的文件名冲突按 ACT 原生方式追加数字，不覆盖其他插件。
4. 只替换用户 `ACTPreferences.xml` 中 `ACT_DefaultExtensions` 的同 GUID 项，写入新版本。保留其他插件默认项及其余偏好设置。
5. 核对包文件和默认加载项，记录结果。普通异常时自动恢复本次替换的旧包、资源与原配置；断电或强制结束程序后的恢复需使用保留的备份。

备份位于所选用户配置目录下：

```text
%APPDATA%\Ansys\v241\ACT\extension_update_backups\日期时间-GUID\
  old\                         旧 WBEX 与配套资源目录
  ACTPreferences.before.xml    更新前配置（原来存在时）
  ACTPreferences.after.xml     计划写入的配置
  report.json                  成功后的安装记录
```

备份在安装扫描目录之外，不会被当成另一份插件加载。更新失败时弹窗显示恢复文件的位置；若磁盘/权限问题也阻止了回退，错误详情会保留诊断信息，保留备份以便人工恢复。不要在正常更新过程中删除备份或锁文件。

## 命令行与源码启动

独立 EXE 可通过指定 JSON 报告进行无界面检查或更新，不依赖控制台输出：

```powershell
.\ACT_WBEX_Updater.exe "D:\Releases\LumiDyna.wbex" --headless --dry-run --ansys-root "C:\Program Files\ANSYS Inc\v241" --report "D:\Releases\check.json"
```

去掉 `--dry-run` 执行更新。此模式必须指定 `--report`，报告包含结果、日志和错误原因。普通用户直接双击 EXE 即可。

开发环境也可沿用源码启动器：

```powershell
.\Run.cmd "D:\Releases\LumiDyna.wbex" --ansys-root "C:\Program Files\ANSYS Inc\v241" --dry-run
.\Run.cmd "D:\Releases\LumiDyna.wbex" --ansys-root "C:\Program Files\ANSYS Inc\v241"
```

也可直接运行 `python tools/update_wbex.py <包.wbex> ...`。省略 `--ansys-root` 时优先选择 v241，缺少 v241 才选择最新安装版本；显式指定路径时使用指定版本。`--profile-dir` 可指定 Ansys 的用户版本目录，用于隔离测试或明确指定的其他配置；`--preferences-file` 用于存在多个 `UserRegFiles_*` 目录的情况，必须是该配置目录内的 `ACTPreferences.xml`。

独立 EXE 需要 Windows 和现有 Ansys 用户配置。只有开发环境的源码启动方式需要 Python 3.9+ / Tkinter；可通过 `WBEX_PYTHON` 指定解释器。没有 Ansys 用户配置时先完成一次 Workbench 的用户初始化。

## 重新生成独立程序（开发者）

双击根目录 `Build.cmd`，或用带有 PyInstaller 与 Tcl/Tk 的 Windows Python 执行：

```powershell
python tools/build_wbex_updater.py
# 可选单文件版
python tools/build_wbex_updater.py --mode onefile
```

此步骤只打包更新器，不重新构建 WBEX，也不安装插件。默认输出 `dist/wbex-updater-folder/ACT_WBEX_Updater/` 完整文件夹和同级 ZIP，使用说明在文件夹内。`--mode onefile` 输出原来的 `dist/wbex-updater/ACT_WBEX_Updater.exe` 和说明。构建时仅复制七个更新器运行脚本和白名单中的 ICO 图标到独立暂存目录，并审计打包模块，避免把插件源码、构建工具或仓库资源带入程序。开发机需要 PyInstaller；用户机不需要。

`Build.cmd` 生成的 EXE 固定使用同一条默认规则：优先 v241，不存在时才选最新版本。此规则打包在程序内部，不依赖构建机的 Ansys 安装路径或用户机器的额外环境变量。

诊断命令 `ACT_WBEX_Updater.exe --self-check <report.json>` 会初始化内置 GUI 与 Tcl/Tk 后退出，记录独立运行信息，不安装插件。

## 支持范围与验证

- 本机 **Ansys 2024 R1 / v241** 的离线安装布局已按原生 `Ansys.ACT.WorkBench.NativeManager.InstallExtension` / `UninstallExtension` 实现核对：原包放在 `ACT/extensions/<输入包文件名>.wbex`，资源放在同名目录，并去掉压缩资源的首层目录。编译脚本与 XML 的 `content` 缓冲区保留在 WBEX 中。
- 使用实际 Full、Lite WBEX，在临时用户配置中完成 Full 安装、Lite 安装、Full 更新；核对全部资源字节、原包、默认项及旧包备份，真实用户配置未改动。
- 独立 EXE 已复制到仅包含 EXE 和 WBEX 的中文/空格目录，以不相关的工作目录启动，并从 PATH 移除 Python、清除 Python/Tcl 路径变量。内置 GUI 自检、自动识别同目录包、只检查、安装与更新均在临时配置中通过，真实用户配置未改动。
- 多版本检测与界面支持 v241、v261 等版本号，已用临时目录和用户配置验证 v241 优先、缺少 v241 时回退最新版本、手动切换及配置隔离。本机实际仅安装 v241，尚未在真正的 v261 安装中验证完整更新。Ansys 2026 R1 的官方文档仍列出 [`%APPDATA%/Ansys/v261/ACT/extensions`](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/act_dev/act_define_additionalfolders.html) 和 [`v261/Framework/bin/Win64`](https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/wb2_js/wb2js_cmdlineexec.html) 目录约定。
- 单元测试覆盖 GUID 替换、名称/文件名变化、Full/Lite 隔离、文件冲突、只检查、损坏资源、路径越界、运行中阻止及回退。其他 Ansys 版本需在对应环境验证，不能据此保证全部历史或加密 WBEX 格式兼容。
- 工具支持可读取扩展定义及资源 ZIP 的原生 HDF5 WBEX。遇到无法识别的包、多个资源根目录或不能安全识别的已安装包时停止，不猜测删除目标。它检查包内容与安装布局，不替代在 Mechanical 中验证插件实际运行。
- 仅处理所选用户的 `ACT/extensions`，不卸载 `Program Files` 下的系统插件，也不改工程内嵌扩展或源码。
- 若 **Additional Extension Folders** 仍指向相同 GUID 的 XML 开发版，工具会停止并列出冲突文件，避免源代码与 WBEX 同时被发现。先从 Ansys 的附加扩展目录设置中移除对应开发路径；工具不会自动修改开发搜索目录。当前 Full / Lite 源码开发配置可能出现此提示。

如果上次进程被强制结束，`ACT/.wbex-updater.lock` 可能保留。先确认没有更新程序在运行，检查同目录下的备份及安装状态，再移除该锁后重试；不要在另一个更新仍在执行时移除锁。

## 应用图标

EXE、窗口标题栏和任务栏使用统一的蓝色插件包/更新箭头图标。设计 PNG、多尺寸 ICO 及生成提示词保存在 `tools/assets/wbex-updater/`；构建时只打包 ICO，不携带设计母版或图像处理库。自检报告的 `custom_icon_loaded` 表示窗口图标是否加载成功。
