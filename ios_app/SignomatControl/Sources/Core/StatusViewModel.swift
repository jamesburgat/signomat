import Foundation

final class StatusViewModel: ObservableObject {
    @Published var manager = BLEManager()
}

