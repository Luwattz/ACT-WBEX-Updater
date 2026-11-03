补齐第三方开源组件的许可证、版权及免责声明，项目自身继续采用 MIT License。

- ZIP 与单文件 EXE 均包含原始许可文本、组件清单和来源校验信息。
- 窗口右上角“许可证”可离线查看并保存全部声明。
- 新增 `--export-licenses <新目录>`，无需联网即可导出 EXE 内置的许可文件。
- Windows 发布构建锁定 Python 3.13.15、PyInstaller 6.16.0，并核验底层运行库版本。

下载：完整解压 ZIP 后运行 EXE 并保留 `_internal`；单文件 EXE 可独立运行。
`THIRD_PARTY_LICENSES.zip` 提供第三方许可原文，`BUILD-INFO.json` 记录构建组件，
`VERIFICATION.json` 记录两种发行布局的验证结果，`SHA256SUMS.txt` 提供附件校验值。

验证：Windows 运行 108 项测试，107 项通过、1 项跳过。两种发行布局均通过独立目录
启动自检、PE 文件/产品版本与公司信息核对、完整许可证离线导出验证。

请在更新 ACT 插件前保存工作并关闭 Workbench、Mechanical、SpaceClaim。
