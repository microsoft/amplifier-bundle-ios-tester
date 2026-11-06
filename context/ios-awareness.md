# iOS testing

For iOS simulator/device UI tasks, use `ios-tester:ios-operator` (driving flows),
`ios-tester:ios-visual-tester` (rendered UI), or `ios-tester:ios-debugger`
(failures). They use `ios_inspector` and carry setup/troubleshooting procedures.
Route Android to android-tester, web UI to browser-tester, and CLI/TUI to
terminal-tester.

Target the intended UDID explicitly. Use the accessibility tree for input and
screenshots for visual judgment. Keep the tool's labeled points/pixels distinct;
do not guess tap coordinates. The free physical-device tier is read-only and
cannot tap. Run `doctor` for missing prerequisites; do not bypass the tool by
driving raw simctl or device utilities. Preserve device/data permissions.

If using the tool directly, first read [iOS procedures](ios-procedures.md),
including Xcode, signing and device-tier limitations. Unrelated work does not
need this manual.
