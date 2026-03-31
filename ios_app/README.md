# iOS App Scaffold

This folder contains a SwiftUI + CoreBluetooth scaffold for the personal Signomat control app.

## Generate an Xcode Project

The app uses `XcodeGen` to keep the project file declarative.

```bash
brew install xcodegen
cd ios_app
xcodegen generate
open SignomatControl.xcodeproj
```

## Current Scope

- scan/connect to the Pi BLE service
- show core runtime status
- send the required control commands
- no live media transfer or live preview

