import CoreLocation
import Foundation
import MapKit
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var viewModel: StatusViewModel

    private let commandGrid: [GridItem] = [
        GridItem(.flexible()),
        GridItem(.flexible())
    ]
    private let tripCommands: [SignomatCommand] = [.startTrip, .stopTrip, .saveDiagnosticSnapshot]
    private let recordingCommands: [SignomatCommand] = [.startRecording, .stopRecording]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    statusCard
                    mapCard
                    categoryCard
                    commandCard
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
            recordingBadge(isRecording: status.rec)
            statusRow("Last Detection", status.last ?? "None")
            statusRow("Last Detection Time", status.lastTS ?? "None")
            statusRow("Detections This Trip", "\(status.det)")
            statusRow("GPS", status.gpsFix ? "Fix" : status.gps)
            statusRow("Coordinates", coordinatesText(status))
            statusRow("Speed", speedText(status))
            statusRow("Trail Points", "\(viewModel.manager.tripBreadcrumbs.count)")
            statusRow("Trail Distance", trailDistanceText)
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

    private var categoryCard: some View {
        let categories = viewModel.manager.status.signCategories.sorted { lhs, rhs in
            if lhs.value == rhs.value {
                return lhs.key < rhs.key
            }
            return lhs.value > rhs.value
        }

        return VStack(alignment: .leading, spacing: 12) {
            Text("Signs This Trip")
                .font(.headline)
            if categories.isEmpty {
                Text("No sign categories logged yet for this trip.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(categories, id: \.key) { entry in
                    HStack {
                        Text(entry.key.replacingOccurrences(of: "_", with: " ").capitalized)
                        Spacer()
                        Text("\(entry.value)")
                            .fontWeight(.semibold)
                    }
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var commandCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Trip Controls")
                .font(.headline)
            Text("Trips start recording automatically. Use the recording buttons only if you want to override that during an active trip.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            LazyVGrid(columns: commandGrid, spacing: 12) {
                ForEach(tripCommands) { command in
                    commandButton(command)
                }
            }

            if viewModel.manager.status.trip {
                Text("Recording Override")
                    .font(.subheadline)
                    .fontWeight(.semibold)
                LazyVGrid(columns: commandGrid, spacing: 12) {
                    ForEach(recordingCommands) { command in
                        commandButton(command)
                    }
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private func commandButton(_ command: SignomatCommand) -> some View {
        Button(command.title) {
            viewModel.manager.send(command)
        }
        .buttonStyle(.borderedProminent)
        .disabled(!viewModel.manager.isConnected)
    }

    private var mapCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Trip Map")
                    .font(.headline)
                Spacer()
                Button("Clear Trail") {
                    viewModel.manager.clearTripBreadcrumbs()
                }
                .disabled(viewModel.manager.tripBreadcrumbs.isEmpty)
            }

            if viewModel.manager.tripBreadcrumbs.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("No breadcrumb trail yet")
                        .fontWeight(.semibold)
                    Text("Once the Pi is connected and sending GPS fixes during a trip, the route will draw here.")
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
                .background(Color.secondary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 16))
            } else {
                Map(initialPosition: .automatic) {
                    if viewModel.manager.tripBreadcrumbs.count > 1 {
                        MapPolyline(coordinates: trailCoordinates)
                            .stroke(.blue, lineWidth: 4)
                    }
                    if let latest = viewModel.manager.tripBreadcrumbs.last {
                        Marker("Pi", coordinate: latest.coordinate)
                            .tint(.red)
                    }
                }
                .frame(height: 260)
                .clipShape(RoundedRectangle(cornerRadius: 16))
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

    private func recordingBadge(isRecording: Bool) -> some View {
        HStack {
            Text("Recording")
                .foregroundStyle(.secondary)
            Spacer()
            Label(isRecording ? "Recording Now" : "Not Recording", systemImage: isRecording ? "record.circle.fill" : "pause.circle")
                .fontWeight(.semibold)
                .foregroundStyle(isRecording ? .red : .secondary)
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

    private var trailCoordinates: [CLLocationCoordinate2D] {
        viewModel.manager.tripBreadcrumbs.map(\.coordinate)
    }

    private var trailDistanceText: String {
        let trail = viewModel.manager.tripBreadcrumbs
        guard trail.count > 1 else { return "0 m" }
        var totalMeters: CLLocationDistance = 0
        for index in 1..<trail.count {
            let previous = CLLocation(latitude: trail[index - 1].coordinate.latitude, longitude: trail[index - 1].coordinate.longitude)
            let current = CLLocation(latitude: trail[index].coordinate.latitude, longitude: trail[index].coordinate.longitude)
            totalMeters += current.distance(from: previous)
        }
        if totalMeters >= 1000 {
            return String(format: "%.2f km", totalMeters / 1000)
        }
        return String(format: "%.0f m", totalMeters)
    }
}
