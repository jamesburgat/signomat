import Combine
import Foundation

final class StatusViewModel: ObservableObject {
    let manager = BLEManager()

    private var cancellables: Set<AnyCancellable> = []

    init() {
        manager.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.objectWillChange.send()
            }
            .store(in: &cancellables)
    }
}
