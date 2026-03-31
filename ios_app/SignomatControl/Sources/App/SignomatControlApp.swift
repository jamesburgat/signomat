import SwiftUI

@main
struct SignomatControlApp: App {
    @StateObject private var viewModel = StatusViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(viewModel)
        }
    }
}

