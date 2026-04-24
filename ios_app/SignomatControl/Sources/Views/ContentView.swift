import CoreLocation
import Foundation
import MapKit
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var viewModel: StatusViewModel
    @AppStorage("previewBaseURL") private var previewBaseURL = "http://signomat.local:8000"
    @AppStorage("previewMaxWidth") private var previewMaxWidth = 960
    @State private var previewRevision = UUID().uuidString

    private let commandGrid: [GridItem] = [
        GridItem(.flexible()),
        GridItem(.flexible())
    ]
    private let tripCommands: [SignomatCommand] = [.startTrip, .stopTrip, .saveDiagnosticSnapshot]
    private let recordingCommands: [SignomatCommand] = [.startRecording, .stopRecording]
    private let inferenceCommands: [SignomatCommand] = [.enableInference, .disableInference]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    previewCard
                    tripActionCard
                    alertCard
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

    private var previewCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Troubleshooting Preview")
                .font(.headline)

            Text("Use the Pi local API for a quick pre-drive frame check. BLE stays in charge of control and status, while preview stays lightweight on local network.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            TextField("Pi local API URL", text: $previewBaseURL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .textFieldStyle(.roundedBorder)

            HStack(spacing: 10) {
                Button("Refresh Frame") {
                    refreshPreview()
                }
                .buttonStyle(.borderedProminent)
                .disabled(previewSnapshotURL == nil)

                if let previewPageURL {
                    Link("Open Live Preview", destination: previewPageURL)
                        .buttonStyle(.bordered)
                }
            }

            if let previewSnapshotURL {
                AsyncImage(url: previewSnapshotURL, transaction: Transaction(animation: .easeInOut(duration: 0.2))) { phase in
                    switch phase {
                    case .empty:
                        previewPlaceholder(
                            title: "Loading frame...",
                            message: "Fetching a still image from \(previewHostLabel)."
                        )
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                            .frame(maxWidth: .infinity)
                            .frame(minHeight: 220)
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                    case .failure:
                        previewPlaceholder(
                            title: "Preview unavailable",
                            message: "Make sure the phone can reach \(previewHostLabel) and the Pi local API is running."
                        )
                    @unknown default:
                        previewPlaceholder(
                            title: "Preview unavailable",
                            message: "The still frame could not be rendered."
                        )
                    }
                }
                .frame(maxWidth: .infinity)
                .background(Color.secondary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 16))
            } else {
                previewPlaceholder(
                    title: "Enter a Pi URL",
                    message: "Example: http://signomat.local:8000 or http://192.168.4.1:8000"
                )
            }

            Text("Snapshot endpoint: /preview.jpg. Live tuning page: /preview.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
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
            statusRow("Inference", status.inf ? "Enabled" : "Disabled")
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

    @ViewBuilder
    private var alertCard: some View {
        if let alert = viewModel.manager.status.alert {
            VStack(alignment: .leading, spacing: 8) {
                Label(alert.title, systemImage: "exclamationmark.triangle.fill")
                    .font(.headline)
                Text(alert.message)
                    .font(.subheadline)
                Text(alert.level.capitalized)
                    .font(.caption)
                    .fontWeight(.semibold)
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(alert.level == "critical" ? Color.red.opacity(0.18) : Color.yellow.opacity(0.18))
            .clipShape(RoundedRectangle(cornerRadius: 20))
        }
    }

    private var tripActionCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Trip Controls")
                .font(.headline)
            Text(viewModel.manager.status.trip ? "Trip is active. Stop it when the drive ends." : "Start a trip to begin logging and automatic recording.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            VStack(spacing: 12) {
                largeCommandButton(.startTrip, tint: .green)
                largeCommandButton(.stopTrip, tint: .red)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var categoryCard: some View {
        let status = viewModel.manager.status
        let categories = viewModel.manager.status.signCategories.sorted { lhs, rhs in
            if lhs.value == rhs.value {
                return lhs.key < rhs.key
            }
            return lhs.value > rhs.value
        }
        let recentSigns = status.recentSigns

        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Signs This Trip")
                    .font(.headline)
                Spacer()
                Text("\(status.det)")
                    .font(.headline)
            }
            if recentSigns.isEmpty {
                Text("No classified signs logged yet for this trip.")
                    .foregroundStyle(.secondary)
            } else {
                Text("Recent Classified Signs")
                    .font(.subheadline)
                    .fontWeight(.semibold)
                ForEach(recentSigns) { sign in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(displaySignLabel(sign.label))
                                .fontWeight(.semibold)
                            if let timestamp = sign.timestamp {
                                Text(timestamp)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        if let confidence = sign.confidence {
                            Text(String(format: "%.0f%%", confidence * 100))
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if !categories.isEmpty {
                Divider()
                Text("Category Totals")
                    .font(.subheadline)
                    .fontWeight(.semibold)
                ForEach(categories, id: \.key) { entry in
                    HStack {
                        Text(displaySignLabel(entry.key))
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
            Text("More Actions")
                .font(.headline)
            Text("Trips start recording automatically. Use these only when you want to override recording or save a snapshot.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            LazyVGrid(columns: commandGrid, spacing: 12) {
                ForEach(tripCommands.filter { $0 == .saveDiagnosticSnapshot }) { command in
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

            Text("Inference")
                .font(.subheadline)
                .fontWeight(.semibold)
            LazyVGrid(columns: commandGrid, spacing: 12) {
                ForEach(inferenceCommands) { command in
                    commandButton(command)
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private func previewPlaceholder(title: String, message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline)
                .fontWeight(.semibold)
            Text(message)
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(minHeight: 220)
        .padding()
    }

    private func commandButton(_ command: SignomatCommand) -> some View {
        Button(command.title) {
            viewModel.manager.send(command)
        }
        .buttonStyle(.borderedProminent)
        .disabled(!viewModel.manager.isConnected)
    }

    private func largeCommandButton(_ command: SignomatCommand, tint: Color) -> some View {
        Button(command.title) {
            viewModel.manager.send(command)
        }
        .buttonStyle(.borderedProminent)
        .tint(tint)
        .font(.headline)
        .frame(maxWidth: .infinity)
        .controlSize(.large)
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

    private func displaySignLabel(_ label: String) -> String {
        label.replacingOccurrences(of: "_", with: " ").capitalized
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

    private var previewHostLabel: String {
        normalizedPreviewBaseURL?.host ?? previewBaseURL
    }

    private var normalizedPreviewBaseURL: URL? {
        let trimmed = previewBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let candidate = trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") ? trimmed : "http://\(trimmed)"
        return URL(string: candidate)
    }

    private var previewSnapshotURL: URL? {
        guard let baseURL = normalizedPreviewBaseURL else { return nil }
        var components = URLComponents(url: baseURL.appending(path: "preview.jpg"), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "max_width", value: "\(previewMaxWidth)"),
            URLQueryItem(name: "_rev", value: previewRevision)
        ]
        return components?.url
    }

    private var previewPageURL: URL? {
        normalizedPreviewBaseURL?.appending(path: "preview")
    }

    private func refreshPreview() {
        previewRevision = UUID().uuidString
    }
}
