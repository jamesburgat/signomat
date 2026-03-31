import Foundation
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var viewModel: StatusViewModel

    private let commandGrid: [GridItem] = [
        GridItem(.flexible()),
        GridItem(.flexible())
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    statusCard
                    LazyVGrid(columns: commandGrid, spacing: 12) {
                        ForEach(SignomatCommand.allCases) { command in
                            Button(command.title) {
                                viewModel.manager.send(command)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(!viewModel.manager.isConnected)
                        }
                    }
                }
                .padding(20)
            }
            .navigationTitle("Signomat")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(connectButtonLabel) {
                        viewModel.manager.isConnected ? viewModel.manager.disconnect() : viewModel.manager.connect()
                    }
                    .disabled(viewModel.manager.isScanning && !viewModel.manager.isConnected)
                }
            }
        }
    }

    private var connectButtonLabel: String {
        if viewModel.manager.isConnected {
            return "Disconnect"
        }
        if viewModel.manager.isScanning {
            return "Scanning..."
        }
        return "Connect"
    }

    private var statusCard: some View {
        let status = viewModel.manager.status
        return VStack(alignment: .leading, spacing: 12) {
            Label(
                viewModel.manager.isConnected ? "Connected" : "Disconnected",
                systemImage: viewModel.manager.isConnected ? "dot.radiowaves.left.and.right" : "bolt.horizontal.circle"
            )
            .font(.headline)
            statusRow("Bluetooth", viewModel.manager.bluetoothState)
            statusRow("Connection", viewModel.manager.connectionState)
            statusRow("Discovered Device", viewModel.manager.discoveredPeripheralName ?? "None")
            statusRow("Last Event", viewModel.manager.lastEvent)
            statusRow("Trip ID", status.tripID ?? "None")
            statusRow("Trip Active", status.trip ? "Yes" : "No")
            statusRow("Recording", status.rec ? "Yes" : "No")
            statusRow("Inference", status.inf ? "Enabled" : "Disabled")
            statusRow("Last Detection", status.last ?? "None")
            statusRow("Last Detection Time", status.lastTS ?? "None")
            statusRow("Detections This Trip", "\(status.det)")
            statusRow("GPS", status.gpsFix ? "Fix" : status.gps)
            statusRow("Coordinates", coordinatesText(status))
            statusRow("Speed", speedText(status))
            statusRow("Storage Free", "\(status.freeMB) MB")
            statusRow("Storage Used", "\(status.usedMB) MB")
            statusRow("Upload Queue", "\(status.queue)")
            statusRow("Sync State", status.sync)
            statusRow("Pi Temp", temperatureText(status))
            if let error = viewModel.manager.lastCommandError {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private func statusRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            Text(label)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .fontWeight(.semibold)
                .multilineTextAlignment(.trailing)
        }
    }

    private func coordinatesText(_ status: LiveStatus) -> String {
        guard let lat = status.lat, let lon = status.lon else { return "Unavailable" }
        return String(format: "%.5f, %.5f", lat, lon)
    }

    private func speedText(_ status: LiveStatus) -> String {
        guard let spd = status.spd else { return "Unavailable" }
        return String(format: "%.1f m/s", spd)
    }

    private func temperatureText(_ status: LiveStatus) -> String {
        guard let tempC = status.tempC else { return "Unavailable" }
        return String(format: "%.1f C", tempC)
    }
}
